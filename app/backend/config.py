#!/usr/bin/env python3
# [Flow: Step 1 (.env 로드) -> Step 2 (Settings 객체 생성) -> Step 3 (앱 전역에서 settings import)]
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 서비스
    app_port: int = 28181
    public_base_url: str = "https://proof.teamcat.app"

    # 인프라
    database_url: str = "postgresql+psycopg2://chungu:changeme_postgres@postgres:5432/chungu"
    redis_url: str = "redis://redis:6379/0"

    # DB 커넥션 풀. 대부분의 엔드포인트가 동기 `def` 이라 FastAPI 가 anyio 스레드풀
    # (기본 40스레드)에서 실행한다 — 풀이 그보다 작으면 스레드가 커넥션을 기다리며
    # 요청이 큐잉된다. SQLAlchemy 기본값(5 + 10)은 동시 요청 15개에서 포화한다.
    # ⚠️ pool_size + max_overflow(=40) 를 스레드풀 상한(=40)과 함께 맞춰 둔 값이다.
    # 한쪽만 올리면 다른 쪽이 병목이 되거나 `QueuePool limit` 오류가 난다.
    # (파일 업로드 등 await 가 필요한 6개 핸들러는 여전히 async 로 이벤트 루프에서 돈다 —
    #  목록은 tests/test_no_blocking_async_endpoints.py 의 ALLOWED_ASYNC_WITH_SYNC_DB.)
    db_pool_size: int = 20
    db_max_overflow: int = 20
    # Supabase/pgbouncer 가 유휴 커넥션을 끊어도 죽은 커넥션을 재사용하지 않도록 주기적 재생성.
    db_pool_recycle: int = 1800

    # 보안
    secret_key: str = "changeme_generate_a_long_random_secret"

    # Supabase (셀프호스트 on a1)
    supabase_url: str = "http://192.168.1.50:28000"
    supabase_public_url: str = "https://proof.teamcat.app/supabase"  # 외부 노출 URL (빈 값이면 supabase_url 사용)
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

    # 표 병합 (Excel Basic): 형식 유사도가 이 값 이상이면 연속 표를 병합
    table_merge_similarity_threshold: float = 0.75

    # 스레드 상한 (대용량 처리 안정화)
    llm_max_workers: int = 64       # vLLM 동시 요청 상한 (고배치 최적화)
    media_max_workers: int = 8      # E4B(llama.cpp) 동시 요청 상한 (4슬롯 + 여유)
    ocr_max_workers: int = 8        # Tesseract 동시 처리 상한
    docling_max_workers: int = 16   # a1 CPU Docling 전처리 서비스 동시 요청 상한

    # OCR 엔진 선택은 paddleocr_service 컨테이너의 PADDLEOCR_BACKEND 환경변수로 한다
    # (local_v5 | aistudio | local_vl). 백엔드가 무엇이든 백엔드 코드가 호출하는 계약은
    # /api/convert* 하나이므로, 여기(앱 설정)에는 엔진 선택 값을 두지 않는다.

    # OCR 배치 크기 — 한 요청에 묶어 보낼 페이지 수 (pipeline_vision).
    # AI Studio는 job당 10페이지가 상한이었고, 로컬 PP-OCRv5는 이 제한이 없으므로
    # 로컬 전환 후 이 값을 올리면 왕복 횟수가 줄어든다 (서비스 측 상한은
    # PADDLEOCR_LOCAL_BATCH_MAX_PAGES).
    ocr_batch_size: int = 10

    # Docling 전처리 서비스 (a1 CPU 서버, Tesseract 기본)
    docling_enabled: bool = True
    docling_service_url: str = "http://docling:28182"  # Docker compose 내부 서비스 이름
    docling_refinement_enabled: bool = True  # LLM 후처리 옵션 기본 활성화
    docling_max_images_per_doc: int = 20   # 문서당 LLM 전송 이미지 상한
    docling_image_max_size: int = 1920      # 추출 이미지 최대 긴 변 (px)

    # Unoserver (LibreOffice listener) - 문서(PPTX/DOCX/HWP) PDF 미리보기 변환
    unoserver_enabled: bool = False
    unoserver_host: str = "127.0.0.1"
    unoserver_port: int = 2003
    unoserver_timeout: int = 120  # 변환 타임아웃(초)

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

    # PaddleOCR 자동 파라미터 추천 (Vision LLM 샘플 기반)
    paddleocr_auto_parameter_enabled: bool = True
    paddleocr_sample_dpi: int = 150
    paddleocr_sample_max_tokens: int = 2000

    # Cloudflare Turnstile (CAPTCHA)
    turnstile_site_key: str = ""
    turnstile_worker_url: str = ""

    # Paddle Billing (결제)
    paddle_api_key: str = ""

    # 로컬 개발 전용 인증 bypass (절대 프로덕션에서 활성화하지 마세요)
    # dev_bypass_password는 더 이상 사용하지 않음 — dev_auth.py가 SUPABASE_JWT_SECRET으로 직접 JWT를 발급
    dev_bypass_auth: bool = False
    dev_bypass_email: str = "dev@proof.local"
    dev_bypass_user_id: str = "00000000-0000-0000-0000-000000000001"

    # Node.js AI 백엔드 (Vercel AI SDK 5.x 기반 에이전트 채팅)
    # FastAPI가 /api/ai/* 요청을 이 주소로 리버스 프록시한다.
    # Vite dev server의 proxy와 동일한 역할을 프로덕션/단일 오리진 환경에서 수행한다.
    ai_backend_url: str = "http://localhost:3001"

    # AI 백엔드가 agent step 과금 API를 호출할 때 사용하는 공유 비밀
    ai_backend_secret: str = ""

    # Kata Containers 샌드박스 (에이전트 격리 실행 환경)
    sandbox_enabled: bool = False  # Kata 호스트 서버에 설치된 후 활성화
    sandbox_data_dir: str = "/data/jobs"  # workspace 루트 (virtio-fs 마운트 대상)
    sandbox_runtime: str = "io.containerd.kata-clh.v2"  # 기본 모드 RuntimeClass
    sandbox_runtime_dense: str = "io.containerd.kata-clh-dense.v2"  # 고밀도 모드 (300+ VM)
    sandbox_image: str = "proof-agent:latest"  # containerd 에 로드된 에이전트 이미지
    sandbox_default_timeout: int = 1800  # sandbox 기본 타임아웃 (초, 30분)
    sandbox_max_concurrent: int = 150  # 기본 모드 동시 VM 상한
    sandbox_max_concurrent_dense: int = 300  # 고밀도 모드 동시 VM 상한
    sandbox_browserless_url: str = "http://192.168.1.50:20047"  # a1 기존 browserless 서버

    # 경로
    data_dir: str = "/data"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
