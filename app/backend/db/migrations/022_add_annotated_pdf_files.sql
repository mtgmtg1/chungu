-- PDF 하이라이트/여백 주석 결과 파일 목록 (annotation1, annotation2 ...)
ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS annotated_pdf_files JSONB DEFAULT '[]'::jsonb;
