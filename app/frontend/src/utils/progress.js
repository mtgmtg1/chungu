// [Flow: Step 1 (실제 진행률 계산) -> Step 2 (시간 기반 추정 진행률 계산) -> Step 3 (84% cap 및 실제값 우선으로 합산)]
// PDF OCR 작업의 시간진행바(estimated progress) 계산 유틸리티.

const DEFAULT_TIME_CAP = 84;

/**
 * 실제 done/total 기반 진행률을 계산한다.
 * @param {object} job - API에서 받은 job 객체
 * @returns {number} 0~100 사이 정수
 */
export function getActualProgress(job) {
  if (!job) return 0;
  const total = job.total_pages || job.total_files || 1;
  const done = job.done_pages || job.done_files || 0;
  return Math.min(100, Math.round((done / total) * 100));
}

/**
 * 시간 경과 기반 추정 진행률을 계산한다.
 * job.created_at를 기준으로 초당 100/total_pages %씩 상승하며, maxTimePct까지만 올라간다.
 * @param {object} job - API에서 받은 job 객체
 * @param {number} maxTimePct - 시간진행바 최대치 (기본 84)
 * @param {number} now - 기준 시간戳 (ms), 기본값 Date.now()
 * @returns {number} 0~maxTimePct 사이 정수
 */
export function getTimeProgress(job, maxTimePct = DEFAULT_TIME_CAP, now = Date.now()) {
  if (!job || !job.created_at) return 0;
  const total = job.total_pages || job.total_files || 1;
  const elapsedSeconds = (now - new Date(job.created_at).getTime()) / 1000;
  const pct = Math.round((elapsedSeconds / total) * 100);
  return Math.min(maxTimePct, Math.min(100, pct));
}

/**
 * 화면에 표시할 진행률을 계산한다.
 * 실제 진행률이 maxTimePct(84%) 이상이면 실제값을, 그 전까지는 실제값과 시간추정값 중 큰 값을 사용한다.
 * @param {object} job - API에서 받은 job 객체
 * @param {number} maxTimePct - 시간진행바 최대치 (기본 84)
 * @param {number} now - 기준 시간戳 (ms), 기본값 Date.now()
 * @returns {number} 0~100 사이 정수
 */
export function getDisplayProgress(job, maxTimePct = DEFAULT_TIME_CAP, now = Date.now()) {
  const actual = getActualProgress(job);
  const time = getTimeProgress(job, maxTimePct, now);
  if (actual >= maxTimePct) return actual;
  return Math.max(actual, time);
}
