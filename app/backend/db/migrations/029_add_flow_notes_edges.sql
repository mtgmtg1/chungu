-- Flow Panel 노트 노드 및 커스텀 엣지 영속화
-- 사용자가 React Flow 캔버스에 추가한 스티키 노트(NoteNode)와 수동 연결(커스텀 엣지)을
-- 작업+사용자별로 저장. 기존 flow_drawings 테이블에 컬럼 추가.
-- note_nodes: NoteNode[] (id, x, y, text, width, height)
-- custom_edges: CustomEdge[] (id, source, target, label)
ALTER TABLE flow_drawings
    ADD COLUMN IF NOT EXISTS note_nodes JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS custom_edges JSONB NOT NULL DEFAULT '[]'::jsonb;
