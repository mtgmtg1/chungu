// [Flow: Step 1 (FastAPI base URL 및 인증 헤더 설정) -> Step 2 (fetch 래퍼)
//       -> Step 3 (Job/주석/마크다운/엑셀 API 메서드 제공)]
// Python FastAPI에 요청을 보내는 클라이언트. Node.js AI 백엔드는 ai SDK 도구 실행을 위해
// 기존 데이터와 Storage 경로를 FastAPI에서 조회하고, 최종 결과를 FastAPI에 저장한다.
import type { AuthHeaders } from './auth.js';

const PROOF_API_URL = process.env.PROOF_API_URL || 'http://localhost:8000';

/**
 * [Flow: Step 1 (path, method, body, authHeaders 수신) -> Step 2 (fetch 요청)
 *       -> Step 3 (JSON 파싱 및 에러 throw) -> Step 4 (데이터 반환)]
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

  const res = await fetch(url, options);
  const isJson = (res.headers.get('content-type') || '').includes('application/json');
  const data = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const body = data as any;
    const detail = isJson ? (body.detail || JSON.stringify(body)) : body;
    throw new Error(`Proof API error ${res.status}: ${detail}`);
  }
  return data as T;
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
  try {
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
  } catch {
    return { elements: [], pageDimensions: {} };
  }
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
