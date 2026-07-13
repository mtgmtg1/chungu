-- [Flow: Step 1 (issue_tree 컬럼 추가) -> Step 2 (인덱스 생성) -> Step 3 (빈 객체 기본값 설정)]
-- 쟁점(Issue) → 주장(Claim) → 근거(Evidence) 3단계 트리를 저장할 JSONB 컬럼을 추가한다.
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS issue_tree JSONB NOT NULL DEFAULT '{}'::jsonb;
