// [Flow: Step 1 (context에서 job_id, authHeaders 추출)
//       -> Step 2 (마크다운에서 헤딩 트리 추출 / elkjs 레이아웃 계산)
//       -> Step 3 (드로잉/주석/노트/엣지/헤딩 조작 도구 생성)
//       -> Step 4 (도구 객체 반환)]
// 플로우 뷰용 서버 사이드 도구. 마크다운 문서의 헤딩 구조를 추출하고,
// AI로 논리적 트리 구조를 분석하여 React Flow 부모-자식 에지 데이터를 생성.
// 드로잉(SVG path), 텍스트 주석, 노트 노드, 커스텀 엣지, 헤딩 노드 조작 도구를 제공.
import { tool } from 'ai';
import { z } from 'zod';
import { marked } from 'marked';
import ELK from 'elkjs/lib/elk.bundled.js';
const elk = new (ELK as unknown as { new (): any })();
import type { AuthHeaders } from '../lib/auth.js';
import * as proofApi from '../lib/proof-api.js';

interface FlowToolContext {
  jobId?: string;
  job_id?: string;
  authHeaders?: AuthHeaders;
  [key: string]: unknown;
}

// 기본 드로잉 색상 팔레트 — 프론트엔드 drawingUtils.js와 동기화
const DEFAULT_STROKE_COLOR = '#6366f1';
const DEFAULT_STROKE_WIDTH = 4;
const DEFAULT_TEXT_COLOR = '#6366f1';
const DEFAULT_FONT_SIZE = 14;

/**
 * 도형 SVG path 생성 — 선 / 화살표 / 사각형 / 원.
 * drawingUtils.js의 createShapePath 로직을 TypeScript로 포팅.
 *
 * [Flow: Step 1 (시작점/끝점/도형 타입 수신) -> Step 2 (SVG path d 속성 생성) -> Step 3 (반환)]
 *
 * @param x1 시작점 x
 * @param y1 시작점 y
 * @param x2 끝점 x
 * @param y2 끝점 y
 * @param shape 도형 타입 ("line" | "arrow" | "rectangle" | "circle")
 * @returns SVG path d 속성 문자열
 */
function createShapePath(
  x1: number, y1: number, x2: number, y2: number,
  shape: 'line' | 'arrow' | 'rectangle' | 'circle',
): string {
  switch (shape) {
    case 'line':
      return `M ${x1} ${y1} L ${x2} ${y2}`;
    case 'arrow': {
      const angle = Math.atan2(y2 - y1, x2 - x1);
      const headLength = 12;
      const headAngle = Math.PI / 6;
      const x3 = x2 - headLength * Math.cos(angle - headAngle);
      const y3 = y2 - headLength * Math.sin(angle - headAngle);
      const x4 = x2 - headLength * Math.cos(angle + headAngle);
      const y4 = y2 - headLength * Math.sin(angle + headAngle);
      return `M ${x1} ${y1} L ${x2} ${y2} M ${x3} ${y3} L ${x2} ${y2} L ${x4} ${y4}`;
    }
    case 'rectangle': {
      const rx = Math.min(x1, x2);
      const ry = Math.min(y1, y2);
      const rw = Math.abs(x2 - x1);
      const rh = Math.abs(y2 - y1);
      return `M ${rx} ${ry} L ${rx + rw} ${ry} L ${rx + rw} ${ry + rh} L ${rx} ${ry + rh} Z`;
    }
    case 'circle': {
      const cx = (x1 + x2) / 2;
      const cy = (y1 + y2) / 2;
      const radiusX = Math.abs(x2 - x1) / 2;
      const radiusY = Math.abs(y2 - y1) / 2;
      return `M ${cx - radiusX} ${cy} A ${radiusX} ${radiusY} 0 1 0 ${cx + radiusX} ${cy} A ${radiusX} ${radiusY} 0 1 0 ${cx - radiusX} ${cy}`;
    }
    default:
      return '';
  }
}

/**
 * 마크다운에서 헤딩 토큰을 추출하여 골격 노드 배열과 계층 에지 배열을 생성.
 * 토큰 소모 없이 순수 파싱만 수행.
 *
 * [Flow: Step 1 (marked.lexer 토큰화) -> Step 2 (heading 토큰 추출) -> Step 3 (스택 기반 부모-자식 에지)]
 *
 * @param markdown 마크다운 문자열
 * @returns 노드 배열과 계층 에지 배열
 */
function _extractHeadingStructure(markdown: string): {
  nodes: Array<{ id: string; heading: string; level: number; summary: string; keywords: string[] }>;
  edges: Array<{ source: string; target: string; type: string }>;
} {
  const tokens = marked.lexer(markdown || '');
  const nodes: Array<{ id: string; heading: string; level: number; summary: string; keywords: string[] }> = [];
  const edges: Array<{ source: string; target: string; type: string }> = [];
  const stack: Array<{ id: string; level: number }> = [];
  let contentBuffer = '';

  for (const token of tokens) {
    if (token.type === 'heading') {
      // 직전 섹션의 contentBuffer를 summary로 저장 (첫 150자)
      if (nodes.length > 0 && contentBuffer.trim()) {
        nodes[nodes.length - 1].summary = contentBuffer.trim().slice(0, 150);
      }
      contentBuffer = '';

      const nodeId = `node-${nodes.length}`;
      const headingText = token.text || '';
      nodes.push({
        id: nodeId,
        heading: headingText,
        level: token.depth,
        summary: '',
        keywords: [],
      });

      // 스택 기반 부모-자식 에지 생성
      while (stack.length > 0 && stack[stack.length - 1].level >= token.depth) {
        stack.pop();
      }
      if (stack.length > 0) {
        edges.push({
          source: stack[stack.length - 1].id,
          target: nodeId,
          type: 'hierarchy',
        });
      }
      stack.push({ id: nodeId, level: token.depth });
    } else if (token.type === 'paragraph' || token.type === 'text') {
      contentBuffer += (contentBuffer ? ' ' : '') + (token.text || '');
    }
  }

  // 마지막 섹션 summary 저장
  if (nodes.length > 0 && contentBuffer.trim()) {
    nodes[nodes.length - 1].summary = contentBuffer.trim().slice(0, 150);
  }

  return { nodes, edges };
}

/**
 * elkjs를 사용하여 노드에 레이아웃 좌표를 계산.
 * 프론트엔드 elkLayout.js와 동일한 옵션 사용.
 *
 * [Flow: Step 1 (노드/에지를 ELK JSON 그래프로 변환) -> Step 2 (elk.layout 호출) -> Step 3 (좌표 매핑)]
 *
 * @param nodes 노드 배열
 * @param edges 에지 배열
 * @returns 좌표가 포함된 노드 배열
 */
async function _computeElkLayout(
  nodes: Array<{ id: string; heading: string; level: number }>,
  edges: Array<{ source: string; target: string }>,
): Promise<Array<{ id: string; x: number; y: number; width: number; height: number }>> {
  const elkNodes = nodes.map(n => ({
    id: n.id,
    width: 280,
    height: 80,
    layoutOptions: { 'elk.layered.spacing.nodeSelf': '0' },
  }));
  const elkEdges = edges.map(e => ({
    id: `e-${e.source}-${e.target}`,
    sources: [e.source],
    targets: [e.target],
  }));

  const graph = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'DOWN',
      'elk.spacing.nodeNode': '80',
      'elk.layered.spacing.nodeNodeBetweenLayers': '100',
    },
    children: elkNodes,
    edges: elkEdges,
  };

  const result = await elk.layout(graph);
  return (result.children || []).map((c: any) => ({
    id: c.id,
    x: c.x || 0,
    y: c.y || 0,
    width: c.width || 280,
    height: c.height || 80,
  }));
}

/**
 * 마크다운에서 지정한 헤딩의 라인 인덱스 범위를 찾는다.
 * _findSection과 유사하지만 라인 번호를 반환.
 *
 * [Flow: Step 1 (마크다운 라인 분할) -> Step 2 (헤딩 라인 검색) -> Step 3 (섹션 범위 계산)]
 *
 * @param markdown 마크다운 문자열
 * @param headingText 찾을 헤딩 텍스트
 * @returns { startLine, endLine, level } 또는 null
 */
function _findHeadingLineRange(
  markdown: string,
  headingText: string,
): { startLine: number; endLine: number; level: number } | null {
  const lines = markdown.split('\n');
  let startLine = -1;
  let level = 1;

  for (let i = 0; i < lines.length; i++) {
    const match = lines[i].match(/^(#{1,6})\s+(.+)$/);
    if (match && match[2].trim() === headingText.trim()) {
      startLine = i;
      level = match[1].length;
      break;
    }
  }

  if (startLine === -1) return null;

  let endLine = lines.length;
  for (let i = startLine + 1; i < lines.length; i++) {
    const match = lines[i].match(/^(#{1,6})\s+/);
    if (match && match[1].length <= level) {
      endLine = i;
      break;
    }
  }

  return { startLine, endLine, level };
}

/**
 * [Flow: Step 1 (context 파싱) -> Step 2 (드로잉/주석/노트/엣지/헤딩 도구 반환)]
 * 플로우 조작 도구 팩토리 — 기존 분석 도구 + 신규 조작 도구를 생성.
 *
 * @param context 에이전트 컨텍스트 (jobId, authHeaders 포함)
 * @returns 플로우 조작 도구 맵
 */
export function buildFlowTools(context: FlowToolContext) {
  const jobId = String(context.jobId || context.job_id || '');
  const authHeaders = context.authHeaders || {};

  // 드로잉/주석/노트/엣지 보류 변경사항 버퍼 — apply 패턴 (markdown.ts의 edits 버퍼와 동일)
  let pendingPaths: Array<Record<string, unknown>> | null = null;
  let pendingTextAnnotations: Array<Record<string, unknown>> | null = null;
  let pendingNoteNodes: Array<Record<string, unknown>> | null = null;
  let pendingCustomEdges: Array<Record<string, unknown>> | null = null;

  /**
   * 서버에서 현재 flow drawings를 로드하여 보류 버퍼를 초기화.
 * 아직 로드하지 않았다면 첫 조작 도구 호출 시 자동 로드.
   */
  async function ensureLoaded(): Promise<void> {
    if (pendingPaths !== null) return;
    const data = await proofApi.getFlowDrawings(jobId, authHeaders);
    pendingPaths = data?.paths ? [...data.paths] : [];
    pendingTextAnnotations = data?.text_annotations ? [...data.text_annotations] : [];
    pendingNoteNodes = data?.note_nodes ? [...data.note_nodes] : [];
    pendingCustomEdges = data?.custom_edges ? [...data.custom_edges] : [];
  }

  return {
    /* ============================================================
     * 기존 분석 도구 (읽기 전용)
     * ========================================================== */

    extract_flow_structure: tool({
      description:
        'Extract heading-based flow structure from the markdown document. Generate nodes and hierarchical edges through pure parsing without token consumption. Used for flow view rendering.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (optional if context jobId is used)'),
      }),
      execute: async ({ jobId: jid }) => {
        const id = jid || jobId;
        if (!id) return { nodes: [], edges: [], error: 'jobId is required' };

        const markdown = await proofApi.getMarkdown(id, authHeaders);
        const { nodes, edges } = _extractHeadingStructure(markdown);

        return { nodes, edges };
      },
    }),

    infer_flow_dependencies: tool({
      description:
        'Reorganize the extracted flow nodes into a logical tree structure. Infer parent-child edges in a tree form where each node has at most one parent using AI. Use the nodes array from extract_flow_structure as input.',
      inputSchema: z.object({
        nodes: z
          .array(
            z.object({
              id: z.string().describe('Node ID'),
              heading: z.string().describe('Heading text'),
              level: z.number().describe('Heading level (1-6)'),
              summary: z.string().optional().describe('Section summary'),
              keywords: z.array(z.string()).optional().describe('Key keywords'),
            }),
          )
          .describe('Array of nodes extracted by extract_flow_structure'),
      }),
      execute: async ({ nodes }) => {
        const compactNodes = nodes.map(n => ({
          id: n.id,
          heading: n.heading,
          level: n.level,
          summary: n.summary || '',
          keywords: n.keywords || [],
        }));

        return {
          nodes: compactNodes,
          instruction:
            'Analyze the provided nodes and organize them into a logical tree structure. Return a JSON array of edges: [{ source, target, type: "hierarchy", reason }]. CRITICAL: Each node must have AT MOST ONE parent — this is a tree, not a graph. The tree should reflect logical containment and prerequisite relationships, flowing from general/root concepts down to specific details. The root node(s) should have no parent. Include a "reason" field explaining why each parent-child relationship exists.',
        };
      },
    }),

    /* ============================================================
     * 레이아웃 도구 — 노드 위치 계산
     * ========================================================== */

    get_flow_layout: tool({
      description:
        'Extract heading nodes from markdown and compute layout coordinates with elkjs. Use as a coordinate reference when placing drawings/annotations/notes near nodes. Returns each node\'s id, heading, x, y, width, and height.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (optional if context jobId is used)'),
      }),
      execute: async ({ jobId: jid }) => {
        const id = jid || jobId;
        if (!id) return { nodes: [], error: 'jobId is required' };

        const markdown = await proofApi.getMarkdown(id, authHeaders);
        const { nodes, edges } = _extractHeadingStructure(markdown);
        const layoutedNodes = await _computeElkLayout(nodes, edges);

        return {
          nodes: nodes.map(n => {
            const layout = layoutedNodes.find(l => l.id === n.id);
            return {
              id: n.id,
              heading: n.heading,
              level: n.level,
              x: layout?.x || 0,
              y: layout?.y || 0,
              width: layout?.width || 280,
              height: layout?.height || 80,
            };
          }),
        };
      },
    }),

    /* ============================================================
     * 드로잉/주석 CRUD 도구
     * ========================================================== */

    get_flow_drawings: tool({
      description:
        'Retrieve all drawings (paths), text annotations, note nodes, and custom edges of the current flow view from the server. Use to check the current state before manipulation.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (optional if context jobId is used)'),
      }),
      execute: async ({ jobId: jid }) => {
        const id = jid || jobId;
        if (!id) return { error: 'jobId is required' };
        await ensureLoaded();
        return {
          paths: pendingPaths,
          text_annotations: pendingTextAnnotations,
          note_nodes: pendingNoteNodes,
          custom_edges: pendingCustomEdges,
        };
      },
    }),

    add_flow_shape: tool({
      description:
        'Add a shape (line/arrow/rectangle/circle) to the flow view canvas. Coordinates are in the flow coordinate system. Check node positions with get_flow_layout before placing. Must call save_flow_drawings to persist.',
      inputSchema: z.object({
        shapeType: z.enum(['line', 'arrow', 'rectangle', 'circle']).describe('Shape type'),
        x1: z.number().describe('Start x (flow coordinate system)'),
        y1: z.number().describe('Start y (flow coordinate system)'),
        x2: z.number().describe('End x (flow coordinate system)'),
        y2: z.number().describe('End y (flow coordinate system)'),
        strokeColor: z.string().optional().describe('Stroke color (hex, e.g., #6366f1)'),
        strokeWidth: z.number().optional().describe('Stroke width (1-20, default 4)'),
      }),
      execute: async ({ shapeType, x1, y1, x2, y2, strokeColor, strokeWidth }) => {
        await ensureLoaded();
        const d = createShapePath(x1, y1, x2, y2, shapeType);
        const newPath = {
          id: `shape-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          d,
          stroke: strokeColor || DEFAULT_STROKE_COLOR,
          strokeWidth: strokeWidth || DEFAULT_STROKE_WIDTH,
          type: 'shape',
          shapeType,
        };
        pendingPaths!.push(newPath);
        return { ok: true, path: newPath, total_paths: pendingPaths!.length };
      },
    }),

    add_flow_text_annotation: tool({
      description:
        'Add a text annotation to the flow view canvas. Coordinates are in the flow coordinate system. Check node positions with get_flow_layout before placing. Must call save_flow_drawings to persist.',
      inputSchema: z.object({
        text: z.string().describe('Annotation text'),
        x: z.number().describe('x coordinate (flow coordinate system)'),
        y: z.number().describe('y coordinate (flow coordinate system)'),
        color: z.string().optional().describe('Text color (hex, e.g., #6366f1)'),
        fontSize: z.number().optional().describe('Font size (default 14)'),
      }),
      execute: async ({ text, x, y, color, fontSize }) => {
        await ensureLoaded();
        const newAnnotation = {
          id: `text-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          x,
          y,
          text,
          fontSize: fontSize || DEFAULT_FONT_SIZE,
          color: color || DEFAULT_TEXT_COLOR,
        };
        pendingTextAnnotations!.push(newAnnotation);
        return { ok: true, annotation: newAnnotation, total_annotations: pendingTextAnnotations!.length };
      },
    }),

    delete_flow_drawing: tool({
      description:
        'Delete a specific drawing (path) or text annotation by ID. Check the ID with get_flow_drawings before use. Must call save_flow_drawings to persist.',
      inputSchema: z.object({
        id: z.string().describe('ID of the path or text annotation to delete'),
        kind: z.enum(['path', 'text']).describe('Target type to delete ("path" or "text")'),
      }),
      execute: async ({ id, kind }) => {
        await ensureLoaded();
        if (kind === 'path') {
          const before = pendingPaths!.length;
          pendingPaths = pendingPaths!.filter(p => p.id !== id);
          return { ok: true, deleted: before > pendingPaths!.length, remaining: pendingPaths!.length };
        } else {
          const before = pendingTextAnnotations!.length;
          pendingTextAnnotations = pendingTextAnnotations!.filter(a => a.id !== id);
          return { ok: true, deleted: before > pendingTextAnnotations!.length, remaining: pendingTextAnnotations!.length };
        }
      },
    }),

    clear_flow_drawings: tool({
      description:
        'Clear all drawings, text annotations, note nodes, and custom edges in the flow view. Must call save_flow_drawings to persist.',
      inputSchema: z.object({}),
      execute: async () => {
        await ensureLoaded();
        pendingPaths = [];
        pendingTextAnnotations = [];
        pendingNoteNodes = [];
        pendingCustomEdges = [];
        return { ok: true, cleared: true };
      },
    }),

    save_flow_drawings: tool({
      description:
        'Save all pending drawing/annotation/note/edge changes to the server (PUT). Returns the full changed state, and the frontend synchronizes with this result immediately. Must be called after every manipulation tool to persist.',
      inputSchema: z.object({}),
      execute: async () => {
        await ensureLoaded();
        const data = {
          paths: pendingPaths || [],
          text_annotations: pendingTextAnnotations || [],
          note_nodes: pendingNoteNodes || [],
          custom_edges: pendingCustomEdges || [],
        };
        const result = await proofApi.saveFlowDrawings(jobId, data, authHeaders);
        return {
          ok: true,
          saved: true,
          paths: result.paths,
          text_annotations: result.text_annotations,
          note_nodes: result.note_nodes,
          custom_edges: result.custom_edges,
        };
      },
    }),

    /* ============================================================
     * 노트 노드 CRUD 도구
     * ========================================================== */

    add_flow_note: tool({
      description:
        'Add a sticky note (note node) to the flow view. Coordinates are in the flow coordinate system. Check node positions with get_flow_layout before placing. Must call save_flow_drawings to persist.',
      inputSchema: z.object({
        text: z.string().describe('Note text'),
        x: z.number().describe('x coordinate (flow coordinate system)'),
        y: z.number().describe('y coordinate (flow coordinate system)'),
        width: z.number().optional().describe('Note width (default 200)'),
        height: z.number().optional().describe('Note height (default 80)'),
      }),
      execute: async ({ text, x, y, width, height }) => {
        await ensureLoaded();
        const newNote = {
          id: `note-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          x,
          y,
          text,
          width: width || 200,
          height: height || 80,
        };
        pendingNoteNodes!.push(newNote);
        return { ok: true, note: newNote, total_notes: pendingNoteNodes!.length };
      },
    }),

    update_flow_note: tool({
      description:
        'Edit the text or size of an existing note node. Check the note ID with get_flow_drawings before use. Must call save_flow_drawings to persist.',
      inputSchema: z.object({
        noteId: z.string().describe('ID of the note node to modify'),
        text: z.string().optional().describe('New note text'),
        width: z.number().optional().describe('New width'),
        height: z.number().optional().describe('New height'),
      }),
      execute: async ({ noteId, text, width, height }) => {
        await ensureLoaded();
        const note = pendingNoteNodes!.find(n => n.id === noteId);
        if (!note) return { ok: false, error: `Note ${noteId} not found` };
        if (text !== undefined) note.text = text;
        if (width !== undefined) note.width = width;
        if (height !== undefined) note.height = height;
        return { ok: true, note };
      },
    }),

    delete_flow_note: tool({
      description:
        'Delete a note node by ID. Check the note ID with get_flow_drawings before use. Must call save_flow_drawings to persist.',
      inputSchema: z.object({
        noteId: z.string().describe('ID of the note node to delete'),
      }),
      execute: async ({ noteId }) => {
        await ensureLoaded();
        const before = pendingNoteNodes!.length;
        pendingNoteNodes = pendingNoteNodes!.filter(n => n.id !== noteId);
        return { ok: true, deleted: before > pendingNoteNodes!.length, remaining: pendingNoteNodes!.length };
      },
    }),

    /* ============================================================
     * 커스텀 엣지 CRUD 도구
     * ========================================================== */

    add_flow_edge: tool({
      description:
        'Add a custom edge (connector) between two nodes. sourceNodeId and targetNodeId are from extract_flow_structure or get_flow_layout. Must call save_flow_drawings to persist.',
      inputSchema: z.object({
        sourceNodeId: z.string().describe('Source node ID'),
        targetNodeId: z.string().describe('Target node ID'),
        label: z.string().optional().describe('Edge label (optional)'),
      }),
      execute: async ({ sourceNodeId, targetNodeId, label }) => {
        await ensureLoaded();
        const newEdge = {
          id: `e-${sourceNodeId}-${targetNodeId}-${Date.now()}`,
          source: sourceNodeId,
          target: targetNodeId,
          label: label || '',
        };
        pendingCustomEdges!.push(newEdge);
        return { ok: true, edge: newEdge, total_edges: pendingCustomEdges!.length };
      },
    }),

    delete_flow_edge: tool({
      description:
        'Delete a custom edge by ID. Check the edge ID with get_flow_drawings before use. Must call save_flow_drawings to persist.',
      inputSchema: z.object({
        edgeId: z.string().describe('ID of the edge to delete'),
      }),
      execute: async ({ edgeId }) => {
        await ensureLoaded();
        const before = pendingCustomEdges!.length;
        pendingCustomEdges = pendingCustomEdges!.filter(e => e.id !== edgeId);
        return { ok: true, deleted: before > pendingCustomEdges!.length, remaining: pendingCustomEdges!.length };
      },
    }),

    /* ============================================================
     * 헤딩 노드 조작 도구 — 내부적으로 마크다운 편집
     * ========================================================== */

    add_flow_heading: tool({
      description:
        'Add a new heading to the markdown to create a new node in the flow view. If parentHeading is specified, it is added under that heading; otherwise at the end of the document. Do not mix with apply_edits because markdown is edited directly.',
      inputSchema: z.object({
        headingText: z.string().describe('New heading text'),
        level: z.number().min(1).max(6).describe('Heading level (1=H1, 2=H2, ... 6=H6)'),
        parentHeading: z.string().optional().describe('Parent heading text (insert at the end of this heading\'s section). If omitted, added at the end of the document'),
        content: z.string().optional().describe('Body content to add under the heading (markdown)'),
      }),
      execute: async ({ headingText, level, parentHeading, content }) => {
        if (!jobId) return { ok: false, error: 'jobId is required' };
        const markdown = await proofApi.getMarkdown(jobId, authHeaders);
        const prefix = '#'.repeat(level);
        const newSection = `\n\n${prefix} ${headingText}\n` + (content ? `\n${content}\n` : '');

        let updated: string;
        if (parentHeading) {
          const range = _findHeadingLineRange(markdown, parentHeading);
          if (!range) return { ok: false, error: `Parent heading "${parentHeading}" not found` };
          const lines = markdown.split('\n');
          lines.splice(range.endLine, 0, newSection);
          updated = lines.join('\n');
        } else {
          updated = markdown + newSection;
        }

        await proofApi.saveMarkdown(jobId, undefined, updated, authHeaders);
        return { ok: true, headingText, level, added: true };
      },
    }),

    delete_flow_heading: tool({
      description:
        'Delete the specified heading and its entire section from the markdown to remove the node from the flow view. Do not mix with apply_edits because markdown is edited directly.',
      inputSchema: z.object({
        headingText: z.string().describe('Heading text to delete'),
      }),
      execute: async ({ headingText }) => {
        if (!jobId) return { ok: false, error: 'jobId is required' };
        const markdown = await proofApi.getMarkdown(jobId, authHeaders);
        const range = _findHeadingLineRange(markdown, headingText);
        if (!range) return { ok: false, error: `Heading "${headingText}" not found` };

        const lines = markdown.split('\n');
        lines.splice(range.startLine, range.endLine - range.startLine);
        const updated = lines.join('\n');

        await proofApi.saveMarkdown(jobId, undefined, updated, authHeaders);
        return { ok: true, headingText, deleted: true };
      },
    }),

    rename_flow_heading: tool({
      description:
        'Change the heading text in the markdown to modify the title of the flow view node. Do not mix with apply_edits because markdown is edited directly.',
      inputSchema: z.object({
        oldHeadingText: z.string().describe('Current heading text'),
        newHeadingText: z.string().describe('New heading text'),
      }),
      execute: async ({ oldHeadingText, newHeadingText }) => {
        if (!jobId) return { ok: false, error: 'jobId is required' };
        const markdown = await proofApi.getMarkdown(jobId, authHeaders);
        const range = _findHeadingLineRange(markdown, oldHeadingText);
        if (!range) return { ok: false, error: `Heading "${oldHeadingText}" not found` };

        const lines = markdown.split('\n');
        const prefix = '#'.repeat(range.level);
        lines[range.startLine] = `${prefix} ${newHeadingText}`;
        const updated = lines.join('\n');

        await proofApi.saveMarkdown(jobId, undefined, updated, authHeaders);
        return { ok: true, oldHeadingText, newHeadingText, renamed: true };
      },
    }),

    move_flow_heading: tool({
      description:
        'Change the heading level to move the node\'s hierarchy position in the flow view. Do not mix with apply_edits because markdown is edited directly.',
      inputSchema: z.object({
        headingText: z.string().describe('Heading text to move'),
        newLevel: z.number().min(1).max(6).describe('New heading level (1=H1, 2=H2, ... 6=H6)'),
      }),
      execute: async ({ headingText, newLevel }) => {
        if (!jobId) return { ok: false, error: 'jobId is required' };
        const markdown = await proofApi.getMarkdown(jobId, authHeaders);
        const range = _findHeadingLineRange(markdown, headingText);
        if (!range) return { ok: false, error: `Heading "${headingText}" not found` };

        const lines = markdown.split('\n');
        const prefix = '#'.repeat(newLevel);
        lines[range.startLine] = `${prefix} ${headingText}`;
        const updated = lines.join('\n');

        await proofApi.saveMarkdown(jobId, undefined, updated, authHeaders);
        return { ok: true, headingText, newLevel, moved: true };
      },
    }),
  };
}
