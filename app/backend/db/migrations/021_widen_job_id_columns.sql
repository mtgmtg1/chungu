-- annotate_job_id, result_xlsx_advanced_job_id 컬럼 확장
-- Celery task ID는 UUID(36자) 형식이므로 VARCHAR(32)로는 부족해 StringDataRightTruncation 에러 발생
ALTER TABLE jobs ALTER COLUMN annotate_job_id TYPE VARCHAR(64);
ALTER TABLE jobs ALTER COLUMN result_xlsx_advanced_job_id TYPE VARCHAR(64);
