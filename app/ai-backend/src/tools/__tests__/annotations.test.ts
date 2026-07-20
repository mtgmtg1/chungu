// [Flow: Step 1 (globalThis.fetch mock 설정) -> Step 2 (buildAnnotationTools 호출) -> Step 3 (add_text_highlight/add_text_callout 도구의 다중 매개변수 목록 처리 검증)]
// PDF 주석 도구인 add_text_highlight와 add_text_callout이
// page_no, color, opacity를 배열 목록으로 받았을 때 개별 텍스트 항목에 올바르게 매핑하는지 검증하는 테스트.

import { describe, it, beforeEach, afterEach, mock } from 'node:test';
import assert from 'node:assert/strict';
import { buildAnnotationTools } from '../annotations.js';

let savedCalls: Array<{ url: string; query: string; pageNo: string | null }> = [];
let originalFetch: any;

// [Flow: fetch mock 생성 -> /search-text 요청에 대해 query 텍스트가 매칭된 결과를 모의 응답함]
function createMockFetch() {
  return mock.fn(async (url: string | URL, options?: RequestInit) => {
    const urlString = url.toString();

    if (urlString.includes('/search-text')) {
      const urlObj = new URL(urlString);
      const query = urlObj.searchParams.get('query') || '';
      const pageNo = urlObj.searchParams.get('page_no');
      
      savedCalls.push({ url: urlString, query, pageNo });

      const matches = [
        {
          page_no: pageNo ? Number(pageNo) : 1,
          text: query,
          bbox_pdf: [100, 100, 200, 200],
        }
      ];

      return new Response(JSON.stringify({ matches }), {
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

describe('buildAnnotationTools - 목록 요청 기능 테스트', () => {
  beforeEach(() => {
    savedCalls = [];
    originalFetch = globalThis.fetch;
    globalThis.fetch = createMockFetch();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('add_text_highlight가 page_no, color, opacity 목록을 지원하는지 검증', async () => {
    const tools = buildAnnotationTools({
      jobId: 'job-test',
      sourceIndex: 0,
      authHeaders: {},
    });

    // 텍스트, 페이지, 색상, 불투명도를 배열 목록으로 전달
    const result = await (tools.add_text_highlight as any).execute({
      text: ['Hello', 'World'],
      page_no: [1, 2],
      comment: ['First comment', 'Second comment'],
      color: ['red', 'blue'],
      opacity: [0.3, 0.7],
    });

    assert.ok(result.highlights);
    assert.equal(result.total, 2);
    assert.equal(result.highlights[0].ok, true);
    assert.equal(result.highlights[0].page_no, 1);
    assert.equal(result.highlights[1].ok, true);
    assert.equal(result.highlights[1].page_no, 2);
    
    // search-text 호출 기록 검증
    assert.equal(savedCalls.length, 2);
    assert.equal(savedCalls[0].query, 'Hello');
    assert.equal(savedCalls[0].pageNo, '1');
    assert.ok(savedCalls[0].url.includes('mode=text'));
    assert.equal(savedCalls[1].query, 'World');
    assert.equal(savedCalls[1].pageNo, '2');
    assert.ok(savedCalls[1].url.includes('mode=text'));
  });

  it('add_line_highlight가 page_no, color, opacity 목록 및 mode=line을 지원하는지 검증', async () => {
    const tools = buildAnnotationTools({
      jobId: 'job-test',
      sourceIndex: 0,
      authHeaders: {},
    });

    const result = await (tools.add_line_highlight as any).execute({
      text: ['Line1', 'Line2'],
      page_no: [1, 3],
      color: ['green', 'purple'],
    });

    assert.ok(result.highlights);
    assert.equal(result.total, 2);
    assert.equal(result.highlights[0].ok, true);
    assert.equal(result.highlights[1].ok, true);

    assert.equal(savedCalls.length, 2);
    assert.equal(savedCalls[0].query, 'Line1');
    assert.ok(savedCalls[0].url.includes('mode=line'));
    assert.equal(savedCalls[1].query, 'Line2');
    assert.ok(savedCalls[1].url.includes('mode=line'));
  });

  it('매개변수 배열 길이가 일치하지 않을 때 에러 발생 검증', async () => {
    const tools = buildAnnotationTools({
      jobId: 'job-test',
      sourceIndex: 0,
      authHeaders: {},
    });

    // text 길이는 2인데 page_no 길이는 3인 경우
    const result = await (tools.add_text_highlight as any).execute({
      text: ['Hello', 'World'],
      page_no: [1, 2, 3],
    });

    assert.ok(result.error);
    assert.ok(result.error.includes('page_no array length'));
  });
});
