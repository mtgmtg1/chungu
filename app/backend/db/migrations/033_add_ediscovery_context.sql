-- [Flow: Step 1 (jobs 테이블에 ediscovery_context 컬럼 추가) -> Step 2 (기존 데이터는 빈 문자열로 초기화)]
-- e-Discovery 분석에 사용할 사용자가 입력한 프로젝트 주요/중요 사항 컨텍스트를 저장한다.
-- 첫 업로드 시 입력한 맥락과 분석 버튼 옆에서 수정한 맥락을 모두 지속한다.

ALTER TABLE jobs
  ADD COLUMN IF NOT EXISTS ediscovery_context TEXT NOT NULL DEFAULT '';
