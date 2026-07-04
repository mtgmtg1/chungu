-- [Flow: Step 1 (processing_started_at 컬럼 추가) -> Step 2 (total_work_units 컬럼 추가) -> Step 3 (기존 데이터 기본값 설정)]
-- 시간진행바 기준 시점과 혼합 미디어 작업량을 저장하는 컬럼 추가

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP WITHOUT TIME ZONE;

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS total_work_units INTEGER NOT NULL DEFAULT 0;

-- 기존 완료/에러 작업은 processing_started_at이 없어도 시간진행바에 영향을 주지 않으므로 null 유지
-- total_work_units는 기존 데이터에 대해 total_pages로 초기화 (점진적 업데이트 허용)
UPDATE jobs SET total_work_units = GREATEST(total_pages, total_files, 1) WHERE total_work_units = 0;
