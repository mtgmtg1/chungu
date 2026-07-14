// [Flow: Step 1 (context에서 job_id, authHeaders 추출)
//       -> Step 2 (FastAPI e-Discovery GraphRAG 엔드포인트 호출)
//       -> Step 3 (대용량 Graph JSON이 4000자 초과 시 LLMLingua-2 압축)
//       -> Step 4 (도구 객체 반환)]
// e-Discovery GraphRAG 파이프라인 제어 도구. 수천 장의 법률 문서에서
// 쟁점(issue), 원고(plaintiff), 피고(defendant), 증거(evidence) 노드와 관계를 추출하고,
// 관련도 임계값을 조정하여 그래프를 재필터링.
import { tool } from 'ai';
import { z } from 'zod';
import type { AuthHeaders } from '../lib/auth.js';
import { compressToolResults, shouldCompress } from '../lib/llmlingua.js';
import * as proofApi from '../lib/proof-api.js';

interface EdiscoveryToolContext {
  jobId?: string;
  job_id?: string;
  authHeaders?: AuthHeaders;
  [key: string]: unknown;
}

interface EdiscoveryMetrics {
  total_docs: number;
  processed_chunks: number;
  threshold: number;
  anomalies_detected?: number;
}

interface GraphNode {
  id: string;
  type: string;
  parentId?: string;
  data: {
    label: string;
    page?: number;
    confidence?: number;
    entity?: string;
    date?: string;
    summary?: string;
    issue?: string;
  };
}

interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  data?: { conflict_reason?: string; [key: string]: unknown };
}

interface EdiscoveryGraphResponse {
  job_id: string;
  ediscovery_metrics: EdiscoveryMetrics;
  graph_data: { nodes: GraphNode[]; edges: GraphEdge[] };
}

// [Flow: 도구 결과 직렬화 임계값 — LLMLingua-2 압축 기준 4000자]
const TOOL_RESULT_COMPRESSION_THRESHOLD = 4000;

/**
 * [Flow: Step 1 (Graph JSON 응답 수신) -> Step 2 (JSON 문자열 직렬화 및 길이 확인)
 *       -> Step 3 (4000자 이하면 원본 반환) -> Step 4 (초과 시 LLMLingua-2 압축)
 *       -> Step 5 (요약 + 압축본 반환)]
 *
 * e-Discovery 추출 결과가 4000자를 초과하면 LLMLingua-2로 동적 압축.
 * 압축된 결과는 토큰 효율이 높아져 maxOutputTokens 8192 환경에서도 안정적으로 전달.
 * 압축 실패 시 원본을 그대로 반환.
 *
 * @param response FastAPI에서 반환된 Graph JSON
 * @returns 원본 응답 또는 요약 + 압축본
 */
async function _maybeCompressGraphResponse(
  response: EdiscoveryGraphResponse,
): Promise<EdiscoveryGraphResponse | Record<string, unknown>> {
  const jsonText = JSON.stringify(response);
  if (!shouldCompress(jsonText, TOOL_RESULT_COMPRESSION_THRESHOLD)) {
    return response;
  }

  const compressed = await compressToolResults(jsonText);

  // [Flow: 압축 실패 또는 오히려 커진 경우 원본 반환]
  if (compressed === jsonText || compressed.length >= jsonText.length) {
    return response;
  }

  // [Flow: 모델이 개요를 파악할 수 있도록 핵심 요약 생성]
  const nodes = response.graph_data?.nodes || [];
  const edges = response.graph_data?.edges || [];
  const sampleLabels = nodes.slice(0, 15).map((n) => n.data?.label || n.id);

  return {
    job_id: response.job_id,
    ediscovery_metrics: response.ediscovery_metrics,
    graph_summary: {
      node_count: nodes.length,
      edge_count: edges.length,
      node_type_counts: nodes.reduce<Record<string, number>>((acc, n) => {
        acc[n.type] = (acc[n.type] || 0) + 1;
        return acc;
      }, {}),
      sample_node_labels: sampleLabels,
    },
    compressed_graph_data: compressed,
    compression_meta: {
      was_compressed: true,
      original_length: jsonText.length,
      compressed_length: compressed.length,
      reduction_percent: Math.round((1 - compressed.length / jsonText.length) * 100),
    },
  };
}

/**
 * [Flow: Step 1 (context 파싱) -> Step 2 (extract/adjust 도구 생성) -> Step 3 (도구 맵 반환)]
 *
 * e-Discovery GraphRAG 도구 팩토리.
 *
 * @param context 에이전트 컨텍스트 (jobId, authHeaders 포함)
 * @returns e-Discovery 도구 맵
 */
export function buildEdiscoveryTools(context: EdiscoveryToolContext) {
  const jobId = String(context.jobId || context.job_id || '');
  const authHeaders = context.authHeaders || {};

  return {
    extract_ediscovery_graph: tool({
      description:
        'Extract issue, plaintiff, defendant, and evidence nodes and their logical/causal relationships from legal documents at a scale of thousands of pages using the GraphRAG pipeline. If the result is large, it is automatically compressed with LLMLingua-2. After extraction, call state-update tools such as save_flow_drawings for visualization/summarization.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (optional if context jobId is used)'),
        query: z.string().optional().describe('Natural language query to use for extraction (e.g., "evidence related to contract breach issue")'),
        threshold: z.number().min(0).max(1).optional().describe('Minimum relevance threshold for including nodes/edges (0.0-1.0, default is determined by FastAPI)'),
        maxDocs: z.number().int().min(1).optional().describe('Maximum number of pages/documents to process (when a limit is needed)'),
        context: z.string().optional().describe('Additional context about important project matters (e.g., "loan repayment claim, A is creditor, B is debtor")'),
      }),
      execute: async ({ jobId: jid, query, threshold, maxDocs, context }) => {
        const id = jid || jobId;
        if (!id) return { error: 'jobId is required' };

        try {
          const response = await proofApi.extractEdiscoveryGraph(
            id,
            { query, threshold, max_docs: maxDocs, context },
            authHeaders,
          );
          // 동시 요청으로 인해 processing 상태가 반환되면 압축하지 않고 그대로 전달
          if ((response as any).status === 'processing') {
            return response;
          }
          return await _maybeCompressGraphResponse(response);
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error(`[extract_ediscovery_graph] job=${id} failed: ${msg}`);
          return { error: `e-Discovery graph extraction failed: ${msg}` };
        }
      },
    }),

    adjust_graph_threshold: tool({
      description:
        'Change the relevance/confidence threshold of the already extracted e-Discovery graph to re-filter nodes and edges. Use after extract_ediscovery_graph when the graph has too many or too few nodes.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (optional if context jobId is used)'),
        threshold: z.number().min(0).max(1).describe('New threshold (0.0-1.0, larger values mean stricter filtering)'),
      }),
      execute: async ({ jobId: jid, threshold }) => {
        const id = jid || jobId;
        if (!id) return { error: 'jobId is required' };

        try {
          const response = await proofApi.adjustGraphThreshold(id, threshold, authHeaders);
          return await _maybeCompressGraphResponse(response);
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error(`[adjust_graph_threshold] job=${id} failed: ${msg}`);
          return { error: `Graph threshold adjustment failed: ${msg}` };
        }
      },
    }),

    analyze_legal_profile: tool({
      description:
        'Extract legal domain, claim type, key issues, and required legal elements from legal documents. The agent calls this to judge the case context and can pass additional hints (claim_type_hint, additional_context). If the analysis is ambiguous, collect context with other tools such as search_text or extract_ediscovery_graph and re-call with additional_context.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (optional if context jobId is used)'),
        claimTypeHint: z.string().optional().describe('Hint for claim type determined by the agent (e.g., "damages", "loan repayment")'),
        additionalContext: z.string().optional().describe('Additional context collected by the agent (e.g., e-Discovery graph summary, search results)'),
      }),
      execute: async ({ jobId: jid, claimTypeHint, additionalContext }) => {
        const id = jid || jobId;
        if (!id) return { error: 'jobId is required' };

        try {
          const response = await proofApi.analyzeLegalProfile(
            id,
            { claimTypeHint, additionalContext },
            authHeaders,
          );
          return response;
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error(`[analyze_legal_profile] job=${id} failed: ${msg}`);
          return { error: `Legal profile analysis failed: ${msg}` };
        }
      },
    }),
  };
}
