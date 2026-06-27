#!/usr/bin/env python3
# [Flow: Step 1 (기본값 정의) -> Step 2 (DB에서 읽기/암호 복호화) -> Step 3 (쓰기/암호화) -> Step 4 (최초 부팅 시드)]
from sqlalchemy.orm import Session

from .auth.crypto import decrypt, encrypt
from .config import settings
from .db.models import AppSetting

# 키 -> (기본값, 암호화여부)
SETTING_DEFS: dict[str, tuple[str, bool]] = {
    "llm_endpoint": (settings.default_llm_endpoint, False),
    "llm_model": (settings.default_llm_model, False),
    "llm_api_key": (settings.default_llm_api_key, True),
    "smtp_host": ("", False),
    "smtp_port": ("587", False),
    "smtp_user": ("", False),
    "smtp_password": ("", True),
    "smtp_from": ("", False),
    "smtp_use_tls": ("1", False),
    "download_expire_days": (str(settings.download_expire_days), False),
    "max_pages": (str(settings.max_pages), False),
    "max_file_mb": (str(settings.max_file_mb), False),
    "default_pipeline": ("vision", False),
    # 포인트/결제
    "cost_per_page_krw": ("3", False),
    "cost_per_image_krw": ("3", False),
    "cost_per_audio_sec_krw": ("1", False),
    "cost_per_video_sec_krw": ("10", False),
    "cost_per_page_usd": ("0.002", False),
    "usd_to_krw_rate": ("1500", False),
    "point_packages": ('[{"name":"1,000P","points":1000,"krw":1000,"usd":0.67},{"name":"5,000P","points":5000,"krw":5000,"usd":3.34},{"name":"10,000P","points":10000,"krw":10000,"usd":6.67}]', False),
    "toss_secret_key": ("", True),
    "toss_client_key": ("", False),
    "paddle_api_key": ("", True),
    "paddle_webhook_secret": ("", True),
    "paddle_vendor_id": ("", False),
    # 미디어 전용 LLM (오디오/비디오)
    "media_llm_endpoint": (settings.media_llm_endpoint, False),
    "media_llm_model": (settings.media_llm_model, False),
    "media_llm_api_key": (settings.media_llm_api_key, True),
    # 스레드 상한
    "llm_max_workers": (str(settings.llm_max_workers), False),
    "media_max_workers": (str(settings.media_max_workers), False),
    "docling_max_workers": (str(settings.docling_max_workers), False),
    # Docling 전처리 서비스 (b2 GPU)
    "docling_enabled": (str(int(settings.docling_enabled)), False),
    "docling_service_url": (settings.docling_service_url, False),
    "docling_refinement_enabled": (str(int(settings.docling_refinement_enabled)), False),
    "docling_max_images_per_doc": (str(settings.docling_max_images_per_doc), False),
    "docling_image_max_size": (str(settings.docling_image_max_size), False),
    # Docling LLM 후처리 비용
    "cost_per_docling_refinement_page_krw": ("3", False),
    "cost_per_docling_refinement_page_usd": ("0.002", False),
    # API
    "api_key_default_rate_limit_rpm": ("60", False),
    "api_key_default_daily_quota": ("", False),
    "api_max_concurrent_jobs": ("5", False),
}

SENSITIVE_KEYS = {k for k, (_, enc) in SETTING_DEFS.items() if enc}


def get_setting(db: Session, key: str) -> str:
    """단일 설정값 조회 (없으면 기본값, 민감값은 복호화)."""
    row = db.get(AppSetting, key)
    default, enc = SETTING_DEFS.get(key, ("", False))
    if row is None:
        return default
    return decrypt(row.value) if enc else row.value


def get_all(db: Session, mask_secrets: bool = True) -> dict:
    """전체 설정 조회. mask_secrets=True면 민감값은 '********'로 마스킹."""
    out = {}
    for key, (_default, enc) in SETTING_DEFS.items():
        val = get_setting(db, key)
        if enc and mask_secrets:
            out[key] = "********" if val else ""
        else:
            out[key] = val
    return out


def set_setting(db: Session, key: str, value: str) -> None:
    """단일 설정 저장 (민감값은 암호화). 마스킹 값은 무시."""
    if key not in SETTING_DEFS:
        return
    _default, enc = SETTING_DEFS[key]
    if enc and value == "********":
        return  # 마스킹 그대로면 변경 안 함
    stored = encrypt(value) if enc else value
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=stored, encrypted=1 if enc else 0)
        db.add(row)
    else:
        row.value = stored
        row.encrypted = 1 if enc else 0
    db.commit()


def update_many(db: Session, values: dict) -> None:
    for key, value in values.items():
        if value is None:
            continue
        set_setting(db, key, str(value))


def seed_defaults(db: Session) -> None:
    """최초 부팅: 누락된 설정 키를 기본값으로 채운다."""
    for key, (default, enc) in SETTING_DEFS.items():
        if db.get(AppSetting, key) is None:
            stored = encrypt(default) if (enc and default) else default
            db.add(AppSetting(key=key, value=stored, encrypted=1 if enc else 0))
    db.commit()
