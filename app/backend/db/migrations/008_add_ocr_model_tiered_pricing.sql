-- jobs 테이블에 ocr_model 컬럼 추가 (basic/premium)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ocr_model VARCHAR(10) NOT NULL DEFAULT 'premium';

-- 일일 무료 사용량 추적 테이블
CREATE TABLE IF NOT EXISTS daily_usage (
    id VARCHAR(32) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    pages_used INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, date)
);

-- app_settings에 모델별 과금 설정 추가
INSERT INTO app_settings (key, value, encrypted) VALUES
('cost_basic_page_krw', '1', 0),
('cost_premium_page_krw', '5', 0),
('cost_premium_audio_sec_krw', '1', 0),
('cost_premium_video_sec_krw', '5', 0),
('free_daily_pages_basic', '100', 0)
ON CONFLICT (key) DO NOTHING;
