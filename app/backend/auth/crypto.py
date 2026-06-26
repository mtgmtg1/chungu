#!/usr/bin/env python3
# [Flow: Step 1 (SECRET_KEY -> Fernet 키 유도) -> Step 2 (민감값 암/복호화)]
import base64
import hashlib

from cryptography.fernet import Fernet

from ..config import settings


def _fernet() -> Fernet:
    """SECRET_KEY에서 32바이트 Fernet 키를 유도한다."""
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plain: str) -> str:
    if not plain:
        return ""
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""
