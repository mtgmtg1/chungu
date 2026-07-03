-- USD 크레딧 시스템 전환 마이그레이션
-- [Flow: Step 1 (잔액 변환 KRW→milli-USD) -> Step 2 (자동 충전 컬럼 추가) -> Step 3 (설정값 업데이트)]

-- Step 1: 기존 points_balance KRW → milli-USD 변환 (환율 1500)
-- 예: 1500원 → 1000md ($1.00), 3000원 → 2000md ($2.00)
UPDATE users
SET points_balance = ROUND(points_balance * 1000.0 / 1500)
WHERE points_balance != 0;

-- Step 2: 자동 충전 컬럼 추가
ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_recharge_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_recharge_threshold INTEGER DEFAULT 2000;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_recharge_amount INTEGER DEFAULT 10;
ALTER TABLE users ADD COLUMN IF NOT EXISTS paddle_customer_id VARCHAR(64) DEFAULT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auto_recharge_retries INTEGER DEFAULT 0;

-- Step 3: 설정값 업데이트 — KRW 비용 설정을 milli-USD로 교체
UPDATE app_settings SET value = '1' WHERE key = 'cost_basic_page_krw';
UPDATE app_settings SET value = '5' WHERE key = 'cost_premium_page_krw';
UPDATE app_settings SET value = '1' WHERE key = 'cost_premium_audio_sec_krw';
UPDATE app_settings SET value = '5' WHERE key = 'cost_premium_video_sec_krw';
UPDATE app_settings SET value = '3' WHERE key = 'cost_per_docling_refinement_page_krw';

-- point_packages 설정 제거 (빈 배열로 설정)
UPDATE app_settings SET value = '[]' WHERE key = 'point_packages';

-- Toss 설정 제거
DELETE FROM app_settings WHERE key IN ('toss_secret_key', 'toss_client_key');

-- paddle_price_id 설정 추가 ($1.00 단위 Price ID — 대시보드에서 생성 후 입력 필요)
INSERT INTO app_settings (key, value, encrypted, updated_at)
SELECT 'paddle_price_id', '', 0, NOW()
WHERE NOT EXISTS (SELECT 1 FROM app_settings WHERE key = 'paddle_price_id');

-- auto_recharge_min_threshold 설정 추가
INSERT INTO app_settings (key, value, encrypted, updated_at)
SELECT 'auto_recharge_min_threshold', '500', 0, NOW()
WHERE NOT EXISTS (SELECT 1 FROM app_settings WHERE key = 'auto_recharge_min_threshold');
