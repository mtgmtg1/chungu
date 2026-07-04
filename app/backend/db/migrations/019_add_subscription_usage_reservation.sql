-- [Flow: Step 1 (jobs 테이블에 구독 사용량 예약 필드 추가) -> Step 2 (subscription_usages 테이블에 updated_at 추가) -> Step 3 (기존 Job의 예약 기본값 0 설정)]

ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS reserved_basic_pages INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reserved_premium_pages INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reserved_media_seconds INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reserved_period_start TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS xlsx_advanced_reserved_pages INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS xlsx_advanced_reserved_period_start TIMESTAMP WITH TIME ZONE;

ALTER TABLE subscription_usages
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW();
