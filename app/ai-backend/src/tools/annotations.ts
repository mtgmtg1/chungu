// [Flow: Step 1 (context에서 job_id, source_index, authHeaders 추출) -> Step 2 (임시 주석 상태 관리)
//       -> Step 3 (PDF 검색/요소/하이라이트/콜아웃/삭제/비교/저장 도구 생성) -> Step 4 (도구 객체 반환)]
// PDF 주석 조작용 서버 사이드 도구. FastAPI에서 텍스트 레이어/요소를 조회하고,
// 생성된 주석을 임시 상태에 쌓은 뒤 apply_annotations에서 Storage에 저장한다.
import { generateText, tool } from 'ai';
import { z } from 'zod';
import type { AuthHeaders } from '../lib/auth.js';
import { buildModel } from '../lib/model.js';
import * as proofApi from '../lib/proof-api.js';

// 색상 이름 -> RGB[0-1] 매핑. Python pdf_annotator.py의 HIGHLIGHT_COLOR_PALETTE와 동기화해야 한다.
const COLOR_PALETTE: Record<string, [number, number, number]> = {
  red: [1.0, 0.25, 0.25],
  yellow: [1.0, 0.92, 0.3],
  green: [0.25, 0.85, 0.35],
  blue: [0.25, 0.55, 1.0],
  orange: [1.0, 0.6, 0.15],
  purple: [0.65, 0.35, 0.95],
  pink: [1.0, 0.55, 0.75],
  gray: [0.7, 0.7, 0.7],
};

const DEFAULT_HIGHLIGHT_COLOR: [number, number, number] = [1.0, 0.92, 0.3];
const DEFAULT_CALLOUT_COLOR: [number, number, number] = [0.65, 0.35, 0.95];
const DEFAULT_OPACITY = 0.5;

/**
 * [Flow: Step 1 (RGB[0-1] 값을 0-255로 변환) -> Step 2 (16진수 문자열로 변환) -> Step 3 (hex 조합)]
 *
 * FastAPI의 주석 API는 색상을 hex 문자열(예: #FFEE4D)로 저장하므로,
 * AI 백엔드의 RGB[0-1] 팔레트를 hex로 변환한다.
 *
 * @param rgb RGB[0-1] 튜플
 * @returns hex 색상 문자열
 */
function rgbToHex(rgb: [number, number, number]): string {
  return (
    '#' +
    rgb
      .map((c) => Math.round(Math.max(0, Math.min(1, c)) * 255).toString(16).padStart(2, '0'))
      .join('')
  );
}

interface AnnotationContext {
  jobId?: string;
  job_id?: string;
  sourceIndex?: number;
  source_index?: number;
  authHeaders?: AuthHeaders;
  [key: string]: unknown;
}

interface AnnotationTarget {
  page_no: number;
  bbox_pdf: [number, number, number, number];
  comment: string;
  color: [number, number, number];
  callout_color?: [number, number, number];
  opacity: number;
}

interface PendingAnnotation {
  id: string;
  target: AnnotationTarget;
  type: 'highlight' | 'callout';
}

interface CachedElements {
  elements: Array<Record<string, unknown>>;
  pageDimensions: Record<number, { width: number; height: number }>;
}

/**
 * [Flow: Step 1 (context에서 job_id, source_index, authHeaders 추출) -> Step 2 (pending 상태 초기화)
 *       -> Step 3 (도구 정의) -> Step 4 (도구 객체 반환)]
 *
 * @param context 에이전트 컨텍스트
 * @returns PDF 주석 조작 도구 맵
 */
export function buildAnnotationTools(context: AnnotationContext) {
  const jobId = String(context.jobId || context.job_id || '');
  const parsedSourceIndex = Number(context.sourceIndex ?? context.source_index ?? 0);
  const sourceIndex = Number.isInteger(parsedSourceIndex) ? parsedSourceIndex : 0;
  const authHeaders = context.authHeaders || {};

  // [Flow: Step 1 (현재 요청에서 추가/삭제될 주석을 임시 저장) -> Step 2 (apply_annotations에서 일괄 저장)]
  const pending: PendingAnnotation[] = [];
  const removals: string[] = [];
  // 요소/페이지 크기 캐시 — 동일 에이전트 실행 내에서 재사용 (키: page_no 또는 'all')
  const pageCache = new Map<number | 'all', CachedElements>();

  /**
   * [Flow: Step 1 (page_no에 해당하는 캐시 확인) -> Step 2 (FastAPI에서 해당 페이지 요소 조회)
   *       -> Step 3 (캐시에 저장) -> Step 4 (반환)]
   *
   * page_no가 생략되면 전체 페이지를 조회하며, 이미지 기반 PDF 전체를 OCR 하기 때문에 느릴 수 있다.
   */
  async function loadElements(pageNo?: number): Promise<CachedElements> {
    const key = pageNo ?? 'all';
    if (pageCache.has(key)) return pageCache.get(key)!;
    const { elements, pageDimensions } = await proofApi.getElements(jobId, pageNo, authHeaders);
    const cache: CachedElements = { elements, pageDimensions };
    pageCache.set(key, cache);
    return cache;
  }

  /**
   * [Flow: Step 1 (page_no 캐시 확인) -> Step 2 (필요 시 loadElements 호출)
   *       -> Step 3 (해당 페이지 크기 반환)]
   */
  async function loadPageDimensions(pageNo: number): Promise<{ width: number; height: number }> {
    const cache = await loadElements(pageNo);
    return cache.pageDimensions[pageNo] || { width: 612, height: 792 };
  }

  return {
    search_text: tool({
      description: 'PDF 텍스트 레이어에서 키워드나 정규식으로 텍스트를 검색한다.',
      inputSchema: z.object({
        query: z.string().describe('검색어 또는 정규식'),
        page_no: z.number().optional().describe('1-based 페이지 번호. 생략 시 모든 페이지 검색'),
      }),
      execute: async ({ query, page_no }) => {
        const { matches } = await proofApi.searchText(jobId, query, page_no, authHeaders);
        return { matches: matches.slice(0, 20) };
      },
    }),

    get_elements: tool({
      description: 'OCR 또는 텍스트 레이어에서 추출한 페이지 요소 목록을 반환한다. 큰 PDF나 이미지 기반 PDF에서는 page_no를 지정하지 않으면 전체 페이지를 OCR 해야 하므로 매우 느릴 수 있다. 특정 페이지의 요소만 필요할 때는 반드시 page_no를 명시한다.',
      inputSchema: z.object({
        page_no: z.number().optional().describe('1-based 페이지 번호. 생략 시 모든 페이지를 OCR(느림)'),
      }),
      execute: async ({ page_no }) => {
        const { elements } = await loadElements(page_no);
        // [Flow: 출력 크기 제한 — 50→20개로 축소하여 토큰 소비 절약]
        return { elements: elements.slice(0, 20), total: elements.length };
      },
    }),

    read_job_json: tool({
      description: 'job의 다양한 결과 JSON을 읽는 범용 리더. kind로 읽을 데이터를 지정:\n' +
        '- "annotations": AI/사용자 주석 JSON (EmbedPDF AnnotationTransferItem[] 전체 구조 — id, type, pageIndex, rect, color, contents, calloutLine, strokeColor 등)\n' +
        '- "ocr_layout": OCR 레이아웃 JSON (텍스트 블록/표/이미지 위치 정보)\n' +
        '- "extracted_files": 추출된 파일 목록 (마크다운/이미지/PDF 경로 등)\n' +
        '- "annotated_pdf_files": 주석 PDF 파일 메타데이터 목록\n' +
        '- "job_meta": job 상태 요약 (status, total_pages, file_type, has_pdf 등)\n' +
        '기존 주석의 정확한 위치/구조를 확인하거나 OCR 결과를 분석할 때 사용한다.',
      inputSchema: z.object({
        kind: z.enum(['annotations', 'ocr_layout', 'extracted_files', 'annotated_pdf_files', 'job_meta'])
          .describe('읽을 결과 JSON 종류'),
        page_no: z.number().optional().describe('1-based 페이지 번호. kind=annotations일 때만 필터링에 사용'),
      }),
      execute: async ({ kind, page_no }) => {
        try {
          const result = await proofApi.getResultJson(jobId, kind, sourceIndex, page_no, authHeaders);
          // [Flow: 출력 크기 제한 — 80→30개로 축소하여 토큰 소비 절약]
          const data = result.data;
          if (Array.isArray(data) && data.length > 30) {
            return { kind, total: data.length, data: data.slice(0, 30), truncated: true };
          }
          return { kind, total: result.total ?? (Array.isArray(data) ? data.length : undefined), data };
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error(`[read_job_json] job=${jobId} kind=${kind}: ${msg}`);
          return { error: `read_job_json failed: ${msg}` };
        }
      },
    }),

    get_annotations: tool({
      description: '기존 AI 주석 또는 사용자 주석의 목록을 원본 JSON 구조 전체와 함께 반환한다. 주석의 ID, 종류, 색상, 코멘트, 페이지, 위치(bbox), calloutLine, strokeColor 등 모든 필드를 포함한다. 주석을 편집/삭제하거나 기존 주석과 충돌을 피할 때 사용한다.',
      inputSchema: z.object({
        page_no: z.number().optional().describe('1-based 페이지 번호. 생략 시 모든 페이지'),
        summary_only: z.boolean().optional().describe('true면 요약 필드만 반환 (id/type/page_no/color/comment). 생략 시 원본 JSON 전체 반환'),
      }),
      execute: async ({ page_no, summary_only }) => {
        // [Flow: Step 1 (FastAPI에서 주석 목록 조회) -> Step 2 (404 시 빈 배열로 폴백)
        //       -> Step 3 (summary_only면 요약 필드만 추출) -> Step 4 (결과 반환)]
        // Vercel AI SDK가 tool 에러를 "An error occurred."로 마스킹하므로
        // try/catch로 명확한 결과를 tool output에 포함한다.
        try {
          const { annotations, total } = await proofApi.getAnnotations(jobId, sourceIndex, page_no, authHeaders);
          // [Flow: 출력 크기 제한 — 80→30개로 축소하여 토큰 소비 절약]
          const sliced = annotations.slice(0, 30);
          if (summary_only) {
            return {
              annotations: sliced.map((a) => {
                const inner = (a as any).annotation && typeof (a as any).annotation === 'object'
                  ? (a as any).annotation
                  : a;
                return {
                  id: inner.id,
                  type: inner.type,
                  page_no: (inner.pageIndex ?? 0) + 1,
                  color: inner.color,
                  comment: inner.contents,
                };
              }),
              total,
            };
          }
          // 원본 JSON 전체 구조 반환 — EmbedPDF AnnotationTransferItem[] 형식 그대로
          return { annotations: sliced, total };
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          // 404는 "주석이 아직 없음"을 의미하므로 에러가 아닌 빈 상태로 반환
          if (msg.includes('404')) {
            return { annotations: [], total: 0 };
          }
          console.error(`[get_annotations] job=${jobId} sourceIndex=${sourceIndex} page=${page_no}: ${msg}`);
          return { error: `get_annotations failed: ${msg}`, annotations: [], total: 0 };
        }
      },
    }),

    view_page: tool({
      description: 'PDF의 특정 페이지를 이미지로 렌더링해 VLLM vision 모델이 직접 분석한다. 페이지의 텍스트, 레이아웃, 표, 주요 요소를 요약한 분석 결과를 반환한다. DPI는 페이지 내 raster 이미지의 실제 해상도를 추정해 자동 결정되며, 필요시 150~300 사이로 명시할 수 있다.',
      inputSchema: z.object({
        page_no: z.number().describe('1-based 페이지 번호'),
        dpi: z.number().min(150).max(300).optional().describe('렌더링 DPI (150~300, 생략 시 페이지 내 이미지 해상도에서 자동 추정)'),
      }),
      execute: async ({ page_no, dpi }) => {
        // [Flow: Step 1 (FastAPI에서 페이지 이미지 URL 획득) -> Step 2 (이미지 다운로드)
        //       -> Step 3 (base64 data URL 변환) -> Step 4 (vLLM vision 모델에 분석 요청)
        //       -> Step 5 (분석 텍스트 반환)]
        // Vercel AI SDK가 tool 에러를 "An error occurred."로 마스킹하므로
        // try/catch로 명확한 에러 메시지를 tool output에 포함한다.
        try {
          const { image_url, width, height, dpi: resolvedDpi } = await proofApi.getPageImage(
            jobId,
            page_no,
            dpi,
            authHeaders,
          );

          const imageRes = await fetch(image_url);
          if (!imageRes.ok) {
            return { error: `Failed to download page image: ${imageRes.status}` };
          }
          const imageBuffer = Buffer.from(await imageRes.arrayBuffer());
          const base64 = imageBuffer.toString('base64');
          const dataUrl = `data:image/png;base64,${base64}`;

          const model = buildModel();
          const { text } = await generateText({
            model: model as any,
            messages: [
              {
                role: 'user',
                content: [
                  {
                    type: 'text',
                    text: `Analyze this PDF page (page ${page_no}) and describe its contents, layout, and any notable elements in the same language as the user's request.`,
                  },
                  { type: 'image', image: dataUrl },
                ],
              },
            ],
          });
          return { page_no, dpi: resolvedDpi, width, height, analysis: text };
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error(`[view_page] job=${jobId} page=${page_no}: ${msg}`);
          return { error: `view_page failed: ${msg}` };
        }
      },
    }),

    update_annotation: tool({
      description: '기존 주석의 색상, 코멘트, 투명도를 변경한다. get_annotations로 얻은 id를 사용한다.',
      inputSchema: z.object({
        annotation_id: z.string().describe('get_annotations 결과의 id'),
        color: z.enum(['red', 'yellow', 'green', 'blue', 'orange', 'purple', 'pink', 'gray'])
          .optional()
          .describe('변경할 색상 이름'),
        comment: z.string().optional().describe('변경할 코멘트'),
        opacity: z.number().min(0).max(1).optional().describe('변경할 투명도 (0.0~1.0)'),
      }),
      execute: async ({ annotation_id, color, comment, opacity }) => {
        const payload: { color?: string; comment?: string; opacity?: number } = {};
        if (color) payload.color = rgbToHex(COLOR_PALETTE[color] || DEFAULT_HIGHLIGHT_COLOR);
        if (comment !== undefined) payload.comment = comment;
        if (opacity !== undefined) payload.opacity = opacity;
        return proofApi.updateAnnotation(jobId, annotation_id, sourceIndex, payload, authHeaders);
      },
    }),

    add_highlight: tool({
      description: '선택한 요소에 하이라이트 주석을 추가한다. get_elements(page_no)를 먼저 호출했다면 동일한 page_no를 전달하면 해당 페이지만 빠르게 조회한다. page_no를 생략하면 전체 페이지를 조회하므로 큰 PDF에서는 느릴 수 있다.',
      inputSchema: z.object({
        element_index: z.number().describe('get_elements 결과의 인덱스'),
        page_no: z.number().optional().describe('get_elements를 호출할 때 지정한 1-based 페이지 번호. 생략 시 전체 페이지에서 조회'),
        comment: z.string().describe('주석 코멘트'),
        color: z.enum(['red', 'yellow', 'green', 'blue', 'orange', 'purple', 'pink', 'gray'])
          .default('yellow')
          .describe('색상 이름'),
      }),
      execute: async ({ element_index, page_no, comment, color }) => {
        const { elements } = await loadElements(page_no);
        const element = elements[element_index];
        if (!element) {
          return { error: `element_index ${element_index} not found` };
        }
        const bbox = element.bbox_pdf as [number, number, number, number];
        const pageNo = Number(element.page_no || 1);
        const target: AnnotationTarget = {
          page_no: pageNo,
          bbox_pdf: bbox,
          comment,
          color: COLOR_PALETTE[color] || DEFAULT_HIGHLIGHT_COLOR,
          opacity: DEFAULT_OPACITY,
        };
        const id = `ai-${Date.now()}-${pending.length}`;
        pending.push({ id, target, type: 'highlight' });
        return { ok: true, id, element_index, page_no: pageNo };
      },
    }),

    add_callout: tool({
      description: '선택한 요소에 callout(텍스트 박스 + 화살표) 주석을 추가한다. get_elements(page_no)를 먼저 호출했다면 동일한 page_no를 전달하면 해당 페이지만 빠르게 조회한다.',
      inputSchema: z.object({
        element_index: z.number().describe('get_elements 결과의 인덱스'),
        page_no: z.number().optional().describe('get_elements를 호출할 때 지정한 1-based 페이지 번호. 생략 시 전체 페이지에서 조회'),
        comment: z.string().describe('주석 코멘트'),
        color: z.enum(['red', 'yellow', 'green', 'blue', 'orange', 'purple', 'pink', 'gray'])
          .default('purple')
          .describe('색상 이름'),
      }),
      execute: async ({ element_index, page_no, comment, color }) => {
        const { elements } = await loadElements(page_no);
        const element = elements[element_index];
        if (!element) {
          return { error: `element_index ${element_index} not found` };
        }
        const bbox = element.bbox_pdf as [number, number, number, number];
        const pageNo = Number(element.page_no || 1);
        const target: AnnotationTarget = {
          page_no: pageNo,
          bbox_pdf: bbox,
          comment,
          color: COLOR_PALETTE[color] || DEFAULT_CALLOUT_COLOR,
          opacity: DEFAULT_OPACITY,
        };
        const id = `ai-${Date.now()}-${pending.length}`;
        pending.push({ id, target, type: 'callout' });
        return { ok: true, id, element_index, page_no: pageNo };
      },
    }),

    remove_annotation: tool({
      description: '기존 AI 주석을 제거한다. 삭제 전 사용자 승인이 필요하다.',
      inputSchema: z.object({
        annotation_id: z.string().describe('제거할 주석 ID'),
      }),
      execute: async ({ annotation_id }) => {
        removals.push(annotation_id);
        return { ok: true, removed: annotation_id, requires_approval: true };
      },
    }),

    compare_elements: tool({
      description: '여러 페이지의 요소를 비교 분석한다.',
      inputSchema: z.object({
        description: z.string().describe('비교 기준이나 조건'),
        page_nos: z.array(z.number()).describe('비교할 1-based 페이지 번호 목록'),
      }),
      execute: async ({ description, page_nos }) => {
        const results = [];
        for (const pageNo of page_nos.slice(0, 5)) {
          const { elements } = await loadElements(pageNo);
          const pageElements = elements.filter((el) => Number(el.page_no) === pageNo);
          results.push({
            page_no: pageNo,
            count: pageElements.length,
            elements: pageElements.slice(0, 10),
          });
        }
        return { description, page_nos, results };
      },
    }),

    apply_annotations: tool({
      description: '현재까지 추가한 하이라이트/콜아웃을 Storage에 저장하고 뷰어에 반영한다. 저장 실패 시에도 실제 원인을 결과에 반환한다.',
      inputSchema: z.object({}),
      execute: async () => {
        // [Flow: Step 1 (대기 중인 변경 확인) -> Step 2 (주석 JSON 생성)
        //       -> Step 3 (원래 주석 파일 저장 시도) -> Step 4 (원본 JSON fallback)
        //       -> Step 5 (구조화된 저장 결과 반환)]
        if (pending.length === 0 && removals.length === 0) {
          return { saved: false, reason: '저장할 주석 변경이 없습니다.' };
        }

        if (pending.length === 0) {
          // 현재 remove_annotation은 승인 대기 상태만 기록하고 실제 삭제 API를 호출하지 않는다.
          // 빈 배열을 저장 API에 보내면 백엔드가 400을 반환하므로 명시적인 결과를 반환한다.
          return {
            saved: false,
            removals: removals.length,
            reason: '삭제 요청은 승인 대기 중이며, 추가할 주석이 없어 저장하지 않았습니다.',
          };
        }

        try {
          const pageNos = [...new Set(pending.map((p) => p.target.page_no))];
          const pageDimensions: Record<number, { width: number; height: number }> = {};
          for (const pageNo of pageNos) {
            pageDimensions[pageNo] = await loadPageDimensions(pageNo);
          }
          const annotations = pending.map((pendingAnnotation) =>
            _buildAnnotationItem(pendingAnnotation, pageDimensions),
          );
          let saveSourceIndex = sourceIndex;
          let usedFallback = false;

          // [Flow: Step 1 (source_index로 주석 PDF 저장) -> Step 2 (404/실패 감지)
          //       -> Step 3 (source_index=-1로 원본 PDF의 JSON 저장)]
          try {
            await proofApi.saveAnnotations(jobId, saveSourceIndex, annotations, authHeaders);
          } catch (firstError) {
            if (saveSourceIndex < 0) throw firstError;
            saveSourceIndex = -1;
            usedFallback = true;
            await proofApi.saveAnnotations(jobId, saveSourceIndex, annotations, authHeaders);
          }

          // 같은 실행에서 모델이 apply_annotations를 반복 호출해도 중복 저장하지 않는다.
          pending.length = 0;
          removals.length = 0;
          return {
            saved: true,
            count: annotations.length,
            source_index: saveSourceIndex,
            used_fallback: usedFallback,
          };
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          console.error(`[apply_annotations] job=${jobId} source_index=${sourceIndex}: ${message}`);
          return {
            saved: false,
            error: 'apply_annotations 저장 실패',
            detail: message,
            source_index: sourceIndex,
          };
        }
      },
    }),

    save_annotations: tool({
      description: 'EmbedPDF AnnotationTransferItem[] 형식의 주석 JSON을 직접 전달하여 Storage에 저장하고 뷰어에 반영한다. add_highlight/add_callout + apply_annotations 대신 사용할 수 있으며, view_page나 read_job_json으로 얻은 정보를 바탕으로 정밀한 위치(rect)를 지정해 주석을 만들 때 유용하다.\n' +
        '각 주석 항목의 구조: { annotation: { id, type (9=highlight, 3=freetext/callout), pageIndex (0-based), rect, color, strokeColor, opacity, contents, intent? ("FreeTextCallout"), lineEnding? (4=OpenArrow), segmentRects? } }\n' +
        'rect 좌표계: pdf_user_space=true(기본값)일 때 PDF user-space(y↑, 원점 좌하단)를 사용한다. 다음 형식을 지원한다:\n' +
        '  1. bbox_pdf 배열 직접 전달: rect = [x0, y0, x1, y1] (get_elements의 bbox_pdf 그대로 사용)\n' +
        '  2. {origin, size} 구조: rect = {origin: {x: x0, y: y0}, size: {width: x1-x0, height: y1-y0}} (y0는 PDF user-space 하단)\n' +
        '  3. annotation.bbox_pdf 필드: bbox_pdf = [x0, y0, x1, y1] (rect 대신 사용 가능)\n' +
        'get_elements(page_no)로 얻은 bbox_pdf를 그대로 rect에 전달하면 자동으로 device-space로 변환된다. read_job_json으로 읽은 기존 주석(device-space 좌표)을 그대로 전달할 때는 pdf_user_space=false로 설정한다.',
      inputSchema: z.object({
        annotations: z.array(z.record(z.unknown()))
          .describe('EmbedPDF AnnotationTransferItem[] 배열. 각 항목은 { annotation: { id, type, pageIndex, rect, color, ... } } 구조.'),
        merge: z.boolean().optional()
          .describe('true면 기존 주석과 병합 (기본값). false면 기존 주석을 모두 대체.'),
        pdf_user_space: z.boolean().optional()
          .describe('true면 rect 좌표가 PDF user-space(y↑)임 — 자동으로 device-space(y↓)로 변환. 기본값 true. 기존 주석의 device-space 좌표를 그대로 전달할 때는 false로 설정.'),
      }),
      execute: async ({ annotations, merge, pdf_user_space }) => {
        if (!annotations || annotations.length === 0) {
          return { saved: false, reason: 'No annotations provided' };
        }
        try {
          const shouldMerge = merge !== false;
          const shouldConvert = pdf_user_space !== false;

          // [Flow: Step 1 (PDF user-space → device-space 좌표 변환)
          //       -> Step 2 (저장할 source_index 결정)
          //       -> Step 3 (merge면 기존 주석 읽어 병합) -> Step 4 (FastAPI로 저장)]
          // AI가 get_elements의 bbox_pdf(PDF user-space)를 그대로 전달하는 경우,
          // Y축이 뒤집힌 상태로 저장되는 것을 방지하기 위해 자동 변환을 수행한다.
          let convertedAnnotations = annotations;
          if (shouldConvert) {
            const pageNos = [...new Set(annotations.map((a) => {
              const inner = (a as any).annotation && typeof (a as any).annotation === 'object'
                ? (a as any).annotation : a;
              return (Number(inner.pageIndex ?? 0) + 1);
            }))];
            const pageDims: Record<number, { width: number; height: number }> = {};
            for (const pageNo of pageNos) {
              pageDims[pageNo] = await loadPageDimensions(pageNo);
            }
            convertedAnnotations = annotations.map((a) => _convertAnnotationToDeviceSpace(a, pageDims));
          }

          let toSave = convertedAnnotations;
          let saveSourceIndex = sourceIndex;
          let usedFallback = false;
          if (shouldMerge) {
            try {
              const existing = await proofApi.getAnnotations(jobId, sourceIndex, undefined, authHeaders);
              const existingIds = new Set(existing.annotations.map((a) => {
                const inner = (a as any).annotation && typeof (a as any).annotation === 'object'
                  ? (a as any).annotation : a;
                return inner.id;
              }));
              const newOnes = convertedAnnotations.filter((a) => {
                const inner = (a as any).annotation && typeof (a as any).annotation === 'object'
                  ? (a as any).annotation : a;
                return !existingIds.has(inner.id);
              });
              toSave = [...existing.annotations, ...newOnes];
            } catch {
              // 기존 주석 파일이 없으면 source_index = -1로 fallback (원본 PDF에 JSON 저장)
              saveSourceIndex = -1;
              usedFallback = true;
              toSave = convertedAnnotations;
            }
          }

          try {
            await proofApi.saveAnnotations(jobId, saveSourceIndex, toSave as Array<Record<string, unknown>>, authHeaders);
          } catch (firstErr) {
            // source_index=0으로 실패하면 -1로 재시도 (원본 PDF fallback)
            if (saveSourceIndex >= 0) {
              saveSourceIndex = -1;
              usedFallback = true;
              await proofApi.saveAnnotations(jobId, saveSourceIndex, toSave as Array<Record<string, unknown>>, authHeaders);
            } else {
              throw firstErr;
            }
          }
          return {
            saved: true,
            count: toSave.length,
            new_count: convertedAnnotations.length,
            merged: shouldMerge,
            pdf_user_space_converted: shouldConvert,
            source_index: saveSourceIndex,
            used_fallback: usedFallback,
          };
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error(`[save_annotations] job=${jobId}: ${msg}`);
          return { error: `save_annotations failed: ${msg}` };
        }
      },
    }),
  };
}

/**
 * [Flow: Step 1 (AnnotationTransferItem 수신) -> Step 2 (annotation 객체 추출)
 *       -> Step 3 (rect 형식 정규화 — 배열 [x0,y0,x1,y1] / {origin,size} / {x,y,width,height} / bbox_pdf 필드)
 *       -> Step 4 (rect/segmentRects의 origin.y를 PDF user-space → device-space로 flip)
 *       -> Step 5 (변환된 주석 반환)]
 *
 * PDF user-space(원점 좌하단, y↑)의 rect를 embedpdf device-space(원점 좌상단, y↓)로 변환한다.
 * origin.y가 PDF user-space에서 하단(y0)일 때, device-space에서는 pageHeight - y0 - height = pageHeight - y1이 된다.
 * segmentRects가 있으면 동일하게 변환한다.
 *
 * AI가 전달할 수 있는 다양한 rect 형식을 처리한다:
 * - 배열 [x0, y0, x1, y1] (PDF user-space, get_elements의 bbox_pdf 그대로 전달)
 * - {origin: {x, y}, size: {width, height}} (origin.y = PDF user-space 하단 y0)
 * - {x, y, width, height} (레거시 형식, y = PDF user-space 하단 y0)
 * - bbox_pdf 필드가 별도로 있는 경우 (annotation.bbox_pdf = [x0, y0, x1, y1])
 *
 * @param item AnnotationTransferItem (PDF user-space 좌표)
 * @param pageDims 페이지 번호(1-based) → {width, height} 맵
 * @returns device-space로 변환된 AnnotationTransferItem
 */
function _convertAnnotationToDeviceSpace(
  item: Record<string, unknown>,
  pageDims: Record<number, { width: number; height: number }>,
): Record<string, unknown> {
  const inner = (item as any).annotation && typeof (item as any).annotation === 'object'
    ? (item as any).annotation : item;
  const pageNo = Number(inner.pageIndex ?? 0) + 1;
  const dims = pageDims[pageNo] || { width: 612, height: 792 };
  const pageHeight = dims.height;

  // [Flow: bbox_pdf 배열을 {origin, size} rect로 정규화]
  // AI가 get_elements의 bbox_pdf = [x0, y0, x1, y1]을 그대로 rect로 전달하거나
  // annotation.bbox_pdf 필드로 전달하는 경우를 처리한다.
  const normalizeRect = (rect: any): any => {
    if (!rect) return rect;
    // 배열 [x0, y0, x1, y1] (PDF user-space) → {origin, size}
    if (Array.isArray(rect) && rect.length >= 4) {
      const [x0, y0, x1, y1] = rect.map(Number);
      return {
        origin: { x: x0, y: y0 },
        size: { width: x1 - x0, height: y1 - y0 },
      };
    }
    if (typeof rect !== 'object') return rect;
    // 이미 {origin, size} 형태
    if (rect.origin && typeof rect.origin.x === 'number') return rect;
    // {x, y, width, height} 레거시 형태
    if (typeof rect.x === 'number' && typeof rect.width === 'number') {
      return {
        origin: { x: rect.x, y: rect.y },
        size: { width: rect.width, height: rect.height || 0 },
      };
    }
    return rect;
  };

  // rect 변환: origin.y (PDF user-space 하단 y0) → pageHeight - origin.y - size.height (device-space 상단)
  const convertRect = (rect: any): any => {
    const normalized = normalizeRect(rect);
    if (!normalized || typeof normalized !== 'object') return rect;
    const origin = normalized.origin;
    const size = normalized.size;
    if (!origin || typeof origin.y !== 'number' || !size || typeof size.height !== 'number') return rect;
    return {
      origin: { x: origin.x, y: pageHeight - origin.y - size.height },
      size: { width: size.width, height: size.height },
    };
  };

  const convertedInner = { ...inner };

  // [Flow: bbox_pdf 필드가 있으면 rect로 승격 — AI가 annotation.bbox_pdf로 전달하는 경우]
  if (Array.isArray(convertedInner.bbox_pdf) && !convertedInner.rect) {
    const [x0, y0, x1, y1] = convertedInner.bbox_pdf.map(Number);
    convertedInner.rect = {
      origin: { x: x0, y: y0 },
      size: { width: x1 - x0, height: y1 - y0 },
    };
  }

  if (convertedInner.rect) {
    convertedInner.rect = convertRect(convertedInner.rect);
  }
  if (Array.isArray(convertedInner.segmentRects)) {
    convertedInner.segmentRects = convertedInner.segmentRects.map(convertRect);
  }

  // item이 { annotation: {...} } 구조면 변환된 inner를 다시 감싸서 반환
  if ((item as any).annotation && typeof (item as any).annotation === 'object') {
    return { ...item, annotation: convertedInner };
  }
  return convertedInner;
}

/**
 * [Flow: Step 1 (PendingAnnotation + pageDimensions 수신) -> Step 2 (페이지 크기로 y축 flip)
 *       -> Step 3 (embedpdf AnnotationTransferItem 생성) -> Step 4 (반환)]
 *
 * Python pdf_annotator.py의 _rect_to_embedpdf_rect 와 동일한 변환을 수행한다.
 * PDF user-space(원점 좌하단, y↑) → embedpdf device-space(원점 좌상단, y↓).
 *
 * @param p pending 주석
 * @param pageDimensions 페이지 번호 → {width, height} 맵
 * @returns embedpdf AnnotationTransferItem
 */
function _buildAnnotationItem(
  p: PendingAnnotation,
  pageDimensions: Record<number, { width: number; height: number }>,
): Record<string, unknown> {
  const [x0, y0, x1, y1] = p.target.bbox_pdf;
  const dims = pageDimensions[p.target.page_no] || { width: 612, height: 792 };
  const pageHeight = dims.height;

  // PDF 좌표계(y↑) → embedpdf 좌표계(y↓): origin.y = page_height - y1
  const originX = x0;
  const originY = pageHeight - y1;
  const width = x1 - x0;
  const height = y1 - y0;

  const hexColor = _rgbToHex(p.target.color);

  if (p.type === 'highlight') {
    return {
      annotation: {
        id: p.id,
        type: 9, // embedpdf HIGHLIGHT
        pageIndex: p.target.page_no - 1,
        rect: { origin: { x: originX, y: originY }, size: { width, height } },
        segmentRects: [{ origin: { x: originX, y: originY }, size: { width, height } }],
        strokeColor: hexColor,
        color: hexColor,
        opacity: p.target.opacity,
        contents: p.target.comment,
      },
    };
  }

  // callout (FreeTextCallout)
  return {
    annotation: {
      id: p.id,
      type: 3, // embedpdf FREETEXT
      intent: 'FreeTextCallout',
      pageIndex: p.target.page_no - 1,
      rect: { origin: { x: originX, y: originY }, size: { width: Math.max(width, 80), height: Math.max(height, 24) } },
      strokeColor: hexColor,
      color: hexColor,
      opacity: p.target.opacity,
      contents: p.target.comment,
      lineEnding: 4, // OpenArrow
    },
  };
}

/**
 * [Flow: Step 1 (RGB[0-1] 수신) -> Step 2 (16진수 색상 문자열 변환) -> Step 3 (반환)]
 *
 * @param rgb RGB 배열
 * @returns #RRGGBB
 */
function _rgbToHex(rgb: [number, number, number]): string {
  const toByte = (v: number) => Math.round(v * 255).toString(16).padStart(2, '0');
  return `#${toByte(rgb[0])}${toByte(rgb[1])}${toByte(rgb[2])}`;
}
