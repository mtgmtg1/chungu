-- PDF 하이라이트/여백 주석 기능: OCR bbox 원본 저장 + 주석 상태 추적
ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS annotate_instruction TEXT DEFAULT '',
ADD COLUMN IF NOT EXISTS annotate_mode VARCHAR(20) DEFAULT 'highlight',
ADD COLUMN IF NOT EXISTS annotate_comment_mode VARCHAR(20) DEFAULT 'user_text',
ADD COLUMN IF NOT EXISTS annotate_status VARCHAR(20) DEFAULT '',
ADD COLUMN IF NOT EXISTS annotate_job_id VARCHAR(32) DEFAULT '',
ADD COLUMN IF NOT EXISTS annotate_recovery_notes JSONB DEFAULT '[]',
ADD COLUMN IF NOT EXISTS annotate_refundable BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS annotate_reserved_pages INTEGER DEFAULT 0,
ADD COLUMN IF NOT EXISTS annotate_reserved_period_start TIMESTAMP,
ADD COLUMN IF NOT EXISTS result_ocr_layout_storage_path VARCHAR(1024) DEFAULT '';
