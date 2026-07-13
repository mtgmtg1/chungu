-- [Flow: Step 1 (agent_max_steps 컬럼 추가) -> Step 2 (기본값 100 설정)]
-- AI 에이전트 실행 시 최대 step 수를 사용자별로 저장할 컬럼을 추가한다.
ALTER TABLE users ADD COLUMN IF NOT EXISTS agent_max_steps INTEGER NOT NULL DEFAULT 100;
