// [Flow: Step 1 (실제 진행률 계산) -> Step 2 (UI가 처음 본 시점 또는 created_at) -> Step 3 (시간 기반 추정 진행률 계산, 2배 느림) -> Step 4 (20% cap 및 실제값 우선으로 합산)]
// PDF OCR 작업의 시간진행바(estimated progress) 계산 유틸리티.

const DEFAULT_TIME_CAP = 20;
const TIME_PROGRESS_SLOWDOWN = 2; // 전체 페이지 수 * 2 초에 100%에 도달하도록 속도 절반

/**
 * ISO 문자열을 UTC 기준 Date로 파싱한다.
 * 서버에서 timezone 마커 없이 전달된 naive datetime을 UTC로 처리하여, 클라이언트 로컬 타임존과 무관하게 경과 시간을 계산한다.
 * @param {string} dateStr - ISO 문자열
 * @returns {Date} UTC 기준 Date
 */
function parseUtcDate(dateStr) {
  if (!dateStr) return new Date(0);
  const s = String(dateStr).trim();
  // 이미 Z 또는 +HH:MM/-HH:MM 형식이면 그대로 파싱
  if (s.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(s)) {
    return new Date(s);
  }
  // timezone 마커가 없으면 UTC로 해석
  return new Date(`${s}Z`);
}

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
 * UI가 처음 본 시점(startTime)을 기준으로 경과 시간을 계산한다. startTime이 없으면 created_at을 폴백으로 사용한다.
 * 전체 페이지 수의 2배 시간(초)에 100%에 도달하며, maxTimePct(기본 20%)까지만 올라간다.
 * @param {object} job - API에서 받은 job 객체
 * @param {number} maxTimePct - 시간진행바 최대치 (기본 20)
 * @param {number} now - 기준 시간戳 (ms), 기본값 Date.now()
 * @param {number | null} startTime - UI가 처음 본 시점 (ms), 기본값 null
 * @returns {number} 0~maxTimePct 사이 정수
 */
export function getTimeProgress(job, maxTimePct = DEFAULT_TIME_CAP, now = Date.now(), startTime = null) {
  if (!job) return 0;
  const total = job.total_pages || job.total_files || 1;
  const start = startTime || (job.created_at ? parseUtcDate(job.created_at).getTime() : now);
  const elapsedSeconds = (now - start) / 1000;
  const pct = Math.round((elapsedSeconds / (total * TIME_PROGRESS_SLOWDOWN)) * 100);
  return Math.min(maxTimePct, Math.min(100, pct));
}

/**
 * 화면에 표시할 진행률을 계산한다.
 * 실제 진행률과 시간추정 진행률 중 더 높은 값을 사용한다. 시간추정값은 20%로 cap되므로, 20%를 넘어가는 구간은 자연스럽게 실제 진행률만 표시된다.
 * @param {object} job - API에서 받은 job 객체
 * @param {number} maxTimePct - 시간진행바 최대치 (기본 20)
 * @param {number} now - 기준 시간戳 (ms), 기본값 Date.now()
 * @param {number | null} startTime - UI가 처음 본 시점 (ms), 기본값 null
 * @returns {number} 0~100 사이 정수
 */
export function getDisplayProgress(job, maxTimePct = DEFAULT_TIME_CAP, now = Date.now(), startTime = null) {
  const actual = getActualProgress(job);
  const time = getTimeProgress(job, maxTimePct, now, startTime);
  return Math.max(actual, time);
}
