#!/usr/bin/env python3
# [Flow: Step 1 (.env 로드) -> Step 2 (Settings 객체 생성) -> Step 3 (앱 전역에서 settings import)]
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 서비스
    app_port: int = 28181
    public_base_url: str = "http://192.168.1.50:28181"

    # 인프라
    database_url: str = "postgresql+psycopg2://chungu:changeme_postgres@postgres:5432/chungu"
    redis_url: str = "redis://redis:6379/0"

    # 보안
    secret_key: str = "changeme_generate_a_long_random_secret"

    # Supabase (셀프호스트 on a1)
    supabase_url: str = "http://192.168.1.50:28000"
    supabase_public_url: str = ""  # 외부 노출 URL (빈 값이면 supabase_url 사용)
    supabase_service_key: str = ""
    supabase_anon_key: str = ""
    supabase_jwt_secret: str = ""

    # 초기 관리자
    admin_email: str = "mtgmtg@naver.com"
    admin_initial_password: str = "JDg629714!@"

    # 기본 LLM (이미지/PDF 파싱용 vLLM 프록시)
    default_llm_endpoint: str = "http://192.168.1.69:18080/v1"
    default_llm_model: str = "cyankiwi/gemma-4-12B-it-qat-AWQ-INT4"
    default_llm_api_key: str = ""

    # 미디어 전용 LLM (오디오/비디오 파싱용 Gemma-4 E4B)
    media_llm_endpoint: str = "http://192.168.1.82:18080/v1"
    media_llm_model: str = "unsloth/gemma-4-E4B-it-qat-GGUF"
    media_llm_api_key: str = ""

    # 제한
    max_file_mb: int = 200
    max_pages: int = 10000
    download_expire_days: int = 7

    # 스레드 상한 (대용량 처리 안정화)
    llm_max_workers: int = 64       # vLLM 동시 요청 상한 (고배치 최적화)
    media_max_workers: int = 8      # E4B(llama.cpp) 동시 요청 상한 (4슬롯 + 여유)
    ocr_max_workers: int = 8        # Tesseract 동시 처리 상한

    # 경로
    data_dir: str = "/data"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
