-- jobs 테이블에 ocr_engine 컬럼 추가 (tesseract/easyocr/rapidocr)
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ocr_engine VARCHAR(10) NOT NULL DEFAULT 'easyocr';
