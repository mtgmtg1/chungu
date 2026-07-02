ALTER TABLE jobs
    ADD COLUMN IF NOT EXISTS result_edited_xlsx_storage_path VARCHAR(1024) DEFAULT '';
