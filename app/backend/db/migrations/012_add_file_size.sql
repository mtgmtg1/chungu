-- jobs 테이블에 file_size 컬럼 추가 (업로드 원본 파일 크기 저장)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS file_size BIGINT DEFAULT 0;
