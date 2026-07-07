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
  const sourceIndex = Number(context.sourceIndex ?? context.source_index ?? 0);
  const authHeaders = context.authHeaders || {};

  // [Flow: Step 1 (현재 요청에서 추가/삭제될 주석을 임시 저장) -> Step 2 (apply_annotations에서 일괄 저장)]
  const pending: PendingAnnotation[] = [];
  const removals: string[] = [];
  // 요소/페이지 크기 캐시 — 동일 에이전트 실행 내에서 재사용
  let elementsCache: CachedElements | null = null;

  /**
   * [Flow: Step 1 (캐시 확인) -> Step 2 (FastAPI에서 요소 조회) -> Step 3 (캐시에 저장) -> Step 4 (반환)]
   */
  async function loadElements(): Promise<CachedElements> {
    if (elementsCache) return elementsCache;
    const { elements, pageDimensions } = await proofApi.getElements(jobId, undefined, authHeaders);
    elementsCache = { elements, pageDimensions };
    return elementsCache;
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
      description: 'OCR 또는 텍스트 레이어에서 추출한 페이지 요소 목록을 반환한다.',
      inputSchema: z.object({
        page_no: z.number().optional().describe('1-based 페이지 번호. 생략 시 모든 페이지'),
      }),
      execute: async ({ page_no }) => {
        const { elements } = await loadElements();
        const filtered = page_no !== undefined
          ? elements.filter((el) => Number(el.page_no) === page_no)
          : elements;
        return { elements: filtered.slice(0, 50), total: filtered.length };
      },
    }),

    get_annotations: tool({
      description: '기존 AI 주석 또는 사용자 주석의 목록을 반환한다. 주석의 ID, 종류, 색상, 코멘트, 페이지, 위치를 확인할 때 사용한다.',
      inputSchema: z.object({
        page_no: z.number().optional().describe('1-based 페이지 번호. 생략 시 모든 페이지'),
      }),
      execute: async ({ page_no }) => {
        const { annotations, total } = await proofApi.getAnnotations(jobId, sourceIndex, page_no, authHeaders);
        return {
          annotations: annotations.slice(0, 50).map((a) => {
            const inner = (a as any).annotation && typeof (a as any).annotation === 'object'
              ? (a as any).annotation
              : a;
            return {
              id: inner.id,
              type: inner.type,
              page_no: (inner.pageIndex ?? 0) + 1,
              color: inner.color,
              opacity: inner.opacity,
              comment: inner.contents,
            };
          }),
          total,
        };
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
      description: '선택한 요소에 하이라이트 주석을 추가한다.',
      inputSchema: z.object({
        element_index: z.number().describe('get_elements 결과의 인덱스'),
        comment: z.string().describe('주석 코멘트'),
        color: z.enum(['red', 'yellow', 'green', 'blue', 'orange', 'purple', 'pink', 'gray'])
          .default('yellow')
          .describe('색상 이름'),
      }),
      execute: async ({ element_index, comment, color }) => {
        const { elements } = await loadElements();
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
      description: '선택한 요소에 callout(텍스트 박스 + 화살표) 주석을 추가한다.',
      inputSchema: z.object({
        element_index: z.number().describe('get_elements 결과의 인덱스'),
        comment: z.string().describe('주석 코멘트'),
        color: z.enum(['red', 'yellow', 'green', 'blue', 'orange', 'purple', 'pink', 'gray'])
          .default('purple')
          .describe('색상 이름'),
      }),
      execute: async ({ element_index, comment, color }) => {
        const { elements } = await loadElements();
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
        const { elements } = await loadElements();
        const results = page_nos.slice(0, 5).map((pageNo) => {
          const pageElements = elements.filter((el) => Number(el.page_no) === pageNo);
          return {
            page_no: pageNo,
            count: pageElements.length,
            elements: pageElements.slice(0, 10),
          };
        });
        return { description, page_nos, results };
      },
    }),

    apply_annotations: tool({
      description: '현재까지 추가한 하이라이트/콜아웃을 Storage에 저장하고 뷰어에 반영한다.',
      inputSchema: z.object({}),
      execute: async () => {
        if (pending.length === 0 && removals.length === 0) {
          return { saved: false, reason: 'No pending annotations or removals' };
        }
        const { pageDimensions } = await loadElements();
        // [Flow: Step 1 (pending 주석을 embedpdf AnnotationTransferItem[] 형식으로 변환)
        //       -> Step 2 (FastAPI /user-annotations 로 저장) -> Step 3 (결과 반환)]
        const annotations = pending.map((p) =>
          _buildAnnotationItem(p, pageDimensions),
        );
        await proofApi.saveAnnotations(jobId, sourceIndex, annotations, authHeaders);
        return { saved: true, count: annotations.length, removals: removals.length };
      },
    }),
  };
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
        rect: { x: originX, y: originY, width, height },
        segmentRects: [{ x: originX, y: originY, width, height }],
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
      rect: { x: originX, y: originY, width: Math.max(width, 80), height: Math.max(height, 24) },
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
