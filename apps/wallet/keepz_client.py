import base64
import json
import os
from dataclasses import dataclass
from typing import Any

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.conf import settings


class KeepzError(Exception):
    def __init__(self, message: str, status_code: str | int | None = None, exception_group: str | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = str(status_code) if status_code is not None else None
        self.exception_group = exception_group


@dataclass
class KeepzConfig:
    base_url: str
    identifier: str
    integrator_id: str
    receiver_id: str
    receiver_type: str
    provider_public_key: str
    integrator_private_key: str
    rsa_padding_mode: str
    default_currency: str


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len]) * pad_len


def _pkcs7_unpad(data: bytes, block_size: int = 16) -> bytes:
    if not data or len(data) % block_size != 0:
        raise KeepzError('Invalid padded payload.')
    pad_len = data[-1]
    if pad_len < 1 or pad_len > block_size:
        raise KeepzError('Invalid padded payload.')
    if data[-pad_len:] != bytes([pad_len]) * pad_len:
        raise KeepzError('Invalid padded payload.')
    return data[:-pad_len]


def _json_dumps(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


class KeepzClient:
    def __init__(self, config: KeepzConfig | None = None, timeout: int = 15):
        self.config = config or KeepzConfig(
            base_url=settings.KEEPZ_ECOMMERCE_BASE_URL.rstrip('/'),
            identifier=settings.KEEPZ_IDENTIFIER,
            integrator_id=settings.KEEPZ_INTEGRATOR_ID,
            receiver_id=settings.KEEPZ_RECEIVER_ID,
            receiver_type=settings.KEEPZ_RECEIVER_TYPE,
            provider_public_key=settings.KEEPZ_PROVIDER_PUBLIC_KEY,
            integrator_private_key=settings.KEEPZ_INTEGRATOR_PRIVATE_KEY,
            rsa_padding_mode=settings.KEEPZ_RSA_PADDING,
            default_currency=settings.KEEPZ_DEFAULT_CURRENCY,
        )
        self.timeout = timeout

    def encrypt_payload(self, payload: dict[str, Any]) -> dict[str, str]:
        self._validate_keys()
        aes_key = os.urandom(32)
        iv = os.urandom(16)
        encrypted_data = self._aes_encrypt(_json_dumps(payload), aes_key, iv)
        encrypted_key = self._rsa_encrypt(aes_key)
        return {
            'identifier': self.config.identifier,
            'encryptedData': base64.b64encode(encrypted_data).decode('ascii'),
            'encryptedKeys': base64.b64encode(encrypted_key).decode('ascii'),
            'aes': base64.b64encode(iv).decode('ascii'),
        }

    def decrypt_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self._is_plain_error(payload):
            raise KeepzError(
                payload.get('message') or 'Keepz request failed.',
                payload.get('statusCode'),
                payload.get('exceptionGroup'),
            )

        try:
            encrypted_data = base64.b64decode(payload['encryptedData'])
            encrypted_key = base64.b64decode(payload['encryptedKeys'])
            iv = base64.b64decode(payload['aes'])
        except KeyError as exc:
            raise KeepzError(f'Missing Keepz field: {exc.args[0]}') from exc

        aes_key = self._rsa_decrypt(encrypted_key)
        decrypted = self._aes_decrypt(encrypted_data, aes_key, iv)
        return json.loads(decrypted.decode('utf-8'))

    def create_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            f'{self.config.base_url}/api/integrator/order',
            json=self.encrypt_payload(payload),
            timeout=self.timeout,
        )
        return self._parse_response(response)

    def get_order_status(self, integrator_order_id: str) -> dict[str, Any]:
        response = requests.get(
            f'{self.config.base_url}/api/integrator/order/status',
            params=self.encrypt_payload({'integratorOrderId': integrator_order_id}),
            timeout=self.timeout,
        )
        return self._parse_response(response)

    def _parse_response(self, response: requests.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise KeepzError('Keepz returned a non-JSON response.') from exc

        if not response.ok and not self._is_plain_error(payload):
            raise KeepzError(f'Keepz request failed with status {response.status_code}.', response.status_code)

        if self._is_plain_error(payload):
            raise KeepzError(
                payload.get('message') or 'Keepz request failed.',
                payload.get('statusCode') or response.status_code,
                payload.get('exceptionGroup'),
            )

        return self.decrypt_payload(payload)

    def _validate_keys(self) -> None:
        missing = []
        if not self.config.identifier:
            missing.append('KEEPZ_IDENTIFIER')
        if not self.config.provider_public_key:
            missing.append('KEEPZ_PROVIDER_PUBLIC_KEY')
        if not self.config.integrator_private_key:
            missing.append('KEEPZ_INTEGRATOR_PRIVATE_KEY')
        if missing:
            raise KeepzError(f'Missing Keepz configuration: {", ".join(missing)}')

    def _load_public_key(self):
        return serialization.load_pem_public_key(self.config.provider_public_key.encode('utf-8'))

    def _load_private_key(self):
        return serialization.load_pem_private_key(self.config.integrator_private_key.encode('utf-8'), password=None)

    def _build_rsa_padding(self):
        if self.config.rsa_padding_mode.upper() == 'PKCS1V15':
            return padding.PKCS1v15()
        return padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        )

    def _rsa_encrypt(self, plaintext: bytes) -> bytes:
        return self._load_public_key().encrypt(plaintext, self._build_rsa_padding())

    def _rsa_decrypt(self, ciphertext: bytes) -> bytes:
        return self._load_private_key().decrypt(ciphertext, self._build_rsa_padding())

    def _aes_encrypt(self, plaintext: bytes, aes_key: bytes, iv: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
        encryptor = cipher.encryptor()
        return encryptor.update(_pkcs7_pad(plaintext)) + encryptor.finalize()

    def _aes_decrypt(self, ciphertext: bytes, aes_key: bytes, iv: bytes) -> bytes:
        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        return _pkcs7_unpad(padded)

    @staticmethod
    def _is_plain_error(payload: Any) -> bool:
        return isinstance(payload, dict) and ('message' in payload or 'statusCode' in payload)
