from __future__ import annotations

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from .client import TuyaError


def _decrypt_ecb(ciphertext: bytes, key: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


def _encrypt_ecb(plaintext: bytes, key: bytes) -> bytes:
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()


def encrypt_pin(pin: str, ticket_key: str, access_secret: str) -> str:
    """Decrypt Tuya's ticket key, then encrypt a PIN as uppercase hex."""
    try:
        padded_pin_key = _decrypt_ecb(
            bytes.fromhex(ticket_key), access_secret.encode()
        )
        unpadder = PKCS7(algorithms.AES.block_size).unpadder()
        pin_key = unpadder.update(padded_pin_key) + unpadder.finalize()
        padder = PKCS7(algorithms.AES.block_size).padder()
        padded_pin = padder.update(pin.encode("ascii")) + padder.finalize()
        return _encrypt_ecb(padded_pin, pin_key).hex().upper()
    except (ValueError, TypeError) as err:
        raise TuyaError("Tuya password ticket could not be decrypted") from err
