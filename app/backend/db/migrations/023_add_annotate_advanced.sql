-- 고급주석(Vision LLM) 여부 플래그
ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS annotate_advanced BOOLEAN DEFAULT FALSE;
