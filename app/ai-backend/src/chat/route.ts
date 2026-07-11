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
import { compressToolResults, shouldCompress } from '../lib/llmlingua.js';
import { buildModel } from '../lib/model.js';
import { buildAnnotationTools } from '../tools/annotations.js';
import { createBrowserlessTools } from '../tools/browserless.js';
import { buildFlowTools } from '../tools/flow.js';
import { buildMarkdownTools } from '../tools/markdown.js';
import { createSandboxTools } from '../tools/sandbox.js';
import { buildSpreadsheetTools } from '../tools/spreadsheet.js';

// [Flow: maxOutputTokens — vLLM 기본값(128~256)은 툴콜 결과 분석에 부족하므로 8192로 설정]
const MAX_OUTPUT_TOKENS = 8192;

// [Flow: LLMLingua-2 압축 임계값 — 이전 스텝의 tool 결과 JSON이 이 값(문자 수)을 초과하면 압축]
// 동적 rate: 4000~8000자→0.5(2x), 8000~20000자→0.3(3x), 20000자+→0.2(5x) — Python 서비스가 자동 선택
const COMPRESSION_THRESHOLD_CHARS = 4000;

/**
 * [Flow: Step 1 (context 수신) -> Step 2 (job_id, source_type, page, editor 등 추출)
 *       -> Step 3 (도구 사용 규칙 + 도구 결과 분석 지시를 포함한 system prompt 생성) -> Step 4 (반환)]
 *
 * @param context 프론트엔드에서 전달된 에이전트 컨텍스트
 * @returns system prompt 문자열
 */
function buildSystemPrompt(context: Record<string, unknown>): string {
  const jobId = context.jobId || context.job_id || 'unknown';
  const sourceType = context.sourceType || context.source_type || 'unknown';
  const currentPage = context.currentPage || context.current_page || 1;
  const selectedFileIndex = context.selectedFileIndex ?? context.selected_file_index ?? 0;
  const activeEditor = context.activeEditor || context.active_editor || 'markdown';
  const approvalMode = context.approvalMode || 'ask';

  const basePrompt = `You are PROOF Agent, an AI assistant that helps users manipulate PDF annotations, markdown editor content, and spreadsheets.

Current context:
- job_id: ${jobId}
- source_type: ${sourceType}
- current_page: ${currentPage}
- selected_file_index: ${selectedFileIndex}
- active_editor: ${activeEditor}

Available tool categories:
1. PDF annotation (only when source_type is pdf or docx/hwp preview):
   - search_text, get_elements, get_annotations, read_job_json, view_page, add_highlight, add_callout, update_annotation, remove_annotation, compare_elements, apply_annotations, save_annotations
2. Markdown editor (when active_editor is markdown):
   - get_section, get_table, replace_selection, insert_at, apply_edits
3. Spreadsheet (when active_editor is xlsxBasic or xlsxAdvanced):
   - get_sheet, update_cell, add_row, delete_row, apply_changes
4. Sandbox (when user asks to run code or process files in isolation):
   - create_sandbox, execute_in_sandbox, read_sandbox_file, write_sandbox_file, list_sandbox_files, commit_sandbox_changes, get_sandbox_diff, collect_sandbox_results, destroy_sandbox
   - IMPORTANT: User-visible filenames are preserved in /workspace/original/. For example, if the user says "보고서.pdf", the file is at /workspace/original/보고서.pdf. Read /workspace/_file_mapping.json to see the full mapping of user filenames to sandbox paths. Do NOT use /workspace/input.pdf — use the original filename instead.
5. Web browsing (when user asks to capture or extract web content):
   - browse_web, convert_web_to_pdf, extract_web_text
6. Flow analysis (when user asks to visualize document structure or build a logical tree):
   - extract_flow_structure, infer_flow_dependencies

Rules:
- Always use the provided tools to make changes; do not just describe them.
- CRITICAL: Always read and analyze tool results before making the next tool call. Do NOT call another tool based on assumptions — use the actual data returned by the previous tool. If a tool returns an error, read the error message and adjust your approach accordingly.
- After calling a tool, summarize what you learned from its output before deciding the next step.
- For PDF annotations, only call apply_annotations when you are done adding/removing highlights/callouts.
- To inspect a PDF page visually, call view_page to get a vision analysis of the rendered page image (DPI is estimated from the page's embedded raster images; pass an explicit dpi between 150 and 300 only when needed).
- To read existing annotation JSON (full EmbedPDF AnnotationTransferItem[] structure with id, type, pageIndex, rect, color, contents, calloutLine, strokeColor), call read_job_json with kind="annotations". Use this to check exact annotation positions/structure before editing.
- To read other job result JSON, call read_job_json with kind="ocr_layout" | "extracted_files" | "annotated_pdf_files" | "job_meta".
- To get a quick annotation summary (id/type/page/color only), call get_annotations with summary_only=true.
- To create annotations directly from JSON (without using add_highlight/add_callout), call save_annotations with an EmbedPDF AnnotationTransferItem[] array. Use this when you need precise rect positions from view_page or read_job_json. Set merge=false to replace all existing annotations.
- For PDF text elements, use get_elements with an explicit page_no whenever possible. Without page_no, the backend may OCR the entire PDF which is very slow for large/image-based PDFs.
- When calling add_highlight or add_callout after get_elements(page_no), pass the same page_no to avoid re-scanning the whole PDF. If the page_no is omitted, the tool will still fall back to a full-document scan but it will be slower.
- To modify existing annotations, first call get_annotations or read_job_json(kind="annotations") to list them, then call update_annotation with the annotation id.
- update_annotation immediately persists changes to storage; you do not need to call apply_annotations after it.
- For markdown edits, only call apply_edits when you are done with all replacements/insertions.
- For spreadsheet edits, only call apply_changes when you are done with all cell/row updates.
- If the user request is ambiguous, ask for clarification before calling tools.
- Respond in the same language as the user's request.
- Keep final summary concise.`;

  // [Flow: Step 3.5 (승인 모드가 'ask'인 경우 — 도구 승인 대기 지시 추가)]
  if (approvalMode === 'ask') {
    return basePrompt + `

Tool approval:
- When a tool returns requires_approval: true in its output, STOP and wait for the user to approve or deny before proceeding with any further actions.
- Do NOT call apply_annotations, save_annotations, apply_edits, apply_changes, or any other persisting tool until the user has approved.
- If the user denies, undo the pending change (e.g. do not persist the removal) and acknowledge the denial.`;
  }

  return basePrompt;
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

  const result = streamText({
    model: buildModel() as any,
    system: buildSystemPrompt(context),
    messages: await convertToModelMessages(messages),
    tools: {
      ...buildAnnotationTools(toolContext),
      ...buildMarkdownTools(toolContext),
      ...buildSpreadsheetTools(toolContext),
      ...createSandboxTools(toolContext),
      ...createBrowserlessTools(),
      ...buildFlowTools(toolContext),
    },
    // [Flow: maxOutputTokens 8192 — vLLM 기본값(128~256)은 툴콜 결과 분석에 부족]
    maxOutputTokens: MAX_OUTPUT_TOKENS,
    stopWhen: stepCountIs(30),
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
    onStepFinish: ({ finishReason, usage, toolCalls, toolResults }) => {
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
