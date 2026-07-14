// [Flow: Step 1 (context에서 job_id, page_num, authHeaders 추출) -> Step 2 (임시 편집 상태 관리)
//       -> Step 3 (마크다운 섹션/표/교체/삽입/저장 도구 생성) -> Step 4 (도구 객체 반환)]
// 마크다운 에디터 조작용 서버 사이드 도구. 최종 편집은 apply_edits에서 FastAPI로 저장한다.
import { tool } from 'ai';
import { z } from 'zod';
import type { AuthHeaders } from '../lib/auth.js';
import * as proofApi from '../lib/proof-api.js';

interface MarkdownContext {
  jobId?: string;
  job_id?: string;
  pageNum?: number;
  page_num?: number;
  authHeaders?: AuthHeaders;
  [key: string]: unknown;
}

interface Edit {
  type: 'replace' | 'insert';
  old_text?: string;
  position?: string;
  new_text: string;
}

/**
 * [Flow: Step 1 (context 파싱) -> Step 2 (편집 버퍼 초기화) -> Step 3 (도구 반환)]
 *
 * @param context 에이전트 컨텍스트
 * @returns 마크다운 에디터 조작 도구 맵
 */
export function buildMarkdownTools(context: MarkdownContext) {
  const jobId = String(context.jobId || context.job_id || '');
  const pageNum = context.pageNum !== undefined ? Number(context.pageNum)
    : context.page_num !== undefined ? Number(context.page_num)
    : undefined;
  const authHeaders = context.authHeaders || {};

  const edits: Edit[] = [];

  return {
    get_section: tool({
      description: 'Extract the section with the specified heading from the markdown.',
      inputSchema: z.object({
        heading: z.string().describe('Heading of the section to find'),
      }),
      execute: async ({ heading }) => {
        const markdown = await proofApi.getMarkdown(jobId, authHeaders);
        const section = _findSection(markdown, heading);
        return { heading, content: section };
      },
    }),

    get_table: tool({
      description: 'Extract the Nth table from the markdown.',
      inputSchema: z.object({
        table_index: z.number().describe('0-based table index'),
      }),
      execute: async ({ table_index }) => {
        const markdown = await proofApi.getMarkdown(jobId, authHeaders);
        const tables = _findTables(markdown);
        return { table_index, content: tables[table_index] || '' };
      },
    }),

    replace_selection: tool({
      description: 'Replace the selected text with new markdown.',
      inputSchema: z.object({
        old_text: z.string().describe('Existing text to replace'),
        new_text: z.string().describe('New markdown'),
      }),
      execute: async ({ old_text, new_text }) => {
        edits.push({ type: 'replace', old_text, new_text });
        return { ok: true, type: 'replace', old_text, new_text };
      },
    }),

    insert_at: tool({
      description: 'Insert markdown at the specified position.',
      inputSchema: z.object({
        position: z.string().describe('"cursor" | "end" | "beginning" | heading text'),
        new_text: z.string().describe('Markdown to insert'),
      }),
      execute: async ({ position, new_text }) => {
        edits.push({ type: 'insert', position, new_text });
        return { ok: true, type: 'insert', position, new_text };
      },
    }),

    apply_edits: tool({
      description: 'Save the markdown edits made so far to FastAPI.',
      inputSchema: z.object({}),
      execute: async () => {
        if (edits.length === 0) {
          return { saved: false, reason: 'No pending edits' };
        }
        let markdown = await proofApi.getMarkdown(jobId, authHeaders);
        for (const edit of edits) {
          if (edit.type === 'replace' && edit.old_text) {
            markdown = markdown.replace(edit.old_text, edit.new_text);
          } else if (edit.type === 'insert') {
            if (edit.position === 'end') {
              markdown += '\n\n' + edit.new_text;
            } else if (edit.position === 'beginning') {
              markdown = edit.new_text + '\n\n' + markdown;
            } else if (edit.position === 'cursor') {
              // cursor 위치는 프론트엔드에서 별도로 처리해야 하므로 end로 폴백
              markdown += '\n\n' + edit.new_text;
            } else {
              // heading 제목 뒤에 삽입
              markdown = markdown.replace(edit.position || '', `${edit.position}\n\n${edit.new_text}`);
            }
          }
        }
        await proofApi.saveMarkdown(jobId, pageNum, markdown, authHeaders);
        return { saved: true, edit_count: edits.length };
      },
    }),
  };
}

/**
 * [Flow: Step 1 (마크다운과 제목 수신) -> Step 2 (해당 제목 이후 섹션 추출) -> Step 3 (반환)]
 *
 * @param markdown 마크다운
 * @param heading 섹션 제목
 * @returns 섹션 내용
 */
function _findSection(markdown: string, heading: string): string {
  const lines = markdown.split('\n');
  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim().replace(/^#+\s*/, '') === heading.trim()) {
      start = i;
      break;
    }
  }
  if (start === -1) return '';
  const level = lines[start].match(/^(#+)/)?.[1].length || 1;
  let end = lines.length;
  for (let i = start + 1; i < lines.length; i++) {
    const match = lines[i].match(/^(#+)/);
    if (match && match[1].length <= level) {
      end = i;
      break;
    }
  }
  return lines.slice(start, end).join('\n');
}

/**
 * [Flow: Step 1 (마크다운 수신) -> Step 2 (표를 파싱) -> Step 3 (표 문자열 목록 반환)]
 *
 * @param markdown 마크다운
 * @returns 표 문자열 목록
 */
function _findTables(markdown: string): string[] {
  const tables: string[] = [];
  const lines = markdown.split('\n');
  let buffer: string[] = [];
  for (const line of lines) {
    if (line.trim().startsWith('|')) {
      buffer.push(line);
    } else if (buffer.length > 0) {
      tables.push(buffer.join('\n'));
      buffer = [];
    }
  }
  if (buffer.length > 0) tables.push(buffer.join('\n'));
  return tables;
}
