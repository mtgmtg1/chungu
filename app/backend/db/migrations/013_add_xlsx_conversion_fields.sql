ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS result_xlsx_basic_storage_path VARCHAR(1024) DEFAULT '',
ADD COLUMN IF NOT EXISTS result_xlsx_advanced_storage_path VARCHAR(1024) DEFAULT '',
ADD COLUMN IF NOT EXISTS result_xlsx_advanced_job_id VARCHAR(32) DEFAULT '',
ADD COLUMN IF NOT EXISTS xlsx_basic_converted BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS xlsx_advanced_converted BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS xlsx_advanced_status VARCHAR(20) DEFAULT '',
ADD COLUMN IF NOT EXISTS xlsx_advanced_recovery_notes JSONB DEFAULT '[]',
ADD COLUMN IF NOT EXISTS xlsx_advanced_refundable BOOLEAN DEFAULT FALSE;
