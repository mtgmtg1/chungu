-- [Flow: Step 1 (jobs 테이블에 e-Discovery 상태/결과 컬럼 추가) -> Step 2 (인덱스 생성)]
-- e-Discovery GraphRAG 파이프라인 결과 저장 컬럼.
-- 수천 장 단위 법률 문서에서 쟁점/원고/피고/증거 노드를 추출해 그래프 JSON으로 저장.
-- 기존 annotate_* / xlsx_advanced_* 필드 그룹과 동일한 상태 추적/환불 패턴을 따른다.
-- ediscovery_graphs: {nodes: [{id, type, data:{label, page}}], edges: [{id, source, target, type}]}
-- ediscovery_metrics: {total_docs, processed_chunks, threshold}
-- ediscovery_params:   사용자 지정 파라미터 (chunk_size, threshold, page_range)

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ediscovery_status VARCHAR(20) NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ediscovery_job_id VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ediscovery_graphs JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ediscovery_metrics JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ediscovery_params JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ediscovery_refundable BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ediscovery_reserved_pages INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS ediscovery_reserved_period_start TIMESTAMPTZ;

-- 처리 중/오류 상태 작업 조회용 인덱스
CREATE INDEX IF NOT EXISTS ix_jobs_ediscovery_status
    ON jobs (ediscovery_status)
    WHERE ediscovery_status <> '';
