-- jobs 테이블에 retry_count 컬럼 추가 (서버 재시작 시 중단된 job 재시도 추적)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;
