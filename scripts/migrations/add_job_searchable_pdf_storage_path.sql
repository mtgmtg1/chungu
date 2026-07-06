-- jobs 테이블에 searchable_pdf_storage_path 컬럼 추가
-- Phase 1: Searchable PDF 텍스트 레이어 통합
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS searchable_pdf_storage_path VARCHAR(1024) NOT NULL DEFAULT '';
