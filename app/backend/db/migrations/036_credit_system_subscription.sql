-- [Flow: Step 1 (users에 월간 크레딧 지급 시점 컬럼 추가) -> Step 2 (jobs에 부가 기능별 포인트 비용 컬럼 추가) -> Step 3 (비디오/에이전트 스텝 단가 설정)]
-- 구독 요금제를 개별 페이지/오디오/비디오 한도에서 통합 크레딧(포인트) 시스템으로 전환한다.

-- 월간 크레딧이 마지막으로 지급된 시점 (연간 요금제의 월 단위 지급 및 중복 지급 방지용)
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS subscription_credits_granted_at TIMESTAMP WITH TIME ZONE;

-- 메인 변환 작업의 실제 차감 포인트 (실패/취소 시 환불 금액 정확성 확보)
ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS cost_points INTEGER NOT NULL DEFAULT 0;

-- 부가 기능별 실제 차감된 포인트 (실패/취소 시 환불 금액 정확성 확보)
ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS xlsx_advanced_cost_points INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS annotate_cost_points INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS ediscovery_cost_points INTEGER NOT NULL DEFAULT 0;

-- 비디오 초당 비용을 10pt로 변경
UPDATE app_settings
SET value = '10', updated_at = NOW()
WHERE key = 'cost_premium_video_sec_krw';

-- 에이전트 스텝당 비용을 1pt로 추가
INSERT INTO app_settings (key, value, encrypted, updated_at)
VALUES ('cost_agent_step_krw', '1', 0, NOW())
ON CONFLICT (key) DO UPDATE SET value = '1', encrypted = 0, updated_at = NOW();
