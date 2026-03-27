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
    private_pem, public_pem = _generate_pem_pair()
    config = KeepzConfig(
        base_url='https://gateway.dev.keepz.me/ecommerce-service',
        identifier='test-identifier',
        integrator_id='integrator-1',
        receiver_id='receiver-1',
        receiver_type='BRANCH',
        provider_public_key=public_pem,
        integrator_private_key=private_pem,
        rsa_padding_mode='OAEP',
        default_currency='GEL',
    )
    return KeepzClient(config=config)


def test_encrypt_decrypt_round_trip():
    client = _build_client()
    payload = {'integratorOrderId': 'abc-123', 'amount': '25.00', 'status': 'SUCCESS'}

    encrypted = client.encrypt_payload(payload)
    decrypted = client.decrypt_payload(encrypted)

    assert encrypted['identifier'] == 'test-identifier'
    assert base64.b64decode(encrypted['aes'])
    assert decrypted == payload


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
