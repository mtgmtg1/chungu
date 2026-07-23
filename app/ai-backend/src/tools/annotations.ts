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
 * @param rects device-space rect 리스트 (search_job_text 반환 좌표)
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

interface BatchItemInput {
  text: string;
  page_no?: number;
  comment?: string;
  color?: string;
  opacity?: number;
}

/**
 * [Flow: Step 1 (texts 축약 배열 → 공통 파라미터 적용) → Step 2 (items 배열 그대로 사용)
 *       → Step 3 (text 배열 → 인덱스별 매핑) → Step 4 (text 단일 문자열 → 단건)]
 *
 * 입력 우선순위: texts > items > text[](배열) > text(문자열)
 * texts를 사용하면 page_no/comment/color/opacity는 모든 텍스트에 동일 적용되어 토큰 절약.
 *
 * @param input 도구 입력 파라미터
 * @returns 파싱된 BatchItemInput 배열
 */
function parseBatchInputs(input: {
  texts?: string[];
  items?: BatchItemInput[];
  text?: string | string[];
  page_no?: number | number[];
  comment?: string | string[];
  color?: string | string[];
  opacity?: number | number[];
}): BatchItemInput[] {
  // [Flow: texts 축약 배열 — 공통 page_no/comment/color/opacity를 모든 텍스트에 일괄 적용]
  if (Array.isArray(input.texts) && input.texts.length > 0) {
    const sharedPageNo = typeof input.page_no === 'number' ? input.page_no : undefined;
    const sharedComment = typeof input.comment === 'string' ? input.comment : '';
    const sharedColor = typeof input.color === 'string' ? input.color : undefined;
    const sharedOpacity = typeof input.opacity === 'number' ? input.opacity : undefined;
    return input.texts
      .map((t) => ({
        text: String(t || '').trim(),
        page_no: sharedPageNo,
        comment: sharedComment,
        color: sharedColor,
        opacity: sharedOpacity,
      }))
      .filter((item) => item.text);
  }
  if (Array.isArray(input.items) && input.items.length > 0) {
    return input.items.filter((item) => item && typeof item.text === 'string' && item.text.trim());
  }
  if (Array.isArray(input.text)) {
    return input.text
      .map((t, idx) => ({
        text: String(t || '').trim(),
        page_no: Array.isArray(input.page_no) ? input.page_no[idx] : (typeof input.page_no === 'number' ? input.page_no : undefined),
        comment: Array.isArray(input.comment) ? input.comment[idx] : (typeof input.comment === 'string' ? input.comment : ''),
        color: Array.isArray(input.color) ? input.color[idx] : (typeof input.color === 'string' ? input.color : undefined),
        opacity: Array.isArray(input.opacity) ? input.opacity[idx] : (typeof input.opacity === 'number' ? input.opacity : undefined),
      }))
      .filter((item) => item.text);
  }
  if (typeof input.text === 'string' && input.text.trim()) {
    return [
      {
        text: input.text.trim(),
        page_no: typeof input.page_no === 'number' ? input.page_no : undefined,
        comment: typeof input.comment === 'string' ? input.comment : '',
        color: typeof input.color === 'string' ? input.color : undefined,
        opacity: typeof input.opacity === 'number' ? input.opacity : undefined,
      },
    ];
  }
  return [];
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
        '- "annotations": AI/user annotation JSON (id, type, pageIndex, color, contents, strokeColor, opacity, etc.). Coordinate fields (rect, segmentRects, calloutLine, bbox_pdf) are REDACTED. Use only to inspect or edit existing annotations by id.\n' +
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
          let data = result.data;
          if (kind === 'annotations' && Array.isArray(data)) {
            // [Flow: annotations 조회 시 좌표 필드 redaction — 모델이 좌표를 재사용하지 못하도록 차단]
            data = data.slice(0, 30).map((a) => _redactAnnotationCoords(a as Record<string, unknown>));
          } else if (Array.isArray(data) && data.length > 30) {
            data = data.slice(0, 30);
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
      description: 'Return the list of existing AI or user annotations. Coordinate fields (rect, segmentRects, calloutLine, bbox_pdf) are REDACTED from the output to prevent reuse for new annotations. Use only to list ids, comments, and colors for editing or deleting existing annotations (update_annotation/remove_annotation). For new highlights/callouts use add_text_highlight/add_text_callout with exact text.',
      inputSchema: z.object({
        page_no: z.number().optional().describe('1-based page number. Returns all pages if omitted'),
        summary_only: z.boolean().optional().describe('If true, return only summary fields (id/type/page_no/color/comment).'),
      }),
      execute: async ({ page_no, summary_only }) => {
        // [Flow: Step 1 (FastAPI에서 주석 목록 조회) -> Step 2 (404 시 빈 배열로 폴백)
        //       -> Step 3 (좌표 필드 redaction) -> Step 4 (summary 또는 전체 반환)]
        // Vercel AI SDK가 tool 에러를 "An error occurred."로 마스킹하므로
        // try/catch로 명확한 결과를 tool output에 포함한다.
        try {
          const { annotations, total } = await proofApi.getAnnotations(jobId, sourceIndex, page_no, authHeaders);
          // [Flow: 출력 크기 제한 — 80→30개로 축소하여 토큰 소비 절약]
          const sliced = annotations.slice(0, 30);
          const redacted = sliced.map((a) => _redactAnnotationCoords(a as Record<string, unknown>));
          if (summary_only) {
            return {
              annotations: redacted.map((a) => {
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
          return { annotations: redacted, total };
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
      description: 'Render a specific page of the PDF as an image and analyze it directly with the VLLM vision model. Returns a textual analysis summarizing the page\'s text, layout, tables, and key elements. This output is text-only and does NOT contain coordinates, bounding boxes, or precise positions. Use it only to understand what is on the page, then create annotations with add_text_highlight/add_text_callout using exact text strings.',
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
      description: 'Add one or more highlight annotations. PREFERRED: Use `texts` (string array) + shared page_no/comment/color/opacity when all items share the same settings — this saves tokens. Use `items` only when each item needs DIFFERENT settings. Example: `{ texts: ["A", "B", "C"], page_no: 1, color: "yellow" }` instead of 3 separate items.',
      inputSchema: z.object({
        texts: z.array(z.string()).optional().describe('PREFERRED for batch: Array of text strings to highlight with shared settings below'),
        items: z.array(
          z.object({
            text: z.string().describe('Exact text string to highlight'),
            page_no: z.number().optional().describe('1-based page number'),
            comment: z.string().optional().describe('Annotation comment'),
            color: z.enum(['red', 'yellow', 'green', 'blue', 'orange', 'purple', 'pink', 'gray']).optional().describe('Color name'),
            opacity: z.number().min(0).max(1).optional().describe('Highlight opacity (0.0~1.0)'),
          })
        ).optional().describe('List of highlight items when each needs DIFFERENT settings'),
        text: z.union([z.string(), z.array(z.string())]).optional().describe('Exact text or array of text strings to highlight'),
        page_no: z.union([z.number(), z.array(z.number())]).optional().describe('1-based page number (shared when using texts)'),
        comment: z.union([z.string(), z.array(z.string())]).optional().describe('Annotation comment (shared when using texts)'),
        color: z.union([
          z.enum(['red', 'yellow', 'green', 'blue', 'orange', 'purple', 'pink', 'gray']),
          z.array(z.enum(['red', 'yellow', 'green', 'blue', 'orange', 'purple', 'pink', 'gray'])),
        ]).optional().describe('Color name (shared when using texts)'),
        opacity: z.union([z.number(), z.array(z.number())]).optional().describe('Highlight opacity (shared when using texts)'),
      }),
      execute: async (input) => {
        const itemsToProcess = parseBatchInputs(input as any);
        if (itemsToProcess.length === 0) {
          return { error: 'No valid text provided for add_text_highlight. Pass text or items array.' };
        }
        const results = [];
        for (const item of itemsToProcess) {
          const { matches } = await proofApi.searchText(jobId, item.text, item.page_no, authHeaders, 'line');
          const validMatches = (matches || []).filter(
            (m) => Array.isArray((m as any).bbox_pdf) && (m as any).bbox_pdf.length === 4
          );
          // [TABLE_DEBUG] searchText 결과 좌표 로깅
          if (validMatches.length > 0) {
            const bboxSample = validMatches.slice(0, 3).map((m) => ({
              bbox: (m as any).bbox_pdf.map((v: number) => Math.round(v * 10) / 10),
              text: String((m as any).text || '').slice(0, 30),
            }));
            console.log(
              `[TABLE_DEBUG] add_text_highlight: text='${item.text.slice(0, 40)}' ` +
              `matches=${validMatches.length} bboxes=${JSON.stringify(bboxSample)}`
            );
          }
          if (validMatches.length === 0) {
            results.push({ text: item.text, success: false, error: `Text not found for highlight: '${item.text}'` });
            continue;
          }
          const bboxes = validMatches.map((m) => (m as any).bbox_pdf as [number, number, number, number]);
          const pageNos = validMatches.map((m) => Number((m as any).page_no || item.page_no || 1));
          const pageNo = pageNos[0];
          const colorKey = item.color || 'yellow';
          const target: AnnotationTarget = {
            page_no: pageNo,
            bbox_pdf: _unionRects(bboxes),
            search_rects_pdf: bboxes,
            search_text: item.text,
            comment: item.comment || '',
            color: COLOR_PALETTE[colorKey] || DEFAULT_HIGHLIGHT_COLOR,
            opacity: item.opacity ?? DEFAULT_OPACITY,
          };
          // [TABLE_DEBUG] 최종 AnnotationTarget 좌표 로깅
          console.log(
            `[TABLE_DEBUG] add_text_highlight target: page=${pageNo} ` +
            `bbox_pdf=[${target.bbox_pdf.map(v => v.toFixed(1)).join(', ')}] ` +
            `rects_count=${bboxes.length}`
          );
          const id = `ai-${Date.now()}-${pending.length}`;
          pending.push({ id, target, type: 'highlight' });
          results.push({ ok: true, id, text: item.text, match_count: validMatches.length, page_no: pageNo });
        }
        return {
          ok: true,
          added_count: results.filter((r) => r.ok).length,
          results,
        };
      },
    }),

    add_text_callout: tool({
      description: 'Add one or more callout (text box + leader arrow) annotations. PREFERRED: Use `texts` (string array) + shared page_no/comment/color/opacity when all items share the same settings — this saves tokens. Use `items` only when each item needs DIFFERENT settings.',
      inputSchema: z.object({
        texts: z.array(z.string()).optional().describe('PREFERRED for batch: Array of text strings with shared settings below'),
        items: z.array(
          z.object({
            text: z.string().describe('Exact text string to point callout to'),
            page_no: z.number().optional().describe('1-based page number'),
            comment: z.string().optional().describe('Annotation comment'),
            color: z.enum(['red', 'yellow', 'green', 'blue', 'orange', 'purple', 'pink', 'gray']).optional().describe('Color name'),
            opacity: z.number().min(0).max(1).optional().describe('Callout opacity (0.0~1.0)'),
          })
        ).optional().describe('List of callout items when each needs DIFFERENT settings'),
        text: z.union([z.string(), z.array(z.string())]).optional().describe('Exact text or array of text strings to point callout to'),
        page_no: z.union([z.number(), z.array(z.number())]).optional().describe('1-based page number (shared when using texts)'),
        comment: z.union([z.string(), z.array(z.string())]).optional().describe('Annotation comment (shared when using texts)'),
        color: z.union([
          z.enum(['red', 'yellow', 'green', 'blue', 'orange', 'purple', 'pink', 'gray']),
          z.array(z.enum(['red', 'yellow', 'green', 'blue', 'orange', 'purple', 'pink', 'gray'])),
        ]).optional().describe('Color name (shared when using texts)'),
        opacity: z.union([z.number(), z.array(z.number())]).optional().describe('Callout opacity (shared when using texts)'),
      }),
      execute: async (input) => {
        const itemsToProcess = parseBatchInputs(input as any);
        if (itemsToProcess.length === 0) {
          return { error: 'No valid text provided for add_text_callout. Pass text or items array.' };
        }
        const results = [];
        for (const item of itemsToProcess) {
          const { matches } = await proofApi.searchText(jobId, item.text, item.page_no, authHeaders, 'line');
          const first = (matches || []).find(
            (m) => Array.isArray((m as any).bbox_pdf) && (m as any).bbox_pdf.length === 4
          );
          if (!first) {
            results.push({ text: item.text, success: false, error: `Text not found for callout: '${item.text}'` });
            continue;
          }
          const bbox = (first as any).bbox_pdf as [number, number, number, number];
          const pageNo = Number((first as any).page_no || item.page_no || 1);
          const colorKey = item.color || 'purple';
          const target: AnnotationTarget = {
            page_no: pageNo,
            bbox_pdf: bbox,
            search_text: item.text,
            comment: item.comment || '',
            color: COLOR_PALETTE[colorKey] || DEFAULT_CALLOUT_COLOR,
            opacity: item.opacity ?? DEFAULT_OPACITY,
          };
          const id = `ai-${Date.now()}-${pending.length}`;
          pending.push({ id, target, type: 'callout' });
          results.push({ ok: true, id, text: item.text, page_no: pageNo });
        }
        return {
          ok: true,
          added_count: results.filter((r) => r.ok).length,
          results,
        };
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
      description: 'Compare text elements across multiple pages. Returns page_no, text, and kind only; coordinates are intentionally omitted. Do not use the output to construct annotation positions.',
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
            elements: pageElements.slice(0, 10).map((el) => ({
              page_no: Number((el as any).page_no || 1),
              text: String((el as any).text || ''),
              kind: String((el as any).kind || ''),
            })),
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
          // [Flow: AI 백엔드는 좌표 변환을 하지 않고 device-space 그대로 전송
          //       -> search_job_text(search_for + OCR 폴백)는 모두 device-space(y=0 상단)를 반환
          //       -> FastAPI /jobs/{id}/user-annotations는 input_space='device'일 때 변환 없이 저장]
          console.log(`[apply_annotations] job=${jobId} count=${pending.length} input_space=device`);
          const annotations = pending.map((pendingAnnotation) => _buildAnnotationItem(pendingAnnotation));
          let saveSourceIndex = sourceIndex;
          let usedFallback = false;

          // [Flow: Step 1 (source_index로 주석 JSON 저장) -> Step 2 (404/실패 감지)
          //       -> Step 3 (source_index=-1로 원본 PDF의 JSON 저장)]
          try {
            await proofApi.saveAnnotations(jobId, saveSourceIndex, annotations, 'device', authHeaders);
          } catch (firstError) {
            if (saveSourceIndex < 0) throw firstError;
            saveSourceIndex = -1;
            usedFallback = true;
            await proofApi.saveAnnotations(jobId, saveSourceIndex, annotations, 'device', authHeaders);
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
 * [Flow: Step 1 (PendingAnnotation 수신) -> Step 2 (device-space AnnotationTransferItem 생성) -> Step 3 (반환)]
 *
 * AI 백엔드는 좌표 변환을 하지 않고 device-space 좌표를 그대로 전달한다.
 * search_job_text의 search_for 경로와 OCR 폴백 경로는 모두 device-space(y=0 상단)를 반환한다.
 * FastAPI의 /jobs/{id}/user-annotations 엔드포인트는 input_space='device'일 때 변환 없이 저장한다.
 *
 * device-space rect: origin.y = y0 (페이지 상단 기준, y↓), size.height = y1 - y0.
 *
 * @param p pending 주석
 * @returns device-space 기반 AnnotationTransferItem
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
  // 대상 텍스트 영역: [x0, y0, x1, y1]
  // 팁 위치 (대상 텍스트 좌측/상단): tip = [x0, y0 + height / 2]
  const tbWidth = Math.max(width, 120);
  const tbHeight = Math.max(height + 16, 32);
  const boxX0 = Math.max(10, x0 - 150);
  const boxY0 = y0;

  // 3점 calloutLine: [arrowTip, knee, connectionPoint]
  const tipPoint = { x: x0, y: y0 + height / 2 };
  const kneePoint = { x: boxX0 + tbWidth + 15, y: y0 + height / 2 };
  const boxConnPoint = { x: boxX0 + tbWidth, y: boxY0 + tbHeight / 2 };
  const calloutLine = [tipPoint, kneePoint, boxConnPoint];

  // overallRect (텍스트 박스 + calloutLine 을 포함하는 AABB)
  const minX = Math.min(x0, boxX0);
  const minY = Math.min(y0, boxY0);
  const maxX = Math.max(x1, boxX0 + tbWidth);
  const maxY = Math.max(y1, boxY0 + tbHeight);
  const overallRect = { origin: { x: minX, y: minY }, size: { width: maxX - minX, height: maxY - minY } };

  // rectangleDifferences: overallRect 내에서 텍스트 박스 위치와의 차이 (inset) [left, top, right, bottom]
  const rd = [
    boxX0 - minX,
    boxY0 - minY,
    maxX - (boxX0 + tbWidth),
    maxY - (boxY0 + tbHeight),
  ];

  return {
    annotation: {
      id: p.id,
      type: 3, // embedpdf FREETEXT
      intent: 'FreeTextCallout',
      pageIndex: p.target.page_no - 1,
      rect: overallRect,
      rectangleDifferences: rd,
      calloutLine,
      lineEnding: 4, // OpenArrow
      strokeColor: hexColor,
      strokeWidth: 1.5,
      color: '#FFFFFF',
      opacity: p.target.opacity,
      contents: p.target.comment,
      fontFamily: 4, // PdfStandardFont.Helvetica
      fontSize: 9,
      fontColor: '#1A1A1A',
      textAlign: 0, // Left
      verticalAlign: 0, // Top
    },
  };

}

/**
 * [Flow: Step 1 (AnnotationTransferItem 수신) -> Step 2 (좌표 관련 필드 제거)
 *       -> Step 3 (에이전트에 안전한 사본 반환)]
 *
 * 기존 주석의 id/type/pageIndex/contents/color 등은 유지하면서,
 * rect, segmentRects, calloutLine, bbox_pdf 등 위치 정보를 제거한다.
 * 에이전트가 기존 좌표를 새 주석 생성에 재사용하지 못하도록 차단한다.
 *
 * @param item 주석 아이템 ({annotation: {...}} 또는 평탄한 구조)
 * @returns 좌표가 제거된 주석 아이템
 */
function _redactAnnotationCoords(item: Record<string, unknown>): Record<string, unknown> {
  const clone = JSON.parse(JSON.stringify(item));
  const inner = clone.annotation && typeof clone.annotation === 'object'
    ? (clone.annotation as Record<string, unknown>)
    : clone;
  delete inner.rect;
  delete inner.segmentRects;
  delete inner.calloutLine;
  delete inner.bbox_pdf;
  delete inner.callout;
  return clone;
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
