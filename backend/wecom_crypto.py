from __future__ import annotations

import base64
import hashlib
import os
import struct
import time
from dataclasses import dataclass

from config import WECOM_CORP_ID, WECOM_ENCODING_AES_KEY


try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:  # pragma: no cover
    Cipher = None
    algorithms = None
    modes = None


@dataclass
class WeComVerification:
    ok: bool
    reason: str = ""


class WeComCryptoError(RuntimeError):
    pass


def verify_signature(token: str, signature: str, timestamp: str, nonce: str, encrypted: str = "") -> WeComVerification:
    if not token:
        return WeComVerification(False, "WECOM_TOKEN is not configured")
    if not signature:
        return WeComVerification(False, "signature is missing")
    expected = sign(token, timestamp, nonce, encrypted)
    if expected != signature:
        return WeComVerification(False, "signature mismatch")
    return WeComVerification(True)


def sign(token: str, timestamp: str, nonce: str, encrypted: str = "") -> str:
    values = [token, timestamp or "", nonce or ""]
    if encrypted:
        values.append(encrypted)
    return hashlib.sha1("".join(sorted(values)).encode("utf-8")).hexdigest()


def decrypt_message(encrypted: str, corp_id: str | None = None, encoding_aes_key: str | None = None) -> str:
    key = _aes_key(encoding_aes_key or WECOM_ENCODING_AES_KEY)
    decrypted = _aes_cbc_decrypt(base64.b64decode(encrypted), key)
    plain = _pkcs7_unpad(decrypted)
    if len(plain) < 20:
        raise WeComCryptoError("decrypted payload is too short")

    msg_len = struct.unpack("!I", plain[16:20])[0]
    msg = plain[20:20 + msg_len]
    received_corp_id = plain[20 + msg_len:].decode("utf-8")
    expected_corp_id = corp_id or WECOM_CORP_ID
    if expected_corp_id and received_corp_id != expected_corp_id:
        raise WeComCryptoError("corp id mismatch")
    return msg.decode("utf-8")


def encrypt_message(plain_xml: str, corp_id: str | None = None, encoding_aes_key: str | None = None) -> str:
    key = _aes_key(encoding_aes_key or WECOM_ENCODING_AES_KEY)
    corp = (corp_id or WECOM_CORP_ID).encode("utf-8")
    msg = plain_xml.encode("utf-8")
    packed = os.urandom(16) + struct.pack("!I", len(msg)) + msg + corp
    return base64.b64encode(_aes_cbc_encrypt(_pkcs7_pad(packed), key)).decode("utf-8")


def wrap_encrypted_reply(plain_xml: str, token: str, nonce: str | None = None, timestamp: str | None = None) -> str:
    nonce = nonce or os.urandom(8).hex()
    timestamp = timestamp or str(int(time.time()))
    encrypted = encrypt_message(plain_xml)
    signature = sign(token, timestamp, nonce, encrypted)
    return (
        "<xml>"
        f"<Encrypt><![CDATA[{encrypted}]]></Encrypt>"
        f"<MsgSignature><![CDATA[{signature}]]></MsgSignature>"
        f"<TimeStamp>{timestamp}</TimeStamp>"
        f"<Nonce><![CDATA[{nonce}]]></Nonce>"
        "</xml>"
    )


def _aes_key(encoding_aes_key: str) -> bytes:
    if not encoding_aes_key:
        raise WeComCryptoError("WECOM_ENCODING_AES_KEY is not configured")
    if len(encoding_aes_key) != 43:
        raise WeComCryptoError("WECOM_ENCODING_AES_KEY must be 43 chars")
    return base64.b64decode(f"{encoding_aes_key}=")


def _aes_cbc_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    if Cipher is None:
        raise WeComCryptoError("cryptography is required for encrypted WeCom callbacks")
    cipher = Cipher(algorithms.AES(key), modes.CBC(key[:16]))
    decryptor = cipher.decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


def _aes_cbc_encrypt(plaintext: bytes, key: bytes) -> bytes:
    if Cipher is None:
        raise WeComCryptoError("cryptography is required for encrypted WeCom callbacks")
    cipher = Cipher(algorithms.AES(key), modes.CBC(key[:16]))
    encryptor = cipher.encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        raise WeComCryptoError("empty decrypted payload")
    pad = data[-1]
    if pad < 1 or pad > 32:
        raise WeComCryptoError("invalid padding")
    return data[:-pad]


def _pkcs7_pad(data: bytes) -> bytes:
    block_size = 32
    pad = block_size - (len(data) % block_size)
    return data + bytes([pad]) * pad
