// [Flow: Step 1 (global.fetch mock 설정)
//       -> Step 2 (buildMarkdownTools 호출)
//       -> Step 3 (읽기/편집/저장 도구의 happy path 와 에러 케이스 검증)]
// app/ai-backend/src/tools/markdown.ts 의 buildMarkdownTools 를 검증하는 통합 테스트.

import { describe, it, beforeEach, afterEach, mock } from 'node:test';
import assert from 'node:assert/strict';
import { buildMarkdownTools } from '../markdown.js';

// [Flow: 두 파일을 포함한 결합 markdown fixture]
const combinedMarkdown = `<!-- Page 1 -->
# File 1

File one content.

## Subsection

Details one.

<!-- Page 2 -->
# File 2

File two content.

## Section A

Details two.

| Name | Age |
| --- | --- |
| Kim | 25 |
`;

let savedCalls: Array<{ pageNum: number | undefined; markdown: string }> = [];
let originalFetch: typeof fetch;

// [Flow: fetch mock 생성 -> GET /preview 는 fixture, PATCH/PUT 은 저장 기록]
function createMockFetch() {
  return mock.fn(async (url: string | URL, options?: RequestInit) => {
    const urlString = url.toString();

    if (urlString.includes('/preview')) {
      return new Response(JSON.stringify({ markdown: combinedMarkdown }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }

    if (urlString.includes('/result')) {
      const bodyText = options?.body ? String(options.body) : '{}';
      const parsed = JSON.parse(bodyText) as any;
      const match = urlString.match(/\/result\/pages\/(\d+)$/);
      const pageNum = match ? Number(match[1]) : undefined;
      savedCalls.push({ pageNum, markdown: parsed.markdown || '' });
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }

    return new Response(JSON.stringify({}), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  }) as unknown as typeof fetch;
}

// [Flow: 각 테스트 전 global.fetch 를 mock 으로 교체, 후 복원]
beforeEach(() => {
  savedCalls = [];
  originalFetch = global.fetch;
  global.fetch = createMockFetch();
});

afterEach(() => {
  global.fetch = originalFetch;
});

describe('buildMarkdownTools', () => {
  it('get_markdown 은 selectedFileIndex 기준으로 파일 markdown 을 반환한다', async () => {
    const tools = buildMarkdownTools({
      jobId: 'job-1',
      selectedFileIndex: 0,
    } as any) as any;

    const result = (await tools.get_markdown.execute({})) as any;
    assert.ok(result.content.includes('# File 1'));
    assert.ok(!result.content.includes('# File 2'));
    assert.equal(result.file_index, 0);
  });

  it('get_page(page_no) 는 지정 파일을 반환하고 current file 을 변경한다', async () => {
    const tools = buildMarkdownTools({
      jobId: 'job-1',
      selectedFileIndex: 0,
    } as any) as any;

    const result = (await tools.get_page.execute({ page_no: 2 })) as any;
    assert.ok(result.content.includes('# File 2'));
    assert.ok(!result.content.includes('# File 1'));
    assert.equal(result.file_index, 1);
  });

  it('get_headings 는 outline 을 반환한다', async () => {
    const tools = buildMarkdownTools({
      jobId: 'job-1',
      selectedFileIndex: 0,
    } as any) as any;

    const result = (await tools.get_headings.execute({})) as any;
    assert.ok(Array.isArray(result.headings));
    assert.ok(result.headings.some((h: any) => h.heading === 'File 1'));
    assert.ok(result.headings.some((h: any) => h.heading === 'Subsection'));
  });

  it('get_section 은 fuzzy heading 매칭으로 섹션을 반환한다', async () => {
    const tools = buildMarkdownTools({
      jobId: 'job-1',
      selectedFileIndex: 1,
    } as any) as any;

    const result = (await tools.get_section.execute({ heading: 'Section A' })) as any;
    assert.ok(result.content.includes('Details two'));
    assert.equal(result.resolved_heading, 'Section A');
  });

  it('get_table 은 page_no 가 지정된 파일의 표를 반환한다', async () => {
    const tools = buildMarkdownTools({
      jobId: 'job-1',
      selectedFileIndex: 0,
    } as any) as any;

    const result = (await tools.get_table.execute({ table_index: 0, page_no: 2 })) as any;
    assert.ok(result.content.includes('Kim'));
    assert.ok(result.content.includes('|'));
  });

  it('read_first_chunk 와 read_next_chunk 를 연달아 호출할 수 있다', async () => {
    const tools = buildMarkdownTools({
      jobId: 'job-1',
      selectedFileIndex: 0,
    } as any) as any;

    const first = (await tools.read_first_chunk.execute({ limit: 20 })) as any;
    assert.equal(first.start, 0);
    assert.ok(typeof first.next_cursor === 'number');

    const next = (await tools.read_next_chunk.execute({
      cursor: first.next_cursor,
      limit: 20,
    })) as any;
    assert.equal(next.start, first.next_cursor);
  });

  it('replace_text 는 old_text/new_text 로 working markdown 을 수정한다', async () => {
    const tools = buildMarkdownTools({
      jobId: 'job-1',
      selectedFileIndex: 0,
    } as any) as any;

    await tools.replace_text.execute({
      old_text: 'File one content.',
      new_text: 'Updated file one content.',
    });

    const md = (await tools.get_markdown.execute({})) as any;
    assert.ok(md.content.includes('Updated file one content.'));
    assert.ok(!md.content.includes('File one content.'));
  });

  it('insert_text 는 지정 위치에 new_text 를 삽입한다', async () => {
    const tools = buildMarkdownTools({
      jobId: 'job-1',
      selectedFileIndex: 1,
    } as any) as any;

    await tools.insert_text.execute({
      position: 'Section A',
      new_text: 'Inserted line.',
    });

    const md = (await tools.get_markdown.execute({})) as any;
    assert.ok(md.content.includes('Inserted line.'));
  });

  it('apply_edits 는 approvalMode 와 무관하게 항상 diff 데이터와 requires_approval 을 반환한다 (저장 안 함)', async () => {
    const tools = buildMarkdownTools({
      jobId: 'job-1',
      selectedFileIndex: 1,
    } as any) as any;

    await tools.replace_text.execute({
      old_text: 'Details two.',
      new_text: 'Changed details two.',
    });

    const result = (await tools.apply_edits.execute({})) as any;
    // [Flow: 저장이 발생하지 않아야 함 — 항상 프론트엔드가 저장]
    assert.equal(savedCalls.length, 0);
    // [Flow: 승인 요청 + diff 데이터 반환]
    assert.equal(result.requires_approval, true);
    assert.equal(result.has_changes, true);
    assert.equal(result.page_num, 2);
    assert.equal(result.file_index, 1);
    assert.ok(typeof result.original_markdown === 'string');
    assert.ok(typeof result.edited_markdown === 'string');
    // [Flow: 원본에는旧 텍스트, 편집본에는新 텍스트가 포함되어야 함]
    assert.ok(result.original_markdown.includes('Details two.'));
    assert.ok(result.edited_markdown.includes('Changed details two.'));
    assert.ok(!result.edited_markdown.includes('Details two.'));
  });

  it('apply_edits 는 변경사항이 없으면 saved=false 를 반환한다', async () => {
    const tools = buildMarkdownTools({
      jobId: 'job-1',
      selectedFileIndex: 0,
    } as any) as any;

    const result = (await tools.apply_edits.execute({})) as any;
    assert.equal(result.saved, false);
    assert.equal(savedCalls.length, 0);
  });

  it('apply_edits (insert_text 후) 도 승인 요청을 반환한다', async () => {
    const tools = buildMarkdownTools({
      jobId: 'job-1',
      selectedFileIndex: 0,
    } as any) as any;

    await tools.insert_text.execute({
      position: 'end',
      new_text: 'New appended content.',
    });

    const result = (await tools.apply_edits.execute({})) as any;
    assert.equal(savedCalls.length, 0);
    assert.equal(result.requires_approval, true);
    assert.ok(result.edited_markdown.includes('New appended content.'));
  });
});
