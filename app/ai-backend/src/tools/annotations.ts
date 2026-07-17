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

/**
 * [Flow: Step 1 (rect 목록 수신) -> Step 2 (최소/최대 x, y 계산) -> Step 3 (bounding rect 반환)]
 *
 * 여러 검색 결과 rect를 하나의 bounding box로 합친다.
 *
 * @param rects PDF user-space rect 리스트
 * @returns bounding rect [x0, y0, x1, y1]
 */
function _unionRects(rects: Array<[number, number, number, number]>): [number, number, number, number] {
  if (!rects || rects.length === 0) return [0, 0, 0, 0];
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x0, y0, x1, y1] of rects) {
    minX = Math.min(minX, x0, x1);
    minY = Math.min(minY, y0, y1);
    maxX = Math.max(maxX, x0, x1);
    maxY = Math.max(maxY, y0, y1);
  }
  return [minX, minY, maxX, maxY];
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
  search_rects_pdf?: Array<[number, number, number, number]>;
  search_text?: string;
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
    const { elements } = await proofApi.getElements(jobId, pageNo, authHeaders);
    const cache: CachedElements = { elements };
    pageCache.set(key, cache);
    return cache;
  }

  return {
    search_text: tool({
      description: 'Search the PDF text layer for keywords or regular expressions. Returns the matched text and page number for verification. Do NOT use coordinates to build annotations manually; use add_text_highlight or add_text_callout with the matched text instead.',
      inputSchema: z.object({
        query: z.string().describe('Search keyword or regular expression'),
        page_no: z.number().optional().describe('1-based page number. Searches all pages if omitted'),
      }),
      execute: async ({ query, page_no }) => {
        const { matches } = await proofApi.searchText(jobId, query, page_no, authHeaders);
        // [Flow: 텍스트 기반 주석 생성을 유도 — 모델에 bbox_pdf 노출 금지]
        const textOnly = matches.slice(0, 20).map((m) => ({
          page_no: Number((m as any).page_no || 1),
          text: String((m as any).text || ''),
        }));
        return { matches: textOnly };
      },
    }),

    get_elements: tool({
      description: 'Return the list of page elements extracted from OCR or the text layer for text inspection only. Coordinates are intentionally omitted; do NOT use them to build annotations. To highlight/callout text, use add_text_highlight or add_text_callout with the exact text. In large PDFs or image-based PDFs, omitting page_no may require OCR of the entire document, so it can be very slow. Always specify page_no when you only need elements from a specific page.',
      inputSchema: z.object({
        page_no: z.number().optional().describe('1-based page number. Omitting it will OCR all pages (slow)'),
      }),
      execute: async ({ page_no }) => {
        // [Flow: Step 1 (loadElements로 FastAPI 조회) -> Step 2 (bbox 등 위치정보 제거 후 20개로 제한 반환)
        //       -> Step 3 (연결 실패 등 오류 발생 시 에러 메시지 반환)]
        try {
          const { elements } = await loadElements(page_no);
          const textOnly = elements.slice(0, 20).map((el) => ({
            page_no: Number((el as any).page_no || 1),
            text: String((el as any).text || ''),
            kind: String((el as any).kind || ''),
          }));
          return { elements: textOnly, total: elements.length };
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error(`[get_elements] job=${jobId} page=${page_no}: ${msg}`);
          return { error: `get_elements failed: ${msg}`, elements: [], total: 0 };
        }
      },
    }),

    read_job_json: tool({
      description: 'A general-purpose reader for various result JSONs of a job. Use kind to specify the data to read:\n' +
        '- "annotations": AI/user annotation JSON in PDF user-space (full structure of EmbedPDF AnnotationTransferItem[] — id, type, pageIndex, rect, color, contents, calloutLine, strokeColor, etc.). Use only for inspecting or editing existing annotations by id; do NOT reuse rect/segmentRects to create new annotations.\n' +
        '- "ocr_layout": OCR layout JSON (text block/table/image position info)\n' +
        '- "extracted_files": list of extracted files (markdown/image/PDF paths, etc.)\n' +
        '- "annotated_pdf_files": annotated PDF file metadata list\n' +
        '- "job_meta": job status summary (status, total_pages, file_type, has_pdf, etc.)\n' +
        'To add new highlights/callouts, use add_text_highlight/add_text_callout with exact text instead.',
      inputSchema: z.object({
        kind: z.enum(['annotations', 'ocr_layout', 'extracted_files', 'annotated_pdf_files', 'job_meta'])
          .describe('Type of result JSON to read'),
        page_no: z.number().optional().describe('1-based page number. Only used for filtering when kind=annotations'),
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
      description: 'Return the list of existing AI or user annotations together with the full original JSON structure. Coordinates (rect, segmentRects, calloutLine) are in PDF user-space (y↑, origin bottom-left) and are provided only for editing/deleting existing annotations by id. Do NOT reuse these coordinates to create new annotations; for new highlights/callouts use add_text_highlight/add_text_callout with exact text.',
      inputSchema: z.object({
        page_no: z.number().optional().describe('1-based page number. Returns all pages if omitted'),
        summary_only: z.boolean().optional().describe('If true, return only summary fields (id/type/page_no/color/comment). If omitted, return the full original JSON'),
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
      description: 'Render a specific page of the PDF as an image and analyze it directly with the VLLM vision model. Returns an analysis summarizing the page\'s text, layout, tables, and key elements. DPI is automatically estimated from the actual resolution of raster images on the page; if needed, specify between 150 and 300.',
      inputSchema: z.object({
        page_no: z.number().describe('1-based page number'),
        dpi: z.number().min(150).max(300).optional().describe('Rendering DPI (150-300; if omitted, auto-estimated from the page\'s image resolution)'),
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
      description: 'Change the color, comment, and opacity of an existing annotation. Use the id obtained from get_annotations.',
      inputSchema: z.object({
        annotation_id: z.string().describe('ID from get_annotations result'),
        color: z.enum(['red', 'yellow', 'green', 'blue', 'orange', 'purple', 'pink', 'gray'])
          .optional()
          .describe('Color name to change to'),
        comment: z.string().optional().describe('Comment to change to'),
        opacity: z.number().min(0).max(1).optional().describe('Opacity to change to (0.0~1.0)'),
      }),
      execute: async ({ annotation_id, color, comment, opacity }) => {
        const payload: { color?: string; comment?: string; opacity?: number } = {};
        if (color) payload.color = rgbToHex(COLOR_PALETTE[color] || DEFAULT_HIGHLIGHT_COLOR);
        if (comment !== undefined) payload.comment = comment;
        if (opacity !== undefined) payload.opacity = opacity;
        return proofApi.updateAnnotation(jobId, annotation_id, sourceIndex, payload, authHeaders);
      },
    }),

    add_text_highlight: tool({
      description: 'Add a highlight annotation by specifying the exact text to highlight. The backend searches the PDF text layer and highlights all matching occurrences. Use search_text first if you are unsure of the exact wording.',
      inputSchema: z.object({
        text: z.string().describe('Exact text string to highlight'),
        page_no: z.number().optional().describe('1-based page number to limit the search. Searches all pages if omitted'),
        comment: z.string().describe('Annotation comment'),
        color: z.enum(['red', 'yellow', 'green', 'blue', 'orange', 'purple', 'pink', 'gray'])
          .default('yellow')
          .describe('Color name'),
        opacity: z.number().min(0).max(1).optional().describe('Highlight opacity (0.0~1.0)'),
      }),
      execute: async ({ text, page_no, comment, color, opacity }) => {
        const { matches } = await proofApi.searchText(jobId, text, page_no, authHeaders);
        const validMatches = (matches || []).filter(
          (m) => Array.isArray((m as any).bbox_pdf) && (m as any).bbox_pdf.length === 4
        );
        if (validMatches.length === 0) {
          return { error: `Text not found for highlight: '${text}'. Call search_text first to verify exact wording.` };
        }
        const bboxes = validMatches.map((m) => (m as any).bbox_pdf as [number, number, number, number]);
        const pageNos = validMatches.map((m) => Number((m as any).page_no || page_no || 1));
        const pageNo = pageNos[0];
        const target: AnnotationTarget = {
          page_no: pageNo,
          bbox_pdf: _unionRects(bboxes),
          search_rects_pdf: bboxes,
          search_text: text,
          comment,
          color: COLOR_PALETTE[color] || DEFAULT_HIGHLIGHT_COLOR,
          opacity: opacity ?? DEFAULT_OPACITY,
        };
        const id = `ai-${Date.now()}-${pending.length}`;
        pending.push({ id, target, type: 'highlight' });
        return { ok: true, id, text, match_count: validMatches.length, page_no: pageNo };
      },
    }),

    add_text_callout: tool({
      description: 'Add a callout (text box + arrow) annotation by specifying the exact text to point to. The backend searches the PDF text layer and places the callout at the matching text. Use search_text first if you are unsure of the exact wording.',
      inputSchema: z.object({
        text: z.string().describe('Exact text string to point the callout to'),
        page_no: z.number().optional().describe('1-based page number to limit the search. Searches all pages if omitted'),
        comment: z.string().describe('Annotation comment'),
        color: z.enum(['red', 'yellow', 'green', 'blue', 'orange', 'purple', 'pink', 'gray'])
          .default('purple')
          .describe('Color name'),
        opacity: z.number().min(0).max(1).optional().describe('Callout opacity (0.0~1.0)'),
      }),
      execute: async ({ text, page_no, comment, color, opacity }) => {
        const { matches } = await proofApi.searchText(jobId, text, page_no, authHeaders);
        const first = (matches || []).find(
          (m) => Array.isArray((m as any).bbox_pdf) && (m as any).bbox_pdf.length === 4
        );
        if (!first) {
          return { error: `Text not found for callout: '${text}'. Call search_text first to verify exact wording.` };
        }
        const bbox = (first as any).bbox_pdf as [number, number, number, number];
        const pageNo = Number((first as any).page_no || page_no || 1);
        const target: AnnotationTarget = {
          page_no: pageNo,
          bbox_pdf: bbox,
          search_text: text,
          comment,
          color: COLOR_PALETTE[color] || DEFAULT_CALLOUT_COLOR,
          opacity: opacity ?? DEFAULT_OPACITY,
        };
        const id = `ai-${Date.now()}-${pending.length}`;
        pending.push({ id, target, type: 'callout' });
        return { ok: true, id, text, page_no: pageNo };
      },
    }),

    remove_annotation: tool({
      description: 'Remove an existing AI annotation. User approval is required before deletion.',
      inputSchema: z.object({
        annotation_id: z.string().describe('ID of the annotation to remove'),
      }),
      execute: async ({ annotation_id }) => {
        removals.push(annotation_id);
        return { ok: true, removed: annotation_id, requires_approval: true };
      },
    }),

    compare_elements: tool({
      description: 'Compare and analyze elements across multiple pages.',
      inputSchema: z.object({
        description: z.string().describe('Comparison criteria or condition'),
        page_nos: z.array(z.number()).describe('List of 1-based page numbers to compare'),
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
      description: 'Save the highlights/callouts added so far to Storage and reflect them in the viewer. Even if saving fails, the actual cause is returned in the result.',
      inputSchema: z.object({}),
      execute: async () => {
        // [Flow: Step 1 (대기 중인 변경 확인) -> Step 2 (주석 JSON 생성)
        //       -> Step 3 (원래 주석 파일 저장 시도) -> Step 4 (원본 JSON fallback)
        //       -> Step 5 (구조화된 저장 결과 반환)]
        if (pending.length === 0 && removals.length === 0) {
          return { saved: false, reason: 'No annotation changes to save.' };
        }

        if (pending.length === 0) {
          // 현재 remove_annotation은 승인 대기 상태만 기록하고 실제 삭제 API를 호출하지 않는다.
          // 빈 배열을 저장 API에 보내면 백엔드가 400을 반환하므로 명시적인 결과를 반환한다.
          return {
            saved: false,
            removals: removals.length,
            reason: 'Deletion requests are pending approval and no new annotations were added, so nothing was saved.',
          };
        }

        try {
          // [Flow: AI 백엔드는 좌표 변환을 하지 않고 PDF user-space 그대로 전송
          //       -> 변환은 FastAPI pdf_user_annotator.apply_user_annotations에서 수행]
          console.log(`[apply_annotations] job=${jobId} count=${pending.length} input_space=pdf_user`);
          const annotations = pending.map((pendingAnnotation) => _buildAnnotationItem(pendingAnnotation));
          let saveSourceIndex = sourceIndex;
          let usedFallback = false;

          // [Flow: Step 1 (source_index로 주석 PDF 저장) -> Step 2 (404/실패 감지)
          //       -> Step 3 (source_index=-1로 원본 PDF의 JSON 저장)]
          try {
            await proofApi.saveAnnotations(jobId, saveSourceIndex, annotations, 'pdf_user', authHeaders);
          } catch (firstError) {
            if (saveSourceIndex < 0) throw firstError;
            saveSourceIndex = -1;
            usedFallback = true;
            await proofApi.saveAnnotations(jobId, saveSourceIndex, annotations, 'pdf_user', authHeaders);
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
            error: 'apply_annotations save failed',
            detail: message,
            source_index: sourceIndex,
          };
        }
      },
    }),

  };
}

/**
 * [Flow: Step 1 (PendingAnnotation 수신) -> Step 2 (PDF user-space AnnotationTransferItem 생성) -> Step 3 (반환)]
 *
 * AI 백엔드는 좌표 변환을 하지 않고 PDF user-space 좌표를 그대로 전달한다.
 * 변환은 FastAPI의 pdf_user_annotator.apply_user_annotations에서 실제 PDF page_height를 기준으로 수행한다.
 *
 * PDF user-space rect: origin.y = y0 (페이지 하단 기준), size.height = y1 - y0.
 *
 * @param p pending 주석
 * @returns PDF user-space 기반 AnnotationTransferItem
 */
function _buildAnnotationItem(p: PendingAnnotation): Record<string, unknown> {
  const [x0, y0, x1, y1] = p.target.bbox_pdf;
  const width = x1 - x0;
  const height = y1 - y0;

  const hexColor = _rgbToHex(p.target.color);

  if (p.type === 'highlight') {
    // [Flow: search_rects_pdf가 있으면 각 rect를 segmentRects로 사용, 없으면 단일 rect]
    const segmentRects = p.target.search_rects_pdf && p.target.search_rects_pdf.length > 0
      ? p.target.search_rects_pdf.map(([sx0, sy0, sx1, sy1]) => ({
          origin: { x: sx0, y: sy0 },
          size: { width: sx1 - sx0, height: sy1 - sy0 },
        }))
      : [{ origin: { x: x0, y: y0 }, size: { width, height } }];
    return {
      annotation: {
        id: p.id,
        type: 9, // embedpdf HIGHLIGHT
        pageIndex: p.target.page_no - 1,
        rect: { origin: { x: x0, y: y0 }, size: { width, height } },
        segmentRects,
        strokeColor: hexColor,
        color: hexColor,
        opacity: p.target.opacity,
        contents: p.target.comment,
        custom: p.target.search_text ? { searchText: p.target.search_text } : undefined,
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
      rect: { origin: { x: x0, y: y0 }, size: { width: Math.max(width, 80), height: Math.max(height, 24) } },
      strokeColor: hexColor,
      color: hexColor,
      opacity: p.target.opacity,
      contents: p.target.comment,
      lineEnding: 4, // OpenArrow
      fontFamily: 4, // PdfStandardFont.Helvetica
      fontSize: 8,
      fontColor: '#333333',
      textAlign: 0, // PdfTextAlignment.Left
      verticalAlign: 0, // PdfVerticalAlignment.Top
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
