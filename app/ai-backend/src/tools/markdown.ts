// [Flow: Step 1 (context에서 job_id, 파일 인덱스, authHeaders 추출)
//       -> Step 2 (마크다운 working state 초기화)
//       -> Step 3 (읽기/편집/저장 도구 객체 생성) -> Step 4 (도구 맵 반환)]
// 마크다운 에디터 조작용 서버 사이드 도구. 최종 편집은 apply_edits 에서 FastAPI 로 저장한다.

import { tool } from 'ai';
import { z } from 'zod';
import type { AuthHeaders } from '../lib/auth.js';
import * as proofApi from '../lib/proof-api.js';
import { sanitizeMarkdownForLLM } from '../lib/markdown-sanitizer.js';
import {
  DEFAULT_CHUNK_LIMIT,
  createNodiomDoc,
  extractFileMarkdown,
  fetchMarkdown,
  findTablesInMarkdown,
  getHeadingsFromDoc,
  getSectionMarkdown,
  insertTextAt,
  readChunk,
  replaceTextFuzzy,
  resolveFileIndex,
  splitMarkdownByFileMarkers,
} from '../lib/markdown-utils.js';

interface MarkdownContext {
  jobId?: string;
  job_id?: string;
  pageNum?: number;
  page_num?: number;
  selectedFileIndex?: number;
  selected_file_index?: number;
  currentPage?: number;
  current_page?: number;
  authHeaders?: AuthHeaders;
  [key: string]: unknown;
}

// [Flow: Step 1 (context 파싱) -> Step 2 (편집 상태 초기화) -> Step 3 (도구 반환)]
//
// @param context 에이전트 컨텍스트
// @returns 마크다운 에디터 조작 도구 맵
export function buildMarkdownTools(context: MarkdownContext) {
  const jobId = String(context.jobId || context.job_id || '');
  const authHeaders = context.authHeaders || {};
  const selectedFileIndex = context.selectedFileIndex ?? context.selected_file_index;
  const currentPage = context.currentPage ?? context.current_page;
  const requestedPageNum = context.pageNum !== undefined ? Number(context.pageNum)
    : context.page_num !== undefined ? Number(context.page_num)
    : undefined;

  let workingMarkdown = '';
  let currentFileIndex = 0;
  let markdownLoaded = false;
  let hasChanges = false;

  // [Flow: FastAPI 에서 전체 markdown 조회 -> 파일 마커 분할 -> 선택 파일 로드]
  async function loadFile(requestedPageNo?: number) {
    const combinedMarkdown = await fetchMarkdown(jobId, authHeaders);
    const parts = splitMarkdownByFileMarkers(combinedMarkdown);
    const totalFiles = Math.max(1, parts.length);
    const fileIndex = resolveFileIndex(
      totalFiles,
      requestedPageNo ?? requestedPageNum,
      selectedFileIndex,
      currentPage,
    );

    workingMarkdown = parts.length > 0
      ? extractFileMarkdown(combinedMarkdown, fileIndex)
      : combinedMarkdown;
    currentFileIndex = fileIndex;
    markdownLoaded = true;
    hasChanges = false;
  }

  // [Flow: working markdown 이 로드되지 않았으면 먼저 로드]
  async function ensureLoaded(requestedPageNo?: number) {
    if (!markdownLoaded || requestedPageNo !== undefined) {
      await loadFile(requestedPageNo);
    }
  }

  return {
    get_markdown: tool({
      description: 'Read the selected file from the markdown document/report editor (보고서, 문서, 글쓰기, 메모장).',
      inputSchema: z.object({
        page_no: z.number().optional().describe('Optional 1-based file/page number to read'),
      }),
      execute: async ({ page_no }) => {
        await ensureLoaded(page_no);
        return {
          content: sanitizeMarkdownForLLM(workingMarkdown),
          file_index: currentFileIndex,
          page_num: currentFileIndex + 1,
        };
      },
    }),

    get_page: tool({
      description: 'Read a specific file/page from the markdown document/report editor.',
      inputSchema: z.object({
        page_no: z.number().optional().describe('Optional 1-based file/page number (defaults to selected file)'),
      }),
      execute: async ({ page_no }) => {
        await ensureLoaded(page_no);
        return {
          content: sanitizeMarkdownForLLM(workingMarkdown),
          file_index: currentFileIndex,
          page_num: currentFileIndex + 1,
        };
      },
    }),

    get_headings: tool({
      description: 'Get the outline (headings) of the selected markdown file/document.',
      inputSchema: z.object({
        page_no: z.number().optional().describe('Optional 1-based file/page number'),
      }),
      execute: async ({ page_no }) => {
        await ensureLoaded(page_no);
        const doc = createNodiomDoc(workingMarkdown);
        const headings = getHeadingsFromDoc(doc);
        return { headings };
      },
    }),

    get_section: tool({
      description: 'Extract the section with the specified heading from the markdown document/report editor (fuzzy match supported).',
      inputSchema: z.object({
        heading: z.string().describe('Heading of the section to find'),
        parent_heading: z.string().optional().describe('Parent heading to disambiguate'),
        page_no: z.number().optional().describe('Optional 1-based file/page number'),
      }),
      execute: async ({ heading, parent_heading, page_no }) => {
        await ensureLoaded(page_no);
        const doc = createNodiomDoc(workingMarkdown);
        const result = getSectionMarkdown(doc, heading, parent_heading);

        if ('error' in result) {
          return { error: result.error, suggestions: result.suggestions };
        }

        return {
          content: sanitizeMarkdownForLLM(result.content),
          resolved_heading: result.headingInfo.heading,
          full_path: result.headingInfo.fullPath,
        };
      },
    }),

    get_table: tool({
      description: 'Extract the Nth table from the markdown report/document editor (fuzzy heading supported).',
      inputSchema: z.object({
        table_index: z.number().describe('0-based table index'),
        heading: z.string().optional().describe('Heading of the section containing the table'),
        parent_heading: z.string().optional().describe('Parent heading to disambiguate'),
        page_no: z.number().optional().describe('Optional 1-based file/page number'),
      }),
      execute: async ({ table_index, heading, parent_heading, page_no }) => {
        await ensureLoaded(page_no);
        const result = findTablesInMarkdown(workingMarkdown, table_index, heading, parent_heading);

        if (result.error) {
          return { content: '', error: result.error };
        }

        return { content: sanitizeMarkdownForLLM(result.table || '') };
      },
    }),

    read_first_chunk: tool({
      description: 'Read the first chunk of the selected markdown file (Tiptap-style streaming read).',
      inputSchema: z.object({
        limit: z.number().optional().describe(`Maximum characters per chunk (default ${DEFAULT_CHUNK_LIMIT})`),
        page_no: z.number().optional().describe('Optional 1-based file/page number'),
      }),
      execute: async ({ limit, page_no }) => {
        await ensureLoaded(page_no);
        const chunk = readChunk(workingMarkdown, 'first', limit ?? DEFAULT_CHUNK_LIMIT, 'next');
        return {
          chunk: sanitizeMarkdownForLLM(chunk.chunk),
          start: chunk.start,
          end: chunk.end,
          next_cursor: chunk.nextCursor,
          has_more: chunk.hasMore,
        };
      },
    }),

    read_next_chunk: tool({
      description: 'Read the next chunk of the selected markdown file from the given cursor.',
      inputSchema: z.object({
        cursor: z.number().describe('Cursor returned by previous chunk'),
        limit: z.number().optional().describe(`Maximum characters per chunk (default ${DEFAULT_CHUNK_LIMIT})`),
        page_no: z.number().optional().describe('Optional 1-based file/page number'),
      }),
      execute: async ({ cursor, limit, page_no }) => {
        await ensureLoaded(page_no);
        const chunk = readChunk(workingMarkdown, cursor, limit ?? DEFAULT_CHUNK_LIMIT, 'next');
        return {
          chunk: sanitizeMarkdownForLLM(chunk.chunk),
          start: chunk.start,
          end: chunk.end,
          next_cursor: chunk.nextCursor,
          has_more: chunk.hasMore,
        };
      },
    }),

    read_previous_chunk: tool({
      description: 'Read the previous chunk of the selected markdown file from the given cursor.',
      inputSchema: z.object({
        cursor: z.number().describe('Cursor returned by previous chunk'),
        limit: z.number().optional().describe(`Maximum characters per chunk (default ${DEFAULT_CHUNK_LIMIT})`),
        page_no: z.number().optional().describe('Optional 1-based file/page number'),
      }),
      execute: async ({ cursor, limit, page_no }) => {
        await ensureLoaded(page_no);
        const chunk = readChunk(workingMarkdown, cursor, limit ?? DEFAULT_CHUNK_LIMIT, 'previous');
        return {
          chunk: sanitizeMarkdownForLLM(chunk.chunk),
          start: chunk.start,
          end: chunk.end,
          previous_cursor: chunk.previousCursor,
          has_more: chunk.hasMore,
        };
      },
    }),

    replace_text: tool({
      description: 'Replace existing text in the markdown editor with new markdown using fuzzy matching (old_text/new_text).',
      inputSchema: z.object({
        old_text: z.string().describe('Existing text to replace'),
        new_text: z.string().describe('New markdown'),
        page_no: z.number().optional().describe('Optional 1-based file/page number'),
      }),
      execute: async ({ old_text, new_text, page_no }) => {
        await ensureLoaded(page_no);
        const result = replaceTextFuzzy(workingMarkdown, old_text, new_text);

        if (!result.success) {
          return {
            success: false,
            message: 'old_text not found or could not be replaced. Use get_markdown/read_chunk to verify the text.',
          };
        }

        workingMarkdown = result.markdown;
        hasChanges = true;
        return { success: true };
      },
    }),

    insert_text: tool({
      description: 'Insert markdown at the specified position in the document/report editor (beginning, end, or heading).',
      inputSchema: z.object({
        position: z.string().describe('"beginning" | "end" | "cursor" | heading text'),
        new_text: z.string().describe('Markdown to insert'),
        page_no: z.number().optional().describe('Optional 1-based file/page number'),
      }),
      execute: async ({ position, new_text, page_no }) => {
        await ensureLoaded(page_no);
        const doc = createNodiomDoc(workingMarkdown);
        const result = insertTextAt(workingMarkdown, position, new_text, doc);

        if (!result.success) {
          return { success: false, error: result.error || 'Failed to insert text' };
        }

        workingMarkdown = result.markdown;
        hasChanges = true;
        return { success: true };
      },
    }),

    apply_edits: tool({
      description: 'Save the markdown edits made so far to the document/report editor.',
      inputSchema: z.object({}),
      execute: async () => {
        if (!hasChanges) {
          return { saved: false, reason: 'No pending edits' };
        }

        await proofApi.saveMarkdown(jobId, currentFileIndex + 1, workingMarkdown, authHeaders);
        hasChanges = false;
        return { saved: true, file_index: currentFileIndex, page_num: currentFileIndex + 1 };
      },
    }),
  };
}
