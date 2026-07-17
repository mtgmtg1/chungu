// [Flow: Step 1 (POST 요청에서 messages/context/authHeaders 추출) -> Step 2 (system prompt 빌드)
//       -> Step 3 (streamText에 모델/메시지/도구 등록 + maxOutputTokens 8192 + onStepFinish 로깅)
//       -> Step 4 (prepareStep에서 이전 스텝 메시지가 임계값 초과 시 LLMLingua-2 압축 적용)
//       -> Step 5 (UIMessage 스트림으로 변환하여 반환)]
// Vercel AI SDK 5.x의 streamText를 사용하는 핵심 채팅 엔드포인트.
// PDF 주석, 마크다운, 엑셀 조작 도구를 통합하여 멀티스텝 에이전트 실행을 제공한다.
import {
  convertToModelMessages,
  stepCountIs,
  streamText,
  type UIMessage,
} from 'ai';
import type { Request, Response } from 'express';
import { getAuthHeaders } from '../lib/auth.js';
import * as proofApi from '../lib/proof-api.js';
import { compressToolResults, shouldCompress } from '../lib/llmlingua.js';
import { buildIntentHint } from '../lib/intent-synonyms.js';
import { buildModel } from '../lib/model.js';
import { buildAnnotationTools } from '../tools/annotations.js';
import { createBrowserlessTools } from '../tools/browserless.js';
import { buildEdiscoveryTools } from '../tools/ediscovery.js';
import { buildFlowTools } from '../tools/flow.js';
import { buildMapperTools } from '../tools/mapper.js';
import { buildMarkdownTools } from '../tools/markdown.js';
import { createSandboxTools } from '../tools/sandbox.js';
import { buildSpreadsheetTools } from '../tools/spreadsheet.js';

// [Flow: maxOutputTokens — vLLM 기본값(128~256)은 툴콜 결과 분석에 부족하므로 8192로 설정]
const MAX_OUTPUT_TOKENS = 8192;

// [Flow: AI 에이전트 기본 최대 step 수 — 사용자 설정이 없을 때 100을 사용]
const DEFAULT_AGENT_MAX_STEPS = 100;

// [Flow: LLMLingua-2 압축 임계값 — 이전 스텝의 tool 결과 JSON이 이 값(문자 수)을 초과하면 압축]
// 동적 rate: 4000~8000자→0.5(2x), 8000~20000자→0.3(3x), 20000자+→0.2(5x) — Python 서비스가 자동 선택
const COMPRESSION_THRESHOLD_CHARS = 4000;

/**
 * [Flow: Step 1 (context와 마지막 사용자 메시지 수신) -> Step 2 (job_id, source_type, page, editor 등 추출)
 *       -> Step 3 (의도 정규화 힌트 생성) -> Step 4 (도구 사용 규칙 + 카테고리 설명을 포함한 system prompt 생성) -> Step 5 (반환)]
 *
 * @param context 프론트엔드에서 전달된 에이전트 컨텍스트
 * @param userMessage 마지막 사용자 발화 (비개발자 용어를 매핑하기 위한 힌트 생성에 사용, 선택적)
 * @returns system prompt 문자열
 */
function buildSystemPrompt(context: Record<string, unknown>, userMessage?: string): string {
  const jobId = context.jobId || context.job_id || 'unknown';
  const sourceType = context.sourceType || context.source_type || 'unknown';
  const currentPage = context.currentPage || context.current_page || 1;
  const selectedFileIndex = context.selectedFileIndex ?? context.selected_file_index ?? 0;
  const activeEditor = context.activeEditor || context.active_editor || 'markdown';
  const approvalMode = context.approvalMode || 'ask';
  const intentHint = buildIntentHint(userMessage);

  const basePrompt = `You are PROOF Agent, an AI assistant that helps users manipulate PDF annotations, markdown editor content, and spreadsheets.

${intentHint}Current context:
- job_id: ${jobId}
- source_type: ${sourceType}
- current_page: ${currentPage}
- selected_file_index: ${selectedFileIndex}
- active_editor: ${activeEditor} (markdown = document/report editor; xlsxBasic/xlsxAdvanced = spreadsheet)

Available tool categories:
1. PDF annotation (only when source_type is pdf or docx/hwp preview):
   - search_text, get_elements, get_annotations, read_job_json, view_page, add_text_highlight, add_text_callout, update_annotation, remove_annotation, compare_elements, apply_annotations
2. Markdown editor / report & document editor (when active_editor is markdown):
   - Users may describe this as: 보고서, 문서, 글쓰기, 메모, 메모장, 보고서 작성, 문서 정리, 요약, 마크다운, 에디터.
   - Tools: get_section, get_table, replace_selection, insert_at, apply_edits
3. Spreadsheet (when active_editor is xlsxBasic or xlsxAdvanced):
   - get_sheet, update_cell, add_row, delete_row, apply_changes
4. Sandbox / code execution environment (when user asks to run code, scripts, or process files in isolation):
   - Users may describe this as: 코드 실행, 파이썬, 스크립트, 프로그램, 계산, 코딩, 샌드박스, 돌리기, 테스트.
   - create_sandbox, execute_in_sandbox, read_sandbox_file, write_sandbox_file, list_sandbox_files, commit_sandbox_changes, get_sandbox_diff, collect_sandbox_results, destroy_sandbox
   - IMPORTANT: User-visible filenames are preserved in /workspace/original/. For example, if the user says "report.pdf", the file is at /workspace/original/report.pdf. Read /workspace/_file_mapping.json to see the full mapping of user filenames to sandbox paths. Do NOT use /workspace/input.pdf — use the original filename instead.
5. Web browsing (when user asks to capture or extract web content):
   - browse_web, convert_web_to_pdf, extract_web_text
6. Flow analysis (when user asks to visualize document structure or build a logical tree):
   - extract_flow_structure, infer_flow_dependencies
7. Flow view manipulation (when user asks to draw, annotate, add notes, connect nodes, or restructure headings in the flow view):
   - Layout: get_flow_layout (get node positions for placing drawings near nodes)
   - Drawing/annotation: get_flow_drawings, add_flow_shape (line/arrow/rectangle/circle), add_flow_text_annotation, delete_flow_drawing, clear_flow_drawings
   - Note nodes: add_flow_note, update_flow_note, delete_flow_note
   - Custom edges: add_flow_edge, delete_flow_edge
   - Heading nodes: add_flow_heading, delete_flow_heading, rename_flow_heading, move_flow_heading
   - Persistence: save_flow_drawings (MUST call after drawing/note/edge changes to persist)
   - IMPORTANT: Always call get_flow_layout first to get node positions before placing drawings or notes. Coordinates are in the flow coordinate system.
   - IMPORTANT: Always call save_flow_drawings after any drawing/note/edge changes. Without it, changes are lost.
   - Heading tools (add/delete/rename/move_flow_heading) directly edit the markdown and are persisted immediately. Do NOT mix with apply_edits.
8. e-Discovery Graph Analysis (when user asks to extract legal issues, evidence, parties, or build a case graph from large document sets):
   - extract_ediscovery_graph: run the GraphRAG pipeline to extract issue/plaintiff/defendant/evidence nodes and their relationships
   - adjust_graph_threshold: re-filter the extracted graph by changing the relevance/confidence threshold
   - analyze_legal_profile: infer legal domain, claim type, key issues, and required legal elements from the document. The agent decides when to call this and can pass collected context as additionalContext.
   - IMPORTANT: After extraction, persist or summarize the results by calling save_flow_drawings (e.g., add note nodes for key issues/evidence) or another state-update tool.
   - The graph data contract is: nodes have id, type (issue|plaintiff|defendant|evidence), and data.label/data.page; edges have id, source, target, and type.

9. Issue-Claim-Evidence Tree Mapper (when user asks to build a case theory, map evidence to claims/issues, or calculate proof progress for a claim):
   - analyze_legal_profile: agent-driven inference of claim_type, key issues, and opposing claims. Use this first if the claim type is unknown.
   - get_legal_issue_tree: extract 3~5 issues, each with 2+ opposing claims (e.g. plaintiff vs defendant, prosecutor vs accused), and supporting evidence via vLLM. The LLM cross-validates the issue-claim-evidence chain against the document. Returns mapped_evidence with a reason field. If e-Discovery evidence nodes exist, they are used as evidence sources.
   - save_issue_tree_mappings: persist the completed 3-level tree (claim_type + issues with claims + mapped evidence and relationship reasons) to Supabase. overall_progress_percent is recomputed server-side.
   - get_issue_tree_mappings: retrieve the saved 3-level tree state (for restore or progress check).
   - Legacy 2-level tools also exist: get_legal_elements, save_element_mappings, get_element_mappings. Prefer the 3-level tree tools for new case theory work.
   - Workflow: first call extract_ediscovery_graph to get evidence nodes, then analyze_legal_profile (or get_legal_issue_tree if claim_type is already known) to generate issue/claim slots, then save_issue_tree_mappings with evidence mapped to each claim. The data contract is: {claim_type, overall_progress_percent, cross_validated, issues: [{id, name, description, claims: [{id, party, name, description, mapped_evidence: [{evidence_id, text_snippet, source_doc, reason}]}]}]}. The reason field must describe the concrete factual/legal relationship between the evidence and the claim. Each issue should contain opposing claims (e.g. plaintiff and defendant positions).

Rules:
- Always use the provided tools to make changes; do not just describe them.
- CRITICAL: Always read and analyze tool results before making the next tool call. Do NOT call another tool based on assumptions — use the actual data returned by the previous tool. If a tool returns an error, read the error message and adjust your approach accordingly.
- After calling a tool, summarize what you learned from its output before deciding the next step.
- For PDF annotations, only call apply_annotations when you are done adding/removing highlights/callouts.
- OLD TOOLS REMOVED: add_highlight, add_callout, and save_annotations are no longer available. Calling them will fail. Always use add_text_highlight/add_text_callout for new highlights/callouts.
- To inspect a PDF page visually, call view_page to get a vision analysis. The output is text-only and does NOT contain coordinates or bounding boxes. Pass an explicit dpi between 150 and 300 only when needed.
- To read existing annotation JSON, call read_job_json with kind="annotations" or get_annotations. Coordinate fields (rect, segmentRects, calloutLine, bbox_pdf) are REDACTED. Use the returned id, type, page_no, color, and comment only for editing or deleting.
- To read other job result JSON, call read_job_json with kind="ocr_layout" | "extracted_files" | "annotated_pdf_files" | "job_meta".
- To create highlight/callout annotations, use add_text_highlight/add_text_callout with the exact text string you want to highlight or point to. The backend searches the PDF text layer and resolves the bounding box/segmentRects automatically. You MUST NOT compute or pass rect/bbox manually.
- If you are unsure of the exact text, call search_text first to verify the wording. search_text, get_elements, and compare_elements return text for verification only; their coordinates are intentionally hidden, so do not try to construct annotations from them.
- For PDF text elements, use get_elements with an explicit page_no whenever possible. Without page_no, the backend may OCR the entire PDF which is very slow for large/image-based PDFs.
- When calling add_text_highlight or add_text_callout, you may pass the same page_no to limit the search and avoid a full-document scan.
- To modify existing annotations, first call get_annotations or read_job_json(kind="annotations") to list them, then call update_annotation with the annotation id.
- update_annotation immediately persists changes to storage; you do not need to call apply_annotations after it.
- For markdown edits, only call apply_edits when you are done with all replacements/insertions.
- For spreadsheet edits, only call apply_changes when you are done with all cell/row updates.
- If the user request is ambiguous, ask for clarification before calling tools.
- Respond in the same language as the user's request.
- Keep final summary concise.
- Sandbox: Any file created or modified inside the sandbox by execute_in_sandbox, convert_document, transcribe_audio, or process_image is NOT visible to the user until you call collect_sandbox_results. Always call collect_sandbox_results after generating files, and before destroy_sandbox. Files must be under /workspace/agent_output/, /workspace/extracted/, or /workspace/annotations/ to be collected. write_sandbox_file and download_file automatically collect results.`;

  // [Flow: Step 3.5 (승인 모드가 'ask'인 경우 — 도구 승인 대기 지시 추가)]
  if (approvalMode === 'ask') {
    return basePrompt + `

Tool approval:
- When a tool returns requires_approval: true in its output, STOP and wait for the user to approve or deny before proceeding with any further actions.
- Do NOT call apply_annotations, apply_edits, apply_changes, or any other persisting tool until the user has approved.
- If the user denies, undo the pending change (e.g. do not persist the removal) and acknowledge the denial.`;
  }

  return basePrompt;
}

/**
 * [Flow: Step 1 (UIMessage 목록 역순 탐색) -> Step 2 (role=user 메시지 발견)
 *       -> Step 3 (텍스트 content 또는 text parts 추출) -> Step 4 (문자열 반환)]
 *
 * Vercel AI SDK 5.x는 content 문자열 또는 parts 배열을 모두 지원할 수 있으므로
 * 둘 다 처리한다. 추출된 텍스트는 buildIntentHint로 전달되어 비개발자 용어를 매핑한다.
 *
 * @param messages UIMessage 목록
 * @returns 마지막 사용자 발화 텍스트 (없으면 undefined)
 */
function _getLastUserText(messages: UIMessage[]): string | undefined {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i] as any;
    if (message.role !== 'user') continue;

    if (typeof message.content === 'string') {
      return message.content;
    }

    const parts = message.parts ?? [];
    const textParts = parts.filter((part: any) => part?.type === 'text');
    const text = textParts.map((part: any) => part.text).join('');
    if (text) return text;
  }

  return undefined;
}

/**
 * [Flow: Step 1 (요청 본문 파싱) -> Step 2 (도구 컨텍스트 생성) -> Step 3 (streamText 실행)
 *       -> Step 4 (prepareStep에서 이전 스텝 tool 결과 압축) -> Step 5 (UIMessage 스트림 반환)]
 *
 * @param req Express 요청
 * @param res Express 응답
 */
export async function chatHandler(req: Request, res: Response) {
  const body = (req.body || {}) as {
    messages?: UIMessage[];
    context?: Record<string, unknown>;
  };
  const messages = body.messages || [];
  const userMessageText = _getLastUserText(messages);
  // [Flow: Step 1 (body.context 우선) -> Step 2 (messages의 system message에서 JSON context 추출)
  //       -> Step 3 (두 출처 병합)]
  const contextFromBody = body.context || {};
  const contextFromSystem = _extractContextFromMessages(messages);
  const context = { ...contextFromSystem, ...contextFromBody };
  const authHeaders = getAuthHeaders(req);

  const toolContext = {
    ...context,
    authHeaders,
  };

  // [Flow: 사용자별 에이전트 최대 step 수 및 사용자 ID 조회 -> 실패 시 기본값 사용]
  let agentMaxSteps = DEFAULT_AGENT_MAX_STEPS;
  let userId: string | null = null;
  try {
    const me = await proofApi.getMe(authHeaders);
    userId = me.user_id || null;
    agentMaxSteps = Math.max(1, Math.min(1000, Number(me.agent_max_steps) || DEFAULT_AGENT_MAX_STEPS));
  } catch (e) {
    console.error('[chatHandler] failed to fetch user agent_max_steps, using default 100:', e);
  }

  const result = streamText({
    model: buildModel() as any,
    system: buildSystemPrompt(context, userMessageText),
    messages: await convertToModelMessages(messages),
    tools: {
      ...buildAnnotationTools(toolContext),
      ...buildMarkdownTools(toolContext),
      ...buildSpreadsheetTools(toolContext),
      ...createSandboxTools(toolContext),
      ...createBrowserlessTools(),
      ...buildFlowTools(toolContext),
      ...buildEdiscoveryTools(toolContext),
      ...buildMapperTools(toolContext),
    },
    // [Flow: maxOutputTokens 8192 — vLLM 기본값(128~256)은 툴콜 결과 분석에 부족]
    maxOutputTokens: MAX_OUTPUT_TOKENS,
    stopWhen: stepCountIs(agentMaxSteps),
    // [Flow: prepareStep — 이전 스텝의 tool 결과가 임계값 초과 시 LLMLingua-2 로 압축하여 전달]
    prepareStep: async ({ steps, stepNumber, messages: stepMessages }) => {
      // [Flow: 첫 스텝이거나 이전 스텝이 없으면 압축 불필요]
      if (stepNumber === 0 || steps.length === 0) {
        return {};
      }

      const lastStep = steps[steps.length - 1];
      const toolResults = lastStep?.toolResults || [];

      // [Flow: tool 결과가 없으면 압축 불필요]
      if (toolResults.length === 0) {
        return {};
      }

      // [Flow: tool 결과 JSON을 문자열로 직렬화하여 압축 대상 크기 계산]
      const toolResultJson = JSON.stringify(
        toolResults.map((tr: any) => ({
          toolName: tr.toolName,
          output: tr.output,
        })),
      );

      // [Flow: 임계값 미만이면 압축 불필요]
      if (!shouldCompress(toolResultJson, COMPRESSION_THRESHOLD_CHARS)) {
        return {};
      }

      console.log(
        `[chatHandler] step=${stepNumber} toolResults size=${toolResultJson.length} chars — compressing with LLMLingua-2`,
      );

      // [Flow: LLMLingua-2 로 tool 결과 압축 — 실패 시 원본 사용 (폴백)]
      const compressed = await compressToolResults(toolResultJson);

      if (compressed !== toolResultJson) {
        console.log(
          `[chatHandler] step=${stepNumber} compressed: ${toolResultJson.length} -> ${compressed.length} chars (${Math.round((1 - compressed.length / toolResultJson.length) * 100)}% reduction)`,
        );
        // [Flow: 압축된 tool 결과를 시스템 메시지로 주입 — 모델이 압축된 데이터를 사용하도록 안내]
        return {
          messages: [
            ...stepMessages,
            {
              role: 'system' as const,
              content: `[Previous tool results were compressed by LLMLingua-2 for context efficiency. Use this compressed data:\n${compressed}`,
            },
          ],
        };
      }

      return {};
    },
    // [Flow: onStepFinish — 각 스텝 종료 시 toolCalls/toolResults/usage 로깅]
    onStepFinish: async ({ finishReason, usage, toolCalls, toolResults }) => {
      const toolCallNames = toolCalls?.map((tc: any) => tc.toolName).join(', ') || 'none';
      const toolResultCount = toolResults?.length || 0;
      const inputTokens = usage?.inputTokens ?? '?';
      const outputTokens = usage?.outputTokens ?? '?';
      console.log(
        `[chatHandler] finishReason=${finishReason} ` +
          `tools=[${toolCallNames}] toolResults=${toolResultCount} ` +
          `tokens(in=${inputTokens}, out=${outputTokens})`,
      );
    },
    // [Flow: onFinish — 에이전트 실행 종료 후 총 스텝 수를 집계해 비동기로 포인트 차감]
    onFinish: async ({ steps }) => {
      const totalSteps = steps.length;
      console.log(`[chatHandler] agent finished — totalSteps=${totalSteps} userId=${userId}`);
      if (!userId || totalSteps <= 0) {
        return;
      }
      try {
        await proofApi.spendAgentSteps(userId, totalSteps, 'AI 에이전트 스텝 사용');
        console.log(`[chatHandler] agent step credits spent — steps=${totalSteps}`);
      } catch (e) {
        console.error('[chatHandler] agent step credit spend failed:', e);
      }
    },
  });

  return result.toUIMessageStreamResponse();
}

/**
 * [Flow: Step 1 (UIMessage 목록 수신) -> Step 2 (role=system 메시지 찾기)
 *       -> Step 3 (content에서 JSON context 파싱) -> Step 4 (context 객체 반환)]
 *
 * 프론트엔드가 initial system message에 context를 담아 보낼 때 사용한다.
 *
 * @param messages UIMessage 목록
 * @returns 추출된 context
 */
function _extractContextFromMessages(messages: UIMessage[]): Record<string, unknown> {
  for (const message of messages) {
    if (message.role === 'system') {
      // UIMessage 5.x는 content 대신 parts 배열을 사용한다.
      const textParts = (message as any).parts?.filter((p: any) => p.type === 'text') || [];
      const content = textParts.map((p: any) => p.text).join('');
      const match = content.match(/Current PROOF context: ({.*})/);
      if (match) {
        try {
          return JSON.parse(match[1]);
        } catch {
          return {};
        }
      }
    }
  }
  return {};
}
