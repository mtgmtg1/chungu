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
        '수천 장 규모의 법률 문서에서 쟁점(issue), 원고(plaintiff), 피고(defendant), 증거(evidence) 노드와 이들 간의 논리적/인과적 관계를 GraphRAG 파이프라인으로 추출. 결과가 클 경우 자동으로 LLMLingua-2 압축. 추출 후 시각화/요약을 위해 save_flow_drawings 등 상태 업데이트 도구를 호출할 것.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (context의 jobId 사용 시 생략 가능)'),
        query: z.string().optional().describe('추출에 사용할 자연어 쿼리 (예: "계약 위반 쟁점과 관련 증거")'),
        threshold: z.number().min(0).max(1).optional().describe('노드/에지 포함 최소 관련도 임계값 (0.0~1.0, 기본값은 FastAPI에서 결정)'),
        maxDocs: z.number().int().min(1).optional().describe('처리할 최대 페이지(문서) 수 (제한이 필요할 때)'),
        context: z.string().optional().describe('프로젝트 주요/중요 사항에 대한 추가 맥락 (예: "대여금 반환 청구, A가 채권자, B가 채무자")'),
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
        '이미 추출된 e-Discovery 그래프의 관련도/신뢰도 임계값을 변경하여 노드와 에지를 재필터링. extract_ediscovery_graph 이후 그래프가 너무 많거나 적을 때 사용.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (context의 jobId 사용 시 생략 가능)'),
        threshold: z.number().min(0).max(1).describe('새 임계값 (0.0~1.0, 값이 클수록 엄격한 필터링)'),
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
        '법률 문서에서 법률 분야(legal_domain), 청구 원인(claim_type), 핵심 쟁점(issues), 입증 요건(legal_elements)을 추출. 에이전트가 사건 맥락을 판단하여 호출하며, 추가 힌트(claim_type_hint, additional_context)를 전달할 수 있다. 분석이 모호하면 search_text, extract_ediscovery_graph 등 다른 도구로 수집한 맥락을 additional_context에 담아 재호출할 것.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (context의 jobId 사용 시 생략 가능)'),
        claimTypeHint: z.string().optional().describe('에이전트가 판단한 청구 원인 힌트 (예: "손해배상", "대여금반환")'),
        additionalContext: z.string().optional().describe('에이전트가 수집한 추가 맥락 (예: e-Discovery 그래프 요약, 검색 결과)'),
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
