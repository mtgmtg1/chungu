-- Add media/file related columns to jobs table for multimedia support.
ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS file_type VARCHAR(20) DEFAULT 'pdf',
    ADD COLUMN IF NOT EXISTS total_files INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS done_files INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS media_duration_seconds INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS extracted_files JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS result_xlsx_storage_path VARCHAR(1024) DEFAULT '',
    ADD COLUMN IF NOT EXISTS result_xlsx_path VARCHAR(1024) DEFAULT '';
