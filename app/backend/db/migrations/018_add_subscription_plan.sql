-- [Flow: Step 1 (사용자 테이블에 구독 필드 추가) -> Step 2 (구독 사용량 테이블 생성) -> Step 3 (기존 사용자를 free 플랜으로 마이그레이션)]

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS subscription_plan VARCHAR(20) DEFAULT 'free',
    ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(20) DEFAULT 'inactive',
    ADD COLUMN IF NOT EXISTS subscription_period_start TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS subscription_period_end TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS subscription_price_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS paddle_subscription_id VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_users_subscription_plan ON users(subscription_plan);
CREATE INDEX IF NOT EXISTS idx_users_subscription_status ON users(subscription_status);

CREATE TABLE IF NOT EXISTS subscription_usages (
    id VARCHAR(32) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    period_start TIMESTAMP WITH TIME ZONE NOT NULL,
    basic_pages INTEGER DEFAULT 0,
    premium_pages INTEGER DEFAULT 0,
    media_seconds INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subscription_usages_user_period ON subscription_usages(user_id, period_start);

UPDATE users SET subscription_plan = 'free', subscription_status = 'active' WHERE subscription_plan IS NULL;
