-- Flow Panel 드로잉/주석 저장 테이블
-- 사용자가 React Flow 캔버스에 그린 드로잉(SVG path)과 텍스트 주석을 작업+사용자별로 저장.
-- paths: DrawingPath[] (SVG path d 속성 + 스타일 메타데이터)
-- text_annotations: TextAnnotation[] (x, y, text, fontSize, color)
CREATE TABLE IF NOT EXISTS flow_drawings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id VARCHAR(255) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    paths JSONB NOT NULL DEFAULT '[]'::jsonb,
    text_annotations JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 작업+사용자별 1레코드 (upsert용)
CREATE UNIQUE INDEX IF NOT EXISTS flow_drawings_job_user_idx
    ON flow_drawings (job_id, user_id);
