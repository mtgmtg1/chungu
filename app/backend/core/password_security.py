#!/usr/bin/env python3
# [Flow: Step 1 (비밀번호 복잡도 검증) -> Step 2 (HIBP 유출 여부 조회) -> Step 3 (검증 결과 반환)]
"""비밀번호 보안 정책: 복잡도 검증 + HIBP Pwned Passwords 조회."""

import hashlib
import re
import urllib.request

from ..config import settings


def validate_password_strength(password: str) -> dict:
    """
    비밀번호 복잡도 검증.
    반환: {valid: bool, score: int(0-4), issues: list[str]}
    """
    # [Flow: Step 1 (길이 검사) -> Step 2 (문자 종류 검사) -> Step 3 (점수 산정)]
    issues = []
    score = 0

    if len(password) < 8:
        issues.append("too_short")
        return {"valid": False, "score": 0, "issues": issues}

    has_lower = bool(re.search(r"[a-z]", password))
    has_upper = bool(re.search(r"[A-Z]", password))
    has_digit = bool(re.search(r"\d", password))
    has_special = bool(re.search(r"[^a-zA-Z0-9]", password))
    char_types = sum([has_lower, has_upper, has_digit, has_special])

    if char_types < 3:
        issues.append("needs_more_variety")

    if len(password) >= 12:
        score += 1
    if char_types >= 3:
        score += 1
    if char_types >= 4:
        score += 1
    if len(password) >= 16:
        score += 1

    valid = len(issues) == 0
    return {"valid": valid, "score": min(score, 4), "issues": issues}


def check_pwned_password(password: str) -> bool:
    """
    HIBP Pwned Passwords API로 유출된 비밀번호인지 조회.
    반환: True = 유출됨, False = 안전.
    API 실패 시 False 반환 (차단하지 않음).
    """
    # [Flow: Step 1 (SHA1 해시) -> Step 2 (접두부 5자로 API 조회) -> Step 3 (접미부 매칭 확인)]
    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]

    try:
        url = f"https://api.pwnedpasswords.com/range/{prefix}"
        req = urllib.request.Request(url, headers={"User-Agent": "PROOF-Security-Check"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            lines = resp.read().decode("utf-8", errors="replace").splitlines()
        for line in lines:
            parts = line.strip().split(":")
            if len(parts) == 2 and parts[0] == suffix:
                return True
    except Exception:
        pass

    return False
