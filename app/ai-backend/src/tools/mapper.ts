// [Flow: Step 1 (context에서 job_id, authHeaders 추출)
//       -> Step 2 (FastAPI 주장-증거 매퍼 엔드포인트 호출)
//       -> Step 3 (도구 객체 반환)]
// 주장(Claim) 기반 증거 퍼즐 매퍼 도구. 청구 원인별 법적 주장을 추출하고,
// 추출된 증거(evidence) 노드를 주장 슬롯에 매핑하며, LLM이 주장-증거 관계(reason)를 기록.
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
        'Extract 3-5 legal claims (required facts) by claim type (e.g., fraud, loan repayment, embezzlement) using vLLM. If e-Discovery evidence nodes exist, analyze the claim-evidence relationship (reason) and map them. Returns cached result for repeated claim_type requests.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (optional if context jobId is used)'),
        claimType: z.string().describe('Claim type (e.g., "fraud", "loan repayment", "embezzlement")'),
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
        'Persist the completed state of the claim-evidence puzzle mapper (claim type, claim list, evidence mapped to each claim and its relationship reason) to the Supabase jobs table. overall_progress_percent is recomputed on the server. Returns the full saved state for frontend synchronization.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (optional if context jobId is used)'),
        claimType: z.string().describe('Claim type'),
        elements: z.array(z.object({
          id: z.string().describe('Claim ID (e.g., "claim_1")'),
          name: z.string().describe('Claim name'),
          description: z.string().describe('Claim description'),
          mapped_evidence: z.array(z.object({
            evidence_id: z.string().describe('Evidence node ID from the e-Discovery graph'),
            text_snippet: z.string().describe('Evidence text summary'),
            source_doc: z.string().describe('Source document/page (e.g., "Plaintiff Exhibit 3", "P.5")'),
            reason: z.string().describe('The concrete relationship by which this evidence supports the claim (identified by the LLM)'),
          })).describe('List of evidence mapped to this claim'),
        })).describe('List of claim slots'),
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
        'Retrieve the saved claim-evidence puzzle mapping state. Use for restore after page refresh or to check current mapping progress. Returns an empty schema if no saved state exists.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (optional if context jobId is used)'),
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

    get_legal_issue_tree: tool({
      description:
        'Extract a 3-level issue → claim → evidence tree by claim type (e.g., fraud, loan repayment, embezzlement) using vLLM. Cross-validate with e-Discovery evidence nodes and document text. Returns cached result for repeated claim_type requests.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (optional if context jobId is used)'),
        claimType: z.string().describe('Claim type (e.g., "fraud", "loan repayment", "embezzlement")'),
      }),
      execute: async ({ jobId: jid, claimType }) => {
        const id = jid || jobId;
        if (!id) return { error: 'jobId is required' };
        if (!claimType || !claimType.trim()) return { error: 'claimType is required' };

        try {
          const response = await proofApi.getLegalIssueTree(id, claimType.trim(), authHeaders);
          return response;
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error(`[get_legal_issue_tree] job=${id} claimType=${claimType} failed: ${msg}`);
          return { error: `Issue tree extraction failed: ${msg}` };
        }
      },
    }),

    save_issue_tree_mappings: tool({
      description:
        'Persist the completed state of the issue-claim-evidence 3-level tree mapper (claim type, issue list, opposing claims for each issue, evidence mapped to each claim and its relationship reason) to the Supabase jobs table. overall_progress_percent is recomputed on the server.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (optional if context jobId is used)'),
        claimType: z.string().describe('Claim type'),
        issues: z.array(z.object({
          id: z.string().describe('Issue ID (e.g., "issue_1")'),
          name: z.string().describe('Issue name'),
          description: z.string().describe('Issue description'),
          claims: z.array(z.object({
            id: z.string().describe('Claim ID (e.g., "claim_1")'),
            party: z.string().describe('Opposing party (e.g., "plaintiff", "defendant", "prosecutor", "accused")'),
            name: z.string().describe('Claim name'),
            description: z.string().describe('Claim description'),
            mapped_evidence: z.array(z.object({
              evidence_id: z.string().describe('Evidence node ID from the e-Discovery graph'),
              text_snippet: z.string().describe('Evidence text summary'),
              source_doc: z.string().describe('Source document/page (e.g., "Plaintiff Exhibit 3", "P.5")'),
              reason: z.string().describe('The concrete relationship by which this evidence supports the claim (cross-validated by the LLM)'),
            })).describe('List of evidence mapped to this claim'),
          })).describe('List of opposing claims belonging to this issue'),
        })).describe('List of issues'),
      }),
      execute: async ({ jobId: jid, claimType, issues }) => {
        const id = jid || jobId;
        if (!id) return { error: 'jobId is required' };

        try {
          const tree = { claim_type: claimType, overall_progress_percent: 0, cross_validated: false, issues };
          const response = await proofApi.saveIssueTreeMappings(id, tree as any, authHeaders);
          return response;
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error(`[save_issue_tree_mappings] job=${id} failed: ${msg}`);
          return { error: `Issue tree mappings save failed: ${msg}` };
        }
      },
    }),

    get_issue_tree_mappings: tool({
      description:
        'Retrieve the saved issue-claim-evidence 3-level tree mapping state. Use for restore after page refresh or to check current mapping progress. Returns an empty schema if no saved state exists.',
      inputSchema: z.object({
        jobId: z.string().optional().describe('Job ID (optional if context jobId is used)'),
      }),
      execute: async ({ jobId: jid }) => {
        const id = jid || jobId;
        if (!id) return { error: 'jobId is required' };

        try {
          const response = await proofApi.getIssueTreeMappings(id, authHeaders);
          return response;
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err);
          console.error(`[get_issue_tree_mappings] job=${id} failed: ${msg}`);
          return { error: `Issue tree mappings fetch failed: ${msg}` };
        }
      },
    }),
  };
}
