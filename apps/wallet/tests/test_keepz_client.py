import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from apps.wallet.keepz_client import KeepzClient, KeepzConfig, KeepzError


pytestmark = [pytest.mark.unit]


def _generate_pem_pair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode('utf-8')
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode('utf-8')
    return private_pem, public_pem


def _build_client() -> KeepzClient:
    return _build_client_with_padding('OAEP')


def _build_client_with_padding(rsa_padding_mode: str) -> KeepzClient:
    private_pem, public_pem = _generate_pem_pair()
    config = KeepzConfig(
        base_url='https://gateway.dev.keepz.me/ecommerce-service',
        identifier='test-identifier',
        integrator_id='integrator-1',
        receiver_id='receiver-1',
        receiver_type='BRANCH',
        provider_public_key=public_pem,
        integrator_private_key=private_pem,
        rsa_padding_mode=rsa_padding_mode,
        default_currency='GEL',
    )
    return KeepzClient(config=config)


@pytest.mark.parametrize('rsa_padding_mode', ['OAEP', 'PKCS1V15'])
def test_encrypt_decrypt_round_trip(rsa_padding_mode: str):
    client = _build_client_with_padding(rsa_padding_mode)
    payload = {'integratorOrderId': 'abc-123', 'amount': '25.00', 'status': 'SUCCESS'}

    encrypted = client.encrypt_payload(payload)
    decrypted = client.decrypt_payload(encrypted)

    assert encrypted['identifier'] == 'test-identifier'
    assert encrypted['aes'] is True
    assert decrypted == payload


def test_encrypt_payload_encrypts_base64_key_and_iv_string():
    client = _build_client()

    encrypted = client.encrypt_payload({'integratorOrderId': 'abc-123'})

    encrypted_keys = base64.b64decode(encrypted['encryptedKeys'])
    decrypted_keys = client._rsa_decrypt(encrypted_keys).decode('utf-8')
    encoded_key, encoded_iv = decrypted_keys.split('.')

    assert encrypted['aes'] is True
    assert len(base64.b64decode(encoded_key)) == 32
    assert len(base64.b64decode(encoded_iv)) == 16


@pytest.mark.parametrize(
    ('encrypted_keys', 'expected_message'),
    [
        (b'missing-separator', 'Invalid Keepz encryptedKeys format.'),
        (b'a.b.c', 'Invalid Keepz encryptedKeys format.'),
        (b'@@@.@@@', 'Invalid Keepz encryptedKeys encoding.'),
        (
            f"{base64.b64encode(b'short-key').decode('ascii')}.{base64.b64encode(b'short-iv').decode('ascii')}".encode('utf-8'),
            'Invalid Keepz encryptedKeys size.',
        ),
    ],
)
def test_invalid_encryptedkeys_payload_raises_keepz_error(encrypted_keys: bytes, expected_message: str):
    client = _build_client()

    with pytest.raises(KeepzError, match=expected_message):
        client._deserialize_encrypted_keys(encrypted_keys)


def test_plain_error_payload_raises_normalized_error():
    client = _build_client()

    with pytest.raises(KeepzError) as exc_info:
        client.decrypt_payload({
            'message': 'Dynamic callback permission missing',
            'statusCode': '6056',
            'exceptionGroup': 'PERMISSION',
        })

    assert exc_info.value.status_code == '6056'
    assert exc_info.value.exception_group == 'PERMISSION'
    assert exc_info.value.message == 'Dynamic callback permission missing'
