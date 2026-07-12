-- [Flow: Step 1 (chat_conversations 테이블 생성) -> Step 2 (job_id+user_id 인덱스 생성)]
-- 에이전트 채팅 대화 이력 저장 테이블.
-- 기존 localStorage 기반 대화 이력을 DB로 이전하여 단일 진실 공급원을 구축한다.
-- 사용자가 Job(프로젝트)별로 나눈 여러 대화 세션과 각 세션의 UIMessage[] 전체를 저장한다.
-- messages: UIMessage[] (Vercel AI SDK 5.x — role, parts, id 등 포함)

CREATE TABLE IF NOT EXISTS chat_conversations (
    id VARCHAR(32) PRIMARY KEY,
    job_id VARCHAR(255) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(100) NOT NULL DEFAULT '',
    messages JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 작업+사용자별 대화 목록 조회용 인덱스
CREATE INDEX IF NOT EXISTS ix_chat_conversations_job_id
    ON chat_conversations (job_id);
CREATE INDEX IF NOT EXISTS ix_chat_conversations_user_id
    ON chat_conversations (user_id);
CREATE INDEX IF NOT EXISTS ix_chat_conversations_job_user_updated
    ON chat_conversations (job_id, user_id, updated_at DESC);
