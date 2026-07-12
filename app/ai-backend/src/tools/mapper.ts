// [Flow: Step 1 (context에서 job_id, authHeaders 추출)
//       -> Step 2 (FastAPI Evidence-to-Element Mapper 엔드포인트 호출)
//       -> Step 3 (도구 객체 반환)]
// 요건 사실 기반 증거 퍼즐 매퍼 도구. 청구 원인별 법적 요건사실을 추출하고,
// 추출된 증거(evidence) 노드를 요건사실 슬롯에 매핑한 퍼즐 상태를 저장/조회.
import { tool } from 'ai';
import { z } from 'zod';
import type { AuthHeaders } from '../lib/auth.js';
import * as proofApi from '../lib/proof-api.js';

interface MapperToolContext {
  jobId?: string;
  job_id?: string;
  authHeaders?: AuthHeaders;
  [key: string]: unknown;
}

/**
 * [Flow: Step 1 (context 파싱) -> Step 2 (get/save/get 도구 생성) -> Step 3 (도구 맵 반환)]
 *
 * Evidence-to-Element Mapper 도구 팩토리.
 *
 * @param context 에이전트 컨텍스트 (jobId, authHeaders 포함)
 * @returns 매퍼 도구 맵
 */
export function buildMapperTools(context: MapperToolContext) {
  const jobId = String(context.jobId || context.job_id || '');
  const authHeaders = context.authHeaders || {};

  return {
    get_legal_elements: tool({
      description:
        '청구 원인(예: 사기죄, 대여금반환, 횡령)에 따른 법적 요건사실 3~5개를 vLLM으로 추출. 빈 슬롯(mapped_evidence:[])이 포함된 퍼즐 매퍼 스키마를 반환. 같은 claim_type 재요청 시 캐시 반환.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (context의 jobId 사용 시 생략 가능)'),
        claimType: z.string().describe('청구 원인 (예: "사기죄", "대여금반환", "횡령")'),
      }),
      execute: async ({ jobId: jid, claimType }) => {
        const id = jid || jobId;
        if (!id) return { error: 'jobId is required' };
        if (!claimType || !claimType.trim()) return { error: 'claimType is required' };

        try {
          const response = await proofApi.getLegalElements(id, claimType.trim(), authHeaders);
          return response;
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error(`[get_legal_elements] job=${id} claimType=${claimType} failed: ${msg}`);
          return { error: `Legal elements extraction failed: ${msg}` };
        }
      },
    }),

    save_element_mappings: tool({
      description:
        '요건사실 퍼즐 매퍼의 완성된 상태(청구 원인, 요건사실 목록, 각 요건에 매핑된 증거)를 Supabase jobs 테이블에 영속화. overall_progress_percent는 서버에서 재계산. 프론트엔드 동기화용으로 저장된 전체 상태를 반환.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (context의 jobId 사용 시 생략 가능)'),
        claimType: z.string().describe('청구 원인'),
        elements: z.array(z.object({
          id: z.string().describe('요건사실 ID (예: "element_1")'),
          name: z.string().describe('요건사실 명칭'),
          description: z.string().describe('요건사실 설명'),
          mapped_evidence: z.array(z.object({
            evidence_id: z.string().describe('e-Discovery 그래프의 evidence 노드 ID'),
            text_snippet: z.string().describe('증거 텍스트 요약'),
            source_doc: z.string().describe('출처 문서/페이지 (예: "갑 제3호증", "P.5")'),
          })).describe('해당 요건에 매핑된 증거 목록'),
        })).describe('요건사실 슬롯 목록'),
      }),
      execute: async ({ jobId: jid, claimType, elements }) => {
        const id = jid || jobId;
        if (!id) return { error: 'jobId is required' };

        try {
          const mappings = { claim_type: claimType, overall_progress_percent: 0, elements };
          const response = await proofApi.saveElementMappings(id, mappings as any, authHeaders);
          return response;
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error(`[save_element_mappings] job=${id} failed: ${msg}`);
          return { error: `Element mappings save failed: ${msg}` };
        }
      },
    }),

    get_element_mappings: tool({
      description:
        '저장된 요건사실 퍼즐 매핑 상태를 조회. 페이지 새로고침 후 복원이나 현재 매핑 진행도 확인에 사용. 저장된 상태가 없으면 빈 스키마 반환.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (context의 jobId 사용 시 생략 가능)'),
      }),
      execute: async ({ jobId: jid }) => {
        const id = jid || jobId;
        if (!id) return { error: 'jobId is required' };

        try {
          const response = await proofApi.getElementMappings(id, authHeaders);
          return response;
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error(`[get_element_mappings] job=${id} failed: ${msg}`);
          return { error: `Element mappings fetch failed: ${msg}` };
        }
      },
    }),
  };
}
