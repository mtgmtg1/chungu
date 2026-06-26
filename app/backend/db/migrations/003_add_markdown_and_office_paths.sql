-- Add columns for edited markdown and office conversion outputs.
ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS result_docx_storage_path VARCHAR(1024) DEFAULT '',
    ADD COLUMN IF NOT EXISTS result_pptx_storage_path VARCHAR(1024) DEFAULT '',
    ADD COLUMN IF NOT EXISTS result_edited_md_storage_path VARCHAR(1024) DEFAULT '',
    ADD COLUMN IF NOT EXISTS result_docx_path VARCHAR(1024) DEFAULT '',
    ADD COLUMN IF NOT EXISTS result_pptx_path VARCHAR(1024) DEFAULT '',
    ADD COLUMN IF NOT EXISTS result_edited_md_path VARCHAR(1024) DEFAULT '';

-- Raise default image OCR dpi to 200.
ALTER TABLE jobs
    ALTER COLUMN dpi SET DEFAULT 200;
