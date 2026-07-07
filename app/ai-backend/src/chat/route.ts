// [Flow: Step 1 (POST 요청에서 messages/context/authHeaders 추출) -> Step 2 (system prompt 빌드)
//       -> Step 3 (streamText에 모델/메시지/도구 등록) -> Step 4 (UIMessage 스트림으로 변환하여 반환)]
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
import { buildModel } from '../lib/model.js';
import { buildAnnotationTools } from '../tools/annotations.js';
import { buildMarkdownTools } from '../tools/markdown.js';
import { buildSpreadsheetTools } from '../tools/spreadsheet.js';

/**
 * [Flow: Step 1 (context 수신) -> Step 2 (job_id, source_type, page, editor 등 추출)
 *       -> Step 3 (도구 사용 규칙을 포함한 system prompt 생성) -> Step 4 (반환)]
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

  return `You are PROOF Agent, an AI assistant that helps users manipulate PDF annotations, markdown editor content, and spreadsheets.

Current context:
- job_id: ${jobId}
- source_type: ${sourceType}
- current_page: ${currentPage}
- selected_file_index: ${selectedFileIndex}
- active_editor: ${activeEditor}

Available tool categories:
1. PDF annotation (only when source_type is pdf or docx/hwp preview):
   - search_text, get_elements, get_annotations, view_page, add_highlight, add_callout, update_annotation, remove_annotation, compare_elements, apply_annotations
2. Markdown editor (when active_editor is markdown):
   - get_section, get_table, replace_selection, insert_at, apply_edits
3. Spreadsheet (when active_editor is xlsxBasic or xlsxAdvanced):
   - get_sheet, update_cell, add_row, delete_row, apply_changes

Rules:
- Always use the provided tools to make changes; do not just describe them.
- For PDF annotations, only call apply_annotations when you are done adding/removing highlights/callouts.
- To inspect a PDF page visually, call view_page to get a vision analysis of the rendered page image (DPI is estimated from the page's embedded raster images; pass an explicit dpi between 150 and 300 only when needed).
- To modify existing annotations, first call get_annotations to list them, then call update_annotation with the annotation id.
- update_annotation immediately persists changes to storage; you do not need to call apply_annotations after it.
- For markdown edits, only call apply_edits when you are done with all replacements/insertions.
- For spreadsheet edits, only call apply_changes when you are done with all cell/row updates.
- If the user request is ambiguous, ask for clarification before calling tools.
- Respond in the same language as the user's request.
- Keep final summary concise.`;
}

/**
 * [Flow: Step 1 (요청 본문 파싱) -> Step 2 (도구 컨텍스트 생성) -> Step 3 (streamText 실행)
 *       -> Step 4 (UIMessage 스트림 반환)]
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
    },
    stopWhen: stepCountIs(5),
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
