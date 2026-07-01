#!/usr/bin/env python3
# [Flow: Step 1 (.env 로드) -> Step 2 (Settings 객체 생성) -> Step 3 (앱 전역에서 settings import)]
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 서비스
    app_port: int = 28181
    public_base_url: str = "https://chungu.teamcat.app"

    # 인프라
    database_url: str = "postgresql+psycopg2://chungu:changeme_postgres@postgres:5432/chungu"
    redis_url: str = "redis://redis:6379/0"

    # 보안
    secret_key: str = "changeme_generate_a_long_random_secret"

    # Supabase (셀프호스트 on a1)
    supabase_url: str = "http://192.168.1.50:28000"
    supabase_public_url: str = "https://chungu.teamcat.app/supabase"  # 외부 노출 URL (빈 값이면 supabase_url 사용)
    supabase_service_key: str = ""
    supabase_anon_key: str = ""
    supabase_jwt_secret: str = ""

    # 초기 관리자
    admin_email: str = "mtgmtg@naver.com"
    admin_initial_password: str = "Jdg629714!@"

    # 기본 LLM (이미지/PDF 파싱용 vLLM 프록시 → 실제 모델은 Gemma-4 26B A4B AWQ)
    default_llm_endpoint: str = "http://192.168.1.69:18080/v1"
    default_llm_model: str = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
    default_llm_api_key: str = ""

    # 미디어 전용 LLM (오디오/비디오 파싱용 Gemma-4 12B GGUF Q4_K_M on llama.cpp)
    media_llm_endpoint: str = "http://192.168.1.82:18080/v1"
    media_llm_model: str = "unsloth/gemma-4-12b-it-GGUF"
    media_llm_api_key: str = ""

    # 제한
    max_file_mb: int = 200
    max_pages: int = 10000
    download_expire_days: int = 7

    # 스레드 상한 (대용량 처리 안정화)
    llm_max_workers: int = 64       # vLLM 동시 요청 상한 (고배치 최적화)
    media_max_workers: int = 8      # E4B(llama.cpp) 동시 요청 상한 (4슬롯 + 여유)
    ocr_max_workers: int = 8        # Tesseract 동시 처리 상한
    docling_max_workers: int = 16   # a1 CPU Docling 전처리 서비스 동시 요청 상한

    # OCR 백엔드 선택 (docling | paddleocr) — URL은 동일하므로 백엔드 교체만으로 전환
    ocr_backend: str = "docling"

    # Docling 전처리 서비스 (a1 CPU 서버, Tesseract 기본)
    docling_enabled: bool = True
    docling_service_url: str = "http://docling:28182"  # Docker compose 내부 서비스 이름
    docling_refinement_enabled: bool = True  # LLM 후처리 옵션 기본 활성화
    docling_max_images_per_doc: int = 20   # 문서당 LLM 전송 이미지 상한
    docling_image_max_size: int = 1920      # 추출 이미지 최대 긴 변 (px)

    # PaddleOCR 폴백 서비스 (AI Studio API 프록시)
    paddleocr_service_url: str = "http://paddleocr_service:8080"
    paddleocr_api_token: str = ""
    paddleocr_api_url: str = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
    paddleocr_fallback_enabled: bool = True
    paddleocr_fallback_daily_limit: int = 20000
    paddleocr_fallback_hourly_quota: int = 800
    paddleocr_fallback_failure_threshold: int = 3
    paddleocr_fallback_failure_window_seconds: int = 60
    paddleocr_fallback_open_seconds: int = 600

    # 경로
    data_dir: str = "/data"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
