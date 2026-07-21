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

  it('add_text_callout가 page_no, color, opacity 목록을 지원하는지 검증', async () => {
    const tools = buildAnnotationTools({
      jobId: 'job-test',
      sourceIndex: 0,
      authHeaders: {},
    });

    // 텍스트, 페이지, 색상, 불투명도를 배열 목록으로 전달
    const result = await (tools.add_text_callout as any).execute({
      text: ['TitleA', 'TitleB'],
      page_no: [1, 2],
      comment: ['Comment A', 'Comment B'],
      color: ['purple', 'orange'],
      opacity: [0.4, 0.8],
    });

    assert.ok(result.callouts);
    assert.equal(result.total, 2);
    assert.equal(result.callouts[0].ok, true);
    assert.equal(result.callouts[0].page_no, 1);
    assert.equal(result.callouts[0].text, 'TitleA');
    assert.equal(result.callouts[1].ok, true);
    assert.equal(result.callouts[1].page_no, 2);
    assert.equal(result.callouts[1].text, 'TitleB');

    // search-text 호출 기록 검증 (callout는 mode 파라미터 없이 기본 검색)
    assert.equal(savedCalls.length, 2);
    assert.equal(savedCalls[0].query, 'TitleA');
    assert.equal(savedCalls[0].pageNo, '1');
    assert.equal(savedCalls[1].query, 'TitleB');
    assert.equal(savedCalls[1].pageNo, '2');
  });

  it('add_text_callout가 단일 문자열과 단일 매개변수도 정상 처리하는지 검증', async () => {
    const tools = buildAnnotationTools({
      jobId: 'job-test',
      sourceIndex: 0,
      authHeaders: {},
    });

    const result = await (tools.add_text_callout as any).execute({
      text: 'SoloText',
      page_no: 3,
      comment: 'Solo comment',
      color: 'red',
      opacity: 0.5,
    });

    assert.ok(result.callouts);
    assert.equal(result.total, 1);
    assert.equal(result.callouts[0].ok, true);
    assert.equal(result.callouts[0].page_no, 3);
    assert.equal(result.callouts[0].text, 'SoloText');
    assert.equal(savedCalls.length, 1);
    assert.equal(savedCalls[0].query, 'SoloText');
    assert.equal(savedCalls[0].pageNo, '3');
  });

  it('add_text_callout에서 매개변수 배열 길이가 일치하지 않을 때 에러 발생 검증', async () => {
    const tools = buildAnnotationTools({
      jobId: 'job-test',
      sourceIndex: 0,
      authHeaders: {},
    });

    // text 길이는 2인데 color 길이는 3인 경우
    const result = await (tools.add_text_callout as any).execute({
      text: ['A', 'B'],
      color: ['red', 'yellow', 'green'],
    });

    assert.ok(result.error);
    assert.ok(result.error.includes('color array length'));
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

  it('add_text_callout 호출 시 type=3 (FreeTextCallout) 주석으로 생성되는지 검증', async () => {
    let savedAnnotationsPayload: any = null;
    const baseMock = createMockFetch();
    const saveFetch = mock.fn(async (url: string | URL, options?: RequestInit) => {
      const urlString = url.toString();
      if (urlString.includes('/user-annotations')) {
        savedAnnotationsPayload = JSON.parse((options?.body as string) || '{}');
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      }
      return baseMock(url, options);
    }) as unknown as typeof fetch;

    globalThis.fetch = saveFetch;

    const tools = buildAnnotationTools({
      jobId: 'job-test',
      sourceIndex: 0,
      authHeaders: {},
    });

    await (tools.add_text_callout as any).execute({
      text: 'CalloutTarget',
      page_no: 1,
      comment: 'Callout comment',
    });

    const applyResult = await (tools.apply_annotations as any).execute({});
    assert.equal(applyResult.saved, true);
    assert.ok(savedAnnotationsPayload);
    assert.equal(savedAnnotationsPayload.annotations.length, 1);

    const anno = savedAnnotationsPayload.annotations[0].annotation;
    assert.equal(anno.type, 3); // FreeTextCallout
    assert.equal(anno.intent, 'FreeTextCallout');
    assert.equal(anno.contents, 'Callout comment');
  });

  it('add_sticky_note 호출 시 type=1 (Sticky Note / TEXT) 주석으로 생성되는지 검증', async () => {
    let savedAnnotationsPayload: any = null;
    const baseMock = createMockFetch();
    const saveFetch = mock.fn(async (url: string | URL, options?: RequestInit) => {
      const urlString = url.toString();
      if (urlString.includes('/user-annotations')) {
        savedAnnotationsPayload = JSON.parse((options?.body as string) || '{}');
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      }
      return baseMock(url, options);
    }) as unknown as typeof fetch;

    globalThis.fetch = saveFetch;

    const tools = buildAnnotationTools({
      jobId: 'job-test',
      sourceIndex: 0,
      authHeaders: {},
    });

    await (tools.add_sticky_note as any).execute({
      text: 'StickyTarget',
      page_no: 1,
      comment: 'Sticky note comment',
    });

    const applyResult = await (tools.apply_annotations as any).execute({});
    assert.equal(applyResult.saved, true);
    assert.ok(savedAnnotationsPayload);
    assert.equal(savedAnnotationsPayload.annotations.length, 1);

    const anno = savedAnnotationsPayload.annotations[0].annotation;
    assert.equal(anno.type, 1); // EmbedPDF TEXT (Sticky Note)
    assert.equal(anno.icon, 'Comment');
    assert.equal(anno.contents, 'Sticky note comment');
    assert.deepEqual(anno.rect, {
      origin: { x: 200, y: 200 },
      size: { width: 20, height: 20 },
    });
  });

  it('apply_annotations 호출 시 기존 스토리지에 존재하는 주석이 유지(누적)되는지 검증', async () => {
    let savedAnnotationsPayload: any = null;
    const baseMock = createMockFetch();
    const saveFetch = mock.fn(async (url: string | URL, options?: RequestInit) => {
      const urlString = url.toString();
      if (urlString.includes('/annotations')) {
        return new Response(
          JSON.stringify({
            annotations: [
              {
                annotation: {
                  id: 'existing-1',
                  type: 9,
                  pageIndex: 0,
                  rect: { origin: { x: 50, y: 50 }, size: { width: 40, height: 10 } },
                  contents: 'Existing comment',
                },
              },
            ],
            total: 1,
          }),
          { status: 200, headers: { 'content-type': 'application/json' } }
        );
      }
      if (urlString.includes('/user-annotations')) {
        savedAnnotationsPayload = JSON.parse((options?.body as string) || '{}');
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        });
      }
      return baseMock(url, options);
    }) as unknown as typeof fetch;

    globalThis.fetch = saveFetch;

    const tools = buildAnnotationTools({
      jobId: 'job-test',
      sourceIndex: 0,
      authHeaders: {},
    });

    await (tools.add_sticky_note as any).execute({
      text: 'NewText',
      page_no: 1,
      comment: 'New comment',
    });

    const applyResult = await (tools.apply_annotations as any).execute({});
    assert.equal(applyResult.saved, true);
    assert.ok(savedAnnotationsPayload);
    // 기존 주석 1개 + 신규 주석 1개 = 총 2개
    assert.equal(savedAnnotationsPayload.annotations.length, 2);
    const ids = savedAnnotationsPayload.annotations.map((a: any) => a.annotation?.id || a.id);
    assert.ok(ids.includes('existing-1'));
  });
});


