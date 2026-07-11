-- AI 에이전트 도구 승인 모드 설정 컬럼 추가
-- 값: 'ask' (승인 버튼 표시) | 'always' (항상 자동 승인)
ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_tool_approval_mode VARCHAR(10) DEFAULT 'ask';

UPDATE users SET ai_tool_approval_mode = 'ask' WHERE ai_tool_approval_mode IS NULL;
