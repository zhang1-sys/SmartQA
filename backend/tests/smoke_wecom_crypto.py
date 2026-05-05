from __future__ import annotations

import base64
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import wecom_crypto


def main():
    # 43 chars, equivalent to a valid 32-byte AES key after base64 padding.
    aes_key = base64.b64encode(os.urandom(32)).decode("utf-8").rstrip("=")
    corp_id = "ww-test-corp"
    plain = "<xml><Content><![CDATA[hello]]></Content></xml>"

    encrypted = wecom_crypto.encrypt_message(plain, corp_id=corp_id, encoding_aes_key=aes_key)
    decrypted = wecom_crypto.decrypt_message(encrypted, corp_id=corp_id, encoding_aes_key=aes_key)
    assert decrypted == plain

    signature = wecom_crypto.sign("token", "123", "nonce", encrypted)
    verification = wecom_crypto.verify_signature("token", signature, "123", "nonce", encrypted)
    assert verification.ok
    print("wecom crypto ok")


if __name__ == "__main__":
    main()
