// [Flow: Step 1 (FastAPI base URL 및 인증 헤더 설정) -> Step 2 (fetch 래퍼)
//       -> Step 3 (Job/주석/마크다운/엑셀 API 메서드 제공)]
// Python FastAPI에 요청을 보내는 클라이언트. Node.js AI 백엔드는 ai SDK 도구 실행을 위해
// 기존 데이터와 Storage 경로를 FastAPI에서 조회하고, 최종 결과를 FastAPI에 저장한다.
import type { AuthHeaders } from './auth.js';

const PROOF_API_URL = process.env.PROOF_API_URL || 'http://localhost:8000';

// [Flow: Step 1 (연결 실패 시 재시도 설정) -> Step 2 (재시도 가능한 오류 판별)
//       -> Step 3 (지수 백오프 후 재시도) -> Step 4 (최종 실패 시 throw)]
// FastAPI와의 일시적 네트워크 단절(컨테이너 재시작, DNS 지연 등)을 회복하기 위한 설정.
const MAX_RETRIES = 3;
const RETRY_BASE_DELAY_MS = 500;
const RETRYABLE_ERROR_CODES = new Set([
  'ECONNREFUSED',
  'ECONNRESET',
  'ETIMEDOUT',
  'ENOTFOUND',
  'EAI_AGAIN',
  'ECONNABORTED',
]);

/**
 * [Flow: Step 1 (Error 객체 여부 확인) -> Step 2 (cause 코드 또는 메시지로 재시도 대상 판별)
 *       -> Step 3 (boolean 반환)]
 *
 * Node.js fetch의 connection-level 오류(예: "fetch failed", ECONNREFUSED)를 재시도 대상으로 판별한다.
 *
 * @param err catch한 오류 객체
 * @returns 재시도 가능 여부
 */
function isRetryableError(err: unknown): boolean {
  if (!(err instanceof Error)) return false;
  const cause = (err as any).cause;
  if (cause && cause.code && RETRYABLE_ERROR_CODES.has(cause.code)) return true;
  const msg = err.message.toLowerCase();
  return (
    msg.includes('fetch failed') ||
    msg.includes('socket hang up') ||
    msg.includes('network error') ||
    msg.includes('disconnect')
  );
}

/**
 * [Flow: Step 1 (지연 시간 수신) -> Step 2 (Promise로 setTimeout 감싸기) -> Step 3 (반환)]
 *
 * @param ms 대기 시간(밀리초)
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * [Flow: Step 1 (path, method, body, authHeaders 수신) -> Step 2 (fetch 요청)
 *       -> Step 3 (연결 실패 시 지수 백오프 재시도) -> Step 4 (JSON 파싱 및 에러 throw) -> Step 5 (데이터 반환)]
 *
 * @param path FastAPI 엔드포인트 경로 (예: /api/jobs/123)
 * @param method HTTP 메서드
 * @param body 요청 본문
 * @param authHeaders 인증 헤더
 * @returns 응답 JSON
 */
export async function request<T>(
  path: string,
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' = 'GET',
  body?: unknown,
  authHeaders?: AuthHeaders,
): Promise<T> {
  const url = `${PROOF_API_URL}${path}`;
  const headers: Record<string, string> = {
    ...(authHeaders || {}),
  };
  const options: RequestInit = {
    method,
    headers,
  };
  if (body !== undefined && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  } else if (body instanceof FormData) {
    options.body = body;
  }

  // POST/PUT/PATCH는 중복 생성 위험이 있으므로 connection-level 실패라도 재시도하지 않는다.
  const isRetryableMethod = method === 'GET' || method === 'DELETE';
  let lastError: unknown;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const res = await fetch(url, options);
      const isJson = (res.headers.get('content-type') || '').includes('application/json');
      const data = isJson ? await res.json() : await res.text();
      if (!res.ok) {
        const body = data as any;
        const detail = isJson ? (body.detail || JSON.stringify(body)) : body;
        throw new Error(`Proof API error ${res.status}: ${detail}`);
      }
      return data as T;
    } catch (err) {
      lastError = err;
      const msg = err instanceof Error ? err.message : String(err);
      const cause = err instanceof Error ? (err as any).cause : undefined;
      const causeCode = cause?.code;
      const causeMessage = cause instanceof Error ? cause.message : undefined;

      console.error(
        `[request] ${method} ${url} attempt=${attempt + 1}/${MAX_RETRIES + 1} failed: ${msg}`,
        { baseUrl: PROOF_API_URL, causeCode, causeMessage, headers: Object.keys(headers) },
      );

      const canRetry = isRetryableMethod && attempt < MAX_RETRIES && isRetryableError(err);
      if (!canRetry) break;

      const delay = Math.min(RETRY_BASE_DELAY_MS * 2 ** attempt, 4000);
      console.log(`[request] retrying ${method} ${url} in ${delay}ms...`);
      await sleep(delay);
    }
  }

  throw lastError;
}

/**
 * [Flow: Step 1 (job_id 수신) -> Step 2 (/api/jobs/{id} 조회) -> Step 3 (Job JSON 반환)]
 *
 * @param jobId Job ID
 * @param authHeaders 인증 헤더
 */
export async function getJob(jobId: string, authHeaders?: AuthHeaders): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/jobs/${jobId}`, 'GET', undefined, authHeaders);
}

/**
 * [Flow: Step 1 (job_id, query, page_no 수신) -> Step 2 (/api/jobs/{id}/search-text 조회)
 *       -> Step 3 (검색 결과 요소 목록 반환)]
 *
 * FastAPI에 새로 추가될 전용 검색 엔드포인트를 사용한다. 엔드포인트가 없으면
 * getElements로 전체 요소를 받아 Node.js 측에서 필터링한다.
 *
 * @param jobId Job ID
 * @param query 검색어/정규식
 * @param pageNo 1-based 페이지 번호 (optional)
 * @param authHeaders 인증 헤더
 */
export async function searchText(
  jobId: string,
  query: string,
  pageNo?: number,
  authHeaders?: AuthHeaders,
): Promise<{
  matches: Array<Record<string, unknown>>;
  pageDimensions: Record<number, { width: number; height: number }>;
}> {
  const params = new URLSearchParams({ query });
  if (pageNo !== undefined) params.set('page_no', String(pageNo));
  try {
    const res = await request<{
      matches: Array<Record<string, unknown>>;
      page_dimensions?: Record<string, { width: number; height: number }>;
    }>(
      `/api/jobs/${jobId}/search-text?${params.toString()}`,
      'GET',
      undefined,
      authHeaders,
    );
    console.log(`[searchText] job=${jobId} query=${query} pageNo=${pageNo} matches=${res.matches?.length ?? 0}`);
    const pageDimensions: Record<number, { width: number; height: number }> = {};
    for (const [k, v] of Object.entries(res.page_dimensions || {})) {
      pageDimensions[Number(k)] = v;
    }
    return { matches: res.matches || [], pageDimensions };
  } catch (err) {
    console.error(`[searchText] job=${jobId} query=${query} pageNo=${pageNo} endpoint failed: ${err instanceof Error ? err.message : String(err)}`);
    // search-text 엔드포인트가 없으면 getElements로 전체 요소를 받아 Node.js 측에서 필터링
    const { elements, pageDimensions } = await getElements(jobId, pageNo, authHeaders);
    const regex = new RegExp(query, 'i');
    const matches = elements.filter((el) => regex.test(String(el.text || '')));
    console.log(`[searchText] fallback job=${jobId} elements=${elements.length} matches=${matches.length}`);
    return { matches, pageDimensions };
  }
}

/**
 * [Flow: Step 1 (job_id, page_no 수신) -> Step 2 (/api/jobs/{id}/elements 조회)
 *       -> Step 3 (요소 목록 + 페이지 크기 반환)]
 *
 * @param jobId Job ID
 * @param pageNo 1-based 페이지 번호 (optional)
 * @param authHeaders 인증 헤더
 */
export async function getElements(
  jobId: string,
  pageNo?: number,
  authHeaders?: AuthHeaders,
): Promise<{
  elements: Array<Record<string, unknown>>;
  pageDimensions: Record<number, { width: number; height: number }>;
}> {
  const res = await request<{
    elements: Array<Record<string, unknown>>;
    page_dimensions?: Record<string, { width: number; height: number }>;
  }>(
    `/api/jobs/${jobId}/elements${pageNo !== undefined ? `?page_no=${pageNo}` : ''}`,
    'GET',
    undefined,
    authHeaders,
  );
  // page_dimensions의 키가 문자열이므로 number 키로 변환
  const pageDimensions: Record<number, { width: number; height: number }> = {};
  for (const [k, v] of Object.entries(res.page_dimensions || {})) {
    pageDimensions[Number(k)] = v;
  }
  return { elements: res.elements || [], pageDimensions };
}

/**
 * [Flow: Step 1 (job_id, source_index, page_no 수신) -> Step 2 (/api/jobs/{id}/annotations 조회)
 *       -> Step 3 (주석 목록 반환)]
 *
 * @param jobId Job ID
 * @param sourceIndex 주석 파일 인덱스 (기본 0)
 * @param pageNo 1-based 페이지 번호 (optional)
 * @param authHeaders 인증 헤더
 */
export async function getAnnotations(
  jobId: string,
  sourceIndex: number = 0,
  pageNo?: number,
  authHeaders?: AuthHeaders,
): Promise<{
  annotations: Array<Record<string, unknown>>;
  total: number;
}> {
  const params = new URLSearchParams({ source_index: String(sourceIndex) });
  if (pageNo !== undefined) params.set('page_no', String(pageNo));
  const res = await request<{
    annotations?: Array<Record<string, unknown>>;
    total?: number;
  }>(`/api/jobs/${jobId}/annotations?${params.toString()}`, 'GET', undefined, authHeaders);
  return { annotations: res.annotations || [], total: res.total ?? 0 };
}

/**
 * [Flow: Step 1 (job_id, page_no, dpi 수신) -> Step 2 (/api/jobs/{id}/page-image 조회)
 *       -> Step 3 (이미지 URL 및 메타데이터 반환)]
 *
 * @param jobId Job ID
 * @param pageNo 1-based 페이지 번호
 * @param dpi 렌더링 DPI (기본 150)
 * @param authHeaders 인증 헤더
 */
export async function getPageImage(
  jobId: string,
  pageNo: number,
  dpi?: number,
  authHeaders?: AuthHeaders,
): Promise<{
  page_no: number;
  dpi: number;
  width: number;
  height: number;
  image_url: string;
}> {
  const params = new URLSearchParams({ page_no: String(pageNo) });
  if (dpi !== undefined) params.set('dpi', String(dpi));
  return request<{
    page_no: number;
    dpi: number;
    width: number;
    height: number;
    image_url: string;
  }>(`/api/jobs/${jobId}/page-image?${params.toString()}`, 'GET', undefined, authHeaders);
}

/**
 * [Flow: Step 1 (job_id, annotation_id, source_index, payload 수신)
 *       -> Step 2 (/api/jobs/{id}/annotations/{annotation_id} 수정) -> Step 3 (수정 결과 반환)]
 *
 * @param jobId Job ID
 * @param annotationId 주석 ID
 * @param sourceIndex 주석 파일 인덱스 (기본 0)
 * @param payload 수정할 필드 (color, comment, opacity)
 * @param authHeaders 인증 헤더
 */
export async function updateAnnotation(
  jobId: string,
  annotationId: string,
  sourceIndex: number = 0,
  payload: { color?: string; comment?: string; opacity?: number } = {},
  authHeaders?: AuthHeaders,
): Promise<{ ok: boolean; annotation_id?: string; updated_fields?: string[] }> {
  const params = new URLSearchParams({ source_index: String(sourceIndex) });
  return request<{ ok: boolean; annotation_id?: string; updated_fields?: string[] }>(
    `/api/jobs/${jobId}/annotations/${encodeURIComponent(annotationId)}?${params.toString()}`,
    'PATCH',
    payload,
    authHeaders,
  );
}

/**
 * [Flow: Step 1 (job_id, source_index, annotations 수신) -> Step 2 (/api/jobs/{id}/user-annotations 저장)
 *       -> Step 3 (저장 결과 반환)]
 *
 * @param jobId Job ID
 * @param sourceIndex source_files 인덱스
 * @param annotations EmbedPDF AnnotationTransferItem[]
 * @param authHeaders 인증 헤더
 */
export async function saveAnnotations(
  jobId: string,
  sourceIndex: number,
  annotations: Array<Record<string, unknown>>,
  authHeaders?: AuthHeaders,
): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(
    `/api/jobs/${jobId}/user-annotations`,
    'POST',
    { source_index: sourceIndex, annotations },
    authHeaders,
  );
}

/**
 * [Flow: Step 1 (job_id, kind, source_index, page_no 수신) -> Step 2 (/api/jobs/{id}/result-json 조회)
 *       -> Step 3 (결과 JSON 반환)]
 *
 * AI 에이전트의 read_job_json 도구가 호출하는 범용 결과 JSON 리더.
 * kind: annotations | ocr_layout | extracted_files | annotated_pdf_files | job_meta
 *
 * @param jobId Job ID
 * @param kind 읽을 결과 JSON 종류
 * @param sourceIndex 주석 파일 인덱스 (kind=annotations일 때만)
 * @param pageNo 1-based 페이지 번호 (kind=annotations일 때만 필터링)
 * @param authHeaders 인증 헤더
 * @returns { kind, data, total? }
 */
export async function getResultJson(
  jobId: string,
  kind: string,
  sourceIndex: number = 0,
  pageNo?: number,
  authHeaders?: AuthHeaders,
): Promise<{ kind: string; data: unknown; total?: number }> {
  const params = new URLSearchParams({ kind });
  if (sourceIndex !== undefined) params.set('source_index', String(sourceIndex));
  if (pageNo !== undefined) params.set('page_no', String(pageNo));
  return request<{ kind: string; data: unknown; total?: number }>(
    `/api/jobs/${jobId}/result-json?${params.toString()}`,
    'GET',
    undefined,
    authHeaders,
  );
}

/**
 * [Flow: Step 1 (job_id 수신) -> Step 2 (/api/jobs/{id}/preview 조회) -> Step 3 (마크다운 반환)]
 *
 * @param jobId Job ID
 * @param authHeaders 인증 헤더
 * @returns 마크다운 문자열
 */
export async function getMarkdown(jobId: string, authHeaders?: AuthHeaders): Promise<string> {
  const res = await request<{ markdown?: string }>(
    `/api/jobs/${jobId}/preview`,
    'GET',
    undefined,
    authHeaders,
  );
  return res.markdown || '';
}

/**
 * [Flow: Step 1 (job_id, page_num, markdown 수신) -> Step 2 (페이지/전체 마크다운 저장)
 *       -> Step 3 (저장 결과 반환)]
 *
 * @param jobId Job ID
 * @param pageNum 1-based 페이지 번호 (undefined면 전체 마크다운)
 * @param markdown 저장할 마크다운
 * @param authHeaders 인증 헤더
 */
export async function saveMarkdown(
  jobId: string,
  pageNum: number | undefined,
  markdown: string,
  authHeaders?: AuthHeaders,
): Promise<Record<string, unknown>> {
  if (pageNum !== undefined) {
    return request<Record<string, unknown>>(
      `/api/jobs/${jobId}/result/pages/${pageNum}`,
      'PATCH',
      { markdown },
      authHeaders,
    );
  }
  return request<Record<string, unknown>>(
    `/api/jobs/${jobId}/result`,
    'PUT',
    { markdown },
    authHeaders,
  );
}

/**
 * [Flow: Step 1 (job_id, xlsx blob 수신) -> Step 2 (/api/jobs/{id}/save-edited-xlsx 저장)
 *       -> Step 3 (저장 결과 반환)]
 *
 * @param jobId Job ID
 * @param blob XLSX Blob
 * @param filename 파일명
 * @param authHeaders 인증 헤더
 */
export async function saveXlsx(
  jobId: string,
  blob: Blob,
  filename: string,
  authHeaders?: AuthHeaders,
): Promise<Record<string, unknown>> {
  const formData = new FormData();
  formData.append('file', blob, filename);
  return request<Record<string, unknown>>(
    `/api/jobs/${jobId}/save-edited-xlsx`,
    'POST',
    formData,
    authHeaders,
  );
}

// ========================================
// Sandbox API 메서드
// ========================================

/**
 * [Flow: Step 1 (job_id, resource_limits 수신) -> Step 2 (POST /api/sandboxes) -> Step 3 (sandbox 정보 반환)]
 *
 * @param jobId Job ID
 * @param resourceLimits 리소스 제한 (cpu, memory_mb)
 * @param denseMode 고밀도 모드 여부
 * @param authHeaders 인증 헤더
 * @returns sandbox 정보 (sandbox_id, status, workspace)
 */
export async function createSandbox(
  jobId: string,
  resourceLimits?: { cpu?: number; memory_mb?: number },
  denseMode?: boolean,
  authHeaders?: AuthHeaders,
): Promise<{
  sandbox_id: string;
  status: string;
  workspace: string;
  error?: string;
}> {
  const body: Record<string, unknown> = { job_id: jobId, dense_mode: denseMode || false };
  if (resourceLimits) body.resource_limits = resourceLimits;
  return request('/api/sandboxes', 'POST', body, authHeaders);
}

/**
 * [Flow: Step 1 (sandbox_id, command 수신) -> Step 2 (POST /api/sandboxes/{id}/execute) -> Step 3 (실행 결과 반환)]
 *
 * @param sandboxId sandbox ID
 * @param command 셸 명령어
 * @param timeout 타임아웃 (초)
 * @param authHeaders 인증 헤더
 * @returns 실행 결과 (exit_code, stdout, stderr)
 */
export async function executeInSandbox(
  sandboxId: string,
  command: string,
  timeout?: number,
  authHeaders?: AuthHeaders,
): Promise<{
  exit_code: number;
  stdout: string;
  stderr: string;
  error?: string;
}> {
  const body: Record<string, unknown> = { command };
  if (timeout) body.timeout = timeout;
  return request(`/api/sandboxes/${sandboxId}/execute`, 'POST', body, authHeaders);
}

/**
 * [Flow: Step 1 (sandbox_id 수신) -> Step 2 (GET /api/sandboxes/{id}) -> Step 3 (상태 반환)]
 *
 * @param sandboxId sandbox ID
 * @param authHeaders 인증 헤더
 * @returns sandbox 상태
 */
export async function getSandboxStatus(
  sandboxId: string,
  authHeaders?: AuthHeaders,
): Promise<Record<string, unknown>> {
  return request(`/api/sandboxes/${sandboxId}`, 'GET', undefined, authHeaders);
}

/**
 * [Flow: Step 1 (sandbox_id, path 수신) -> Step 2 (GET /api/sandboxes/{id}/files) -> Step 3 (파일 목록 반환)]
 *
 * @param sandboxId sandbox ID
 * @param path 조회할 경로
 * @param authHeaders 인증 헤더
 * @returns 파일 목록
 */
export async function listSandboxFiles(
  sandboxId: string,
  path: string,
  authHeaders?: AuthHeaders,
): Promise<{ files: Array<{ name: string; size: number; type: string }>; error?: string }> {
  const params = new URLSearchParams({ path });
  return request(`/api/sandboxes/${sandboxId}/files?${params}`, 'GET', undefined, authHeaders);
}

/**
 * [Flow: Step 1 (sandbox_id, path 수신) -> Step 2 (GET /api/sandboxes/{id}/files/read) -> Step 3 (파일 내용 반환)]
 *
 * @param sandboxId sandbox ID
 * @param path 파일 경로
 * @param authHeaders 인증 헤더
 * @returns 파일 내용
 */
export async function readSandboxFile(
  sandboxId: string,
  path: string,
  authHeaders?: AuthHeaders,
): Promise<{ content: string; size: number; error?: string }> {
  const params = new URLSearchParams({ path });
  return request(`/api/sandboxes/${sandboxId}/files/read?${params}`, 'GET', undefined, authHeaders);
}

/**
 * [Flow: Step 1 (sandbox_id, path, content 수신) -> Step 2 (POST /api/sandboxes/{id}/files/write) -> Step 3 (쓰기 결과 반환)]
 *
 * @param sandboxId sandbox ID
 * @param path 파일 경로
 * @param content 파일 내용
 * @param authHeaders 인증 헤더
 * @returns 쓰기 결과
 */
export async function writeSandboxFile(
  sandboxId: string,
  path: string,
  content: string,
  authHeaders?: AuthHeaders,
): Promise<{ status: string; path: string; error?: string }> {
  return request(`/api/sandboxes/${sandboxId}/files/write`, 'POST', { path, content }, authHeaders);
}

/**
 * [Flow: Step 1 (sandbox_id, message 수신) -> Step 2 (POST /api/sandboxes/{id}/commit) -> Step 3 (commit 결과 반환)]
 *
 * @param sandboxId sandbox ID
 * @param message commit 메시지
 * @param authHeaders 인증 헤더
 * @returns commit 결과
 */
export async function commitSandboxChanges(
  sandboxId: string,
  message: string,
  authHeaders?: AuthHeaders,
): Promise<{ status: string; commit: string; error?: string }> {
  return request(`/api/sandboxes/${sandboxId}/commit`, 'POST', { message }, authHeaders);
}

/**
 * [Flow: Step 1 (sandbox_id 수신) -> Step 2 (GET /api/sandboxes/{id}/diff) -> Step 3 (diff 반환)]
 *
 * @param sandboxId sandbox ID
 * @param cached staged 변경사항만 여부
 * @param authHeaders 인증 헤더
 * @returns git diff
 */
export async function getSandboxDiff(
  sandboxId: string,
  cached: boolean,
  authHeaders?: AuthHeaders,
): Promise<{ diff: string; error?: string }> {
  const params = new URLSearchParams({ cached: String(cached) });
  return request(`/api/sandboxes/${sandboxId}/diff?${params}`, 'GET', undefined, authHeaders);
}

/**
 * [Flow: Step 1 (sandbox_id 수신) -> Step 2 (POST /api/sandboxes/{id}/collect) -> Step 3 (수집 결과 반환)]
 *
 * @param sandboxId sandbox ID
 * @param authHeaders 인증 헤더
 * @returns 수집 결과
 */
export async function collectSandboxResults(
  sandboxId: string,
  authHeaders?: AuthHeaders,
): Promise<{
  uploaded: number;
  failed: number;
  total_scanned: number;
  files: Array<{ path: string; storage_path: string; size: number }>;
  error?: string;
}> {
  return request(`/api/sandboxes/${sandboxId}/collect`, 'POST', undefined, authHeaders);
}

/**
 * [Flow: Step 1 (sandbox_id 수신) -> Step 2 (DELETE /api/sandboxes/{id}) -> Step 3 (종료 결과 반환)]
 *
 * @param sandboxId sandbox ID
 * @param authHeaders 인증 헤더
 * @returns 종료 결과
 */
export async function destroySandbox(
  sandboxId: string,
  authHeaders?: AuthHeaders,
): Promise<{ status: string; container: string; error?: string }> {
  return request(`/api/sandboxes/${sandboxId}`, 'DELETE', undefined, authHeaders);
}

/* ============================================================
 * Flow Drawings API — React Flow 캔버스 드로잉/주석/노트/엣지 CRUD
 * ========================================================== */

/**
 * [Flow: Step 1 (job_id 수신) -> Step 2 (GET /api/jobs/{id}/flow-drawings) -> Step 3 (드로잉 데이터 반환)]
 *
 * 사용자의 Flow Panel 드로잉/주석/노트/엣지를 조회한다.
 *
 * @param jobId Job ID
 * @param authHeaders 인증 헤더
 * @returns 드로잉 데이터 (paths, text_annotations, note_nodes, custom_edges) 또는 null
 */
export async function getFlowDrawings(
  jobId: string,
  authHeaders?: AuthHeaders,
): Promise<{
  paths: Array<Record<string, unknown>>;
  text_annotations: Array<Record<string, unknown>>;
  note_nodes: Array<Record<string, unknown>>;
  custom_edges: Array<Record<string, unknown>>;
} | null> {
  return request(`/api/jobs/${jobId}/flow-drawings`, 'GET', undefined, authHeaders);
}

/**
 * [Flow: Step 1 (job_id + 데이터 수신) -> Step 2 (PUT /api/jobs/{id}/flow-drawings) -> Step 3 (저장 결과 반환)]
 *
 * 사용자의 Flow Panel 드로잉/주석/노트/엣지를 upsert 한다 (전체 교체).
 *
 * @param jobId Job ID
 * @param data 저장할 드로잉 데이터 (paths, text_annotations, note_nodes, custom_edges)
 * @param authHeaders 인증 헤더
 * @returns 저장 결과
 */
export async function saveFlowDrawings(
  jobId: string,
  data: {
    paths?: Array<Record<string, unknown>>;
    text_annotations?: Array<Record<string, unknown>>;
    note_nodes?: Array<Record<string, unknown>>;
    custom_edges?: Array<Record<string, unknown>>;
  },
  authHeaders?: AuthHeaders,
): Promise<{ status: string; paths: unknown[]; text_annotations: unknown[]; note_nodes: unknown[]; custom_edges: unknown[] }> {
  return request(`/api/jobs/${jobId}/flow-drawings`, 'PUT', data, authHeaders);
}

/**
 * [Flow: Step 1 (job_id 수신) -> Step 2 (DELETE /api/jobs/{id}/flow-drawings) -> Step 3 (삭제 결과 반환)]
 *
 * 사용자의 Flow Panel 드로잉/주석/노트/엣지 전체를 삭제한다.
 *
 * @param jobId Job ID
 * @param authHeaders 인증 헤더
 * @returns 삭제 결과
 */
export async function deleteFlowDrawings(
  jobId: string,
  authHeaders?: AuthHeaders,
): Promise<{ status: string }> {
  return request(`/api/jobs/${jobId}/flow-drawings`, 'DELETE', undefined, authHeaders);
}
