-- 문서 파싱 최종 실패 시 사용자 재시도/환불 가능 여부 컬럼 추가
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS refundable BOOLEAN NOT NULL DEFAULT FALSE;

-- 기존 error 상태 작업은 자동 재시도/환불 기능 도입 이전에 발생한 것으로 보고 환불 불가로 설정
UPDATE jobs SET refundable = FALSE WHERE refundable IS NULL;
