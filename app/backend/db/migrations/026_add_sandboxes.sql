-- [Flow: Step 1 (sandboxes 테이블 생성) -> Step 2 (job_id 인덱스) -> Step 3 (상태 인덱스)]
-- Kata Containers 기반 에이전트 샌드박스 실행 기록 테이블.
-- 각 sandbox 는 1개의 Kata VM 에 대응하며, workspace (/data/jobs/{job_id}) 를 마운트한다.

CREATE TABLE IF NOT EXISTS sandboxes (
    id VARCHAR(32) PRIMARY KEY,
    job_id VARCHAR(32) REFERENCES jobs(id) ON DELETE SET NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    container_name VARCHAR(128) NOT NULL DEFAULT '',
    container_id VARCHAR(64) NOT NULL DEFAULT '',
    runtime VARCHAR(32) NOT NULL DEFAULT 'io.containerd.kata-clh.v2',
    status VARCHAR(20) NOT NULL DEFAULT 'creating',
    -- creating / running / stopped / error / destroyed
    workspace_path TEXT NOT NULL DEFAULT '',
    resource_limits JSONB NOT NULL DEFAULT '{"cpu": 1, "memory_mb": 2048}',
    dense_mode BOOLEAN NOT NULL DEFAULT FALSE,
    error TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    destroyed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_sandboxes_job_id ON sandboxes(job_id);
CREATE INDEX IF NOT EXISTS ix_sandboxes_user_id ON sandboxes(user_id);
CREATE INDEX IF NOT EXISTS ix_sandboxes_status ON sandboxes(status);
CREATE INDEX IF NOT EXISTS ix_sandboxes_container_name ON sandboxes(container_name);
