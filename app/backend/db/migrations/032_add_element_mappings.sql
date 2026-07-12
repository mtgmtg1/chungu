-- [Flow: Step 1 (jobs 테이블에 요건사실 퍼즐 매퍼 상태 컬럼 추가)]
-- Evidence-to-Element Mapper — 청구 원인별 법적 요건사실 슬롯에 추출된 증거를 매핑한 퍼즐 상태 저장.
-- element_mappings: {claim_type, overall_progress_percent, elements: [{id, name, description, mapped_evidence: [{evidence_id, text_snippet, source_doc}]}]}

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS element_mappings JSONB NOT NULL DEFAULT '{}'::jsonb;
