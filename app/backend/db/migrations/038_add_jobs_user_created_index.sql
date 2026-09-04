-- [Flow: Step 1 (jobs 목록 조회 복합 인덱스 추가)]
-- /api/jobs 는 WHERE user_id = ? ORDER BY created_at DESC LIMIT ? 형태로 조회한다.
-- 기존에는 user_id 단일 인덱스만 있어 필터 후 정렬(Sort 노드)이 필요했다.
-- (user_id, created_at DESC) 복합 인덱스로 인덱스 순서만으로 LIMIT 을 만족시킨다.
CREATE INDEX IF NOT EXISTS ix_jobs_user_id_created_at ON jobs (user_id, created_at DESC);

-- 관리자/만료 정리 경로의 전역 최신순 조회용.
CREATE INDEX IF NOT EXISTS ix_jobs_created_at ON jobs (created_at DESC);
