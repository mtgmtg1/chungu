-- Add developer API key and usage tracking tables, plus is_developer flag on users.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS is_developer BOOLEAN DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS api_keys (
    id VARCHAR(32) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(100) DEFAULT '',
    key_hash VARCHAR(255) NOT NULL,
    prefix VARCHAR(16) NOT NULL,
    scopes JSONB DEFAULT '[]'::jsonb,
    rate_limit_rpm INTEGER DEFAULT 60,
    daily_quota INTEGER,
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMP WITHOUT TIME ZONE,
    expires_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_key_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(prefix);

CREATE TABLE IF NOT EXISTS api_usage (
    id VARCHAR(32) PRIMARY KEY,
    api_key_id VARCHAR(32) NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    endpoint VARCHAR(255) DEFAULT '',
    job_id VARCHAR(32),
    points_spent INTEGER DEFAULT 0,
    http_status INTEGER DEFAULT 0,
    client_ip VARCHAR(64) DEFAULT '',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_usage_api_key_id ON api_usage(api_key_id);
CREATE INDEX IF NOT EXISTS idx_api_usage_user_id ON api_usage(user_id);
CREATE INDEX IF NOT EXISTS idx_api_usage_created_at ON api_usage(created_at);
