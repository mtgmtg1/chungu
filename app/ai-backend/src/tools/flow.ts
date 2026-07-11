// [Flow: Step 1 (context에서 job_id, authHeaders 추출) -> Step 2 (마크다운에서 헤딩 트리 추출)
//       -> Step 3 (골격 노드 압축 JSON 생성) -> Step 4 (LLM으로 트리 구조 에지 추론) -> Step 5 (도구 객체 반환)]
// 플로우 뷰용 서버 사이드 도구. 마크다운 문서의 헤딩 구조를 추출하고
// AI로 논리적 트리 구조를 분석하여 React Flow 부모-자식 에지 데이터를 생성.
import { tool } from 'ai';
import { z } from 'zod';
import { marked } from 'marked';
import type { AuthHeaders } from '../lib/auth.js';
import * as proofApi from '../lib/proof-api.js';

interface FlowToolContext {
  jobId?: string;
  job_id?: string;
  authHeaders?: AuthHeaders;
  [key: string]: unknown;
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
 * [Flow: Step 1 (context 파싱) -> Step 2 (도구 반환)]
 * 플로우 분석 도구 팩토리 — extract_flow_structure와 infer_flow_dependencies를 생성.
 *
 * @param context 에이전트 컨텍스트 (jobId, authHeaders 포함)
 * @returns 플로우 분석 도구 맵
 */
export function buildFlowTools(context: FlowToolContext) {
  const jobId = String(context.jobId || context.job_id || '');
  const authHeaders = context.authHeaders || {};

  return {
    extract_flow_structure: tool({
      description:
        '마크다운 문서에서 헤딩 기반 플로우 구조를 추출. 토큰 소모 없이 순수 파싱으로 노드와 계층 에지를 생성. 플로우 뷰 렌더링에 사용.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (context의 jobId 사용 시 생략 가능)'),
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
        '추출된 플로우 노드를 논리적 트리 구조로 재구성. 각 노드가 최대 한 개의 부모를 갖는 트리 형태의 부모-자식 에지를 AI로 추론. extract_flow_structure로 얻은 nodes 배열을 입력으로 사용.',
      inputSchema: z.object({
        nodes: z
          .array(
            z.object({
              id: z.string().describe('노드 ID'),
              heading: z.string().describe('헤딩 텍스트'),
              level: z.number().describe('헤딩 레벨 (1-6)'),
              summary: z.string().optional().describe('섹션 요약'),
              keywords: z.array(z.string()).optional().describe('핵심 키워드'),
            }),
          )
          .describe('extract_flow_structure로 추출된 노드 배열'),
      }),
      execute: async ({ nodes }) => {
        // LLM이 노드를 논리적 트리로 재구성하도록 지시.
        // 이 도구는 노드 배열을 반환하고, 실제 LLM 추론은 에이전트의 streamText 컨텍스트에서 수행됨.
        // 도구 자체는 데이터를 정규화하여 반환하고, 에이전트가 다음 스텝에서 분석하도록 함.
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
  };
}
