-- jobs 테이블에 Docling LLM 후처리 옵션 컬럼 추가
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS use_docling_refinement BOOLEAN NOT NULL DEFAULT FALSE;

-- app_settings에 Docling 관련 설정이 없으면 기본값 추가
INSERT INTO app_settings (key, value, encrypted) VALUES
('docling_enabled', '1', 0),
('docling_service_url', 'http://192.168.1.100:28182', 0),
('docling_refinement_enabled', '1', 0),
('docling_max_images_per_doc', '20', 0),
('docling_image_max_size', '1920', 0),
('docling_max_workers', '4', 0),
('cost_per_docling_refinement_page_krw', '3', 0),
('cost_per_docling_refinement_page_usd', '0.002', 0)
ON CONFLICT (key) DO NOTHING;
