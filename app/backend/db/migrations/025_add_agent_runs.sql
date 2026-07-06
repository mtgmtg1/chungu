-- [Flow: Step 1 (agent_runs 테이블 생성) -> Step 2 (job_id/user_id/thread_id 인덱스 생성)]
-- LangGraph 기반 에이전트 실행 기록 테이블.
-- PDF AI 주석과 마크다운 에디터 AI의 멀티스텝 실행 상태를 추적하고,
-- interrupt가 발생한 경우 사용자 승인/거절을 재개할 수 있도록 thread_id를 저장한다.

CREATE TABLE IF NOT EXISTS agent_runs (
    id VARCHAR(32) PRIMARY KEY,
    job_id VARCHAR(32) REFERENCES jobs(id) ON DELETE SET NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    graph_name VARCHAR(32) NOT NULL DEFAULT '',
    thread_id VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    payload JSONB NOT NULL DEFAULT '{}',
    result JSONB NOT NULL DEFAULT '{}',
    pending_interrupt JSONB,
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_agent_runs_job_id ON agent_runs(job_id);
CREATE INDEX IF NOT EXISTS ix_agent_runs_user_id ON agent_runs(user_id);
CREATE INDEX IF NOT EXISTS ix_agent_runs_thread_id ON agent_runs(thread_id);
