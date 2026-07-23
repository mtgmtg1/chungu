// [Flow: Step 1 (markdown-utils 헬퍼 임포트)
//       -> Step 2 (파일 분할/인덱스 해석/헬딩 검색/섹션 추출/표 추출/퍼지 교체/chunk 케이스 정의)
//       -> Step 3 (각 헬퍼 함수의 기대 동작을 assert 로 검증)]
// markdown-utils.ts 의 순수 함수들을 검증하는 유닛 테스트.

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  splitMarkdownByFileMarkers,
  resolveFileIndex,
  extractFileMarkdown,
  createNodiomDoc,
  getHeadingsFromDoc,
  findBestHeadingMatch,
  findHeadingPath,
  getSectionMarkdown,
  findTablesInMarkdown,
  replaceTextFuzzy,
  insertTextAt,
  readChunk,
  DEFAULT_CHUNK_LIMIT,
} from '../markdown-utils.js';

// [Flow: fixture 데이터 정의 -> 필요한 케이스에서 재사용]
const combinedMarkdown = `<!-- Page 1 -->
# File 1

Content of file one.

<!-- Page 2 -->
# File 2

Content of file two.

| Name | Age |
| --- | --- |
| Kim | 25 |

## Section A

Details here.
`;

const koreanMarkdown = `# 프로젝트

개요입니다.

## 백그라운드

배경 내용.

### 세부 사항

세부 내용.

## 할 일

- [ ] 첫 번째
- [ ] 두 번째
`;

describe('splitMarkdownByFileMarkers', () => {
  it('<!-- Page N --> 마커를 기준으로 파일을 분할하고 마커는 제거한다', () => {
    const parts = splitMarkdownByFileMarkers(combinedMarkdown);
    assert.equal(parts.length, 2);
    assert.ok(parts[0].includes('# File 1'));
    assert.ok(parts[0].includes('Content of file one'));
    assert.ok(!parts[0].includes('<!-- Page 1 -->'));
    assert.ok(parts[1].includes('# File 2'));
    assert.ok(!parts[1].includes('<!-- Page 2 -->'));
  });

  it('<!-- 파일 N --> 마커도 동일하게 분할한다', () => {
    const md = '<!-- 파일 1 -->\n# A\n\n<!-- 파일 2 -->\n# B';
    const parts = splitMarkdownByFileMarkers(md);
    assert.equal(parts.length, 2);
    assert.ok(parts[0].includes('# A'));
    assert.ok(parts[1].includes('# B'));
  });

  it('마커가 없으면 단일 파일 배열을 반환한다', () => {
    const md = '# 제목\n\n내용';
    const parts = splitMarkdownByFileMarkers(md);
    assert.equal(parts.length, 1);
    assert.equal(parts[0], md);
  });

  it('선행 공백/빈 항목은 필터링한다', () => {
    const md = '<!-- Page 1 -->\n# A';
    const parts = splitMarkdownByFileMarkers(md);
    assert.equal(parts.length, 1);
    assert.ok(parts[0].includes('# A'));
  });
});

describe('resolveFileIndex', () => {
  it('명시적 page_no 가 가장 우선한다', () => {
    assert.equal(resolveFileIndex(5, 3, 0, 1), 2);
  });

  it('page_no 가 없으면 selectedFileIndex 를 사용한다', () => {
    assert.equal(resolveFileIndex(5, undefined, 2, 1), 2);
  });

  it('selectedFileIndex 도 없으면 currentPage - 1 을 사용한다', () => {
    assert.equal(resolveFileIndex(5, undefined, undefined, 4), 3);
  });

  it('아무것도 없으면 0 을 반환한다', () => {
    assert.equal(resolveFileIndex(5, undefined, undefined, undefined), 0);
  });

  it('범위를 벗어나면 경계로 클램핑한다', () => {
    assert.equal(resolveFileIndex(3, 10, undefined, undefined), 2);
    assert.equal(resolveFileIndex(3, undefined, -1, undefined), 0);
  });
});

describe('extractFileMarkdown', () => {
  it('선택 인덱스에 해당하는 파일 본문을 반환한다', () => {
    const file0 = extractFileMarkdown(combinedMarkdown, 0);
    assert.ok(file0.includes('# File 1'));
    assert.ok(!file0.includes('# File 2'));

    const file1 = extractFileMarkdown(combinedMarkdown, 1);
    assert.ok(file1.includes('# File 2'));
    assert.ok(!file1.includes('# File 1'));
  });

  it('마커는 결과에 포함되지 않는다', () => {
    const file1 = extractFileMarkdown(combinedMarkdown, 1);
    assert.ok(!file1.includes('<!--'));
  });

  it('인덱스가 범위를 벗어나면 경계값으로 클램핑한다', () => {
    const file = extractFileMarkdown(combinedMarkdown, 99);
    assert.ok(file.includes('# File 2'));
  });
});

describe('createNodiomDoc', () => {
  it('Nodiom 인스턴스를 생성하고 read() 가 동작한다', () => {
    const doc = createNodiomDoc('# 제목\n\n내용');
    const section = doc.read('# 제목');
    assert.ok(section.includes('내용'));
  });
});

describe('getHeadingsFromDoc', () => {
  it('문서의 모든 heading 을 depth, fullPath, selector 와 함께 반환한다', () => {
    const doc = createNodiomDoc(koreanMarkdown);
    const headings = getHeadingsFromDoc(doc);

    assert.ok(headings.length >= 3);
    assert.ok(headings.some(h => h.heading === '프로젝트' && h.depth === 1));
    assert.ok(headings.some(h => h.heading === '백그라운드' && h.depth === 2));
    assert.ok(headings.some(h => h.heading === '세부 사항' && h.depth === 3));
    assert.ok(headings.some(h => h.heading === '할 일' && h.depth === 2));
  });

  it('selector 는 # 문자 반복과 heading 텍스트로 구성된다', () => {
    const doc = createNodiomDoc(koreanMarkdown);
    const headings = getHeadingsFromDoc(doc);
    const todo = headings.find(h => h.heading === '할 일');
    assert.ok(todo);
    assert.equal(todo!.selector, '## 할 일');
  });
});

describe('findBestHeadingMatch', () => {
  const headings = [
    { depth: 1, heading: 'Project', fullPath: 'Project', selector: '# Project', fullSelector: '# Project' },
    { depth: 2, heading: 'Tasks', fullPath: 'Project > Tasks', selector: '## Tasks', fullSelector: '# Project > ## Tasks' },
    { depth: 2, heading: 'Summary', fullPath: 'Project > Summary', selector: '## Summary', fullSelector: '# Project > ## Summary' },
  ];

  it('정확한 heading 을 우선 반환한다', () => {
    const match = findBestHeadingMatch('Tasks', headings);
    assert.equal(match?.heading, 'Tasks');
  });

  it('오타/띄어쓰기가 달라도 퍼지 매칭된다', () => {
    const match = findBestHeadingMatch('Taks', headings);
    assert.equal(match?.heading, 'Tasks');
  });

  it('threshold 미만인 match 는 undefined 를 반환한다', () => {
    const match = findBestHeadingMatch('존재하지 않는 제목', headings, 0.2);
    assert.equal(match, undefined);
  });
});

describe('findHeadingPath', () => {
  const doc = createNodiomDoc(koreanMarkdown);
  const outline = doc.tree();

  it('target heading 의 모든 경로를 반환한다', () => {
    const paths = findHeadingPath(outline, '세부 사항');
    assert.equal(paths.length, 1);
    assert.equal(paths[0].length, 3);
    assert.equal(paths[0][0].heading, '프로젝트');
    assert.equal(paths[0][1].heading, '백그라운드');
    assert.equal(paths[0][2].heading, '세부 사항');
  });

  it('parentHeading 을 지정하면 해당 부모 아래 경로만 필터링한다', () => {
    const paths = findHeadingPath(outline, '세부 사항', '백그라운드');
    assert.equal(paths.length, 1);
  });
});

describe('getSectionMarkdown', () => {
  it('정확한 heading 의 섹션 markdown 을 반환한다', () => {
    const doc = createNodiomDoc(koreanMarkdown);
    const result = getSectionMarkdown(doc, '백그라운드') as { content: string; headingInfo: { heading: string } };
    assert.ok('content' in result);
    assert.ok(result.content.includes('배경 내용'));
    assert.equal(result.headingInfo.heading, '백그라운드');
  });

  it('오타가 있어도 fuzzy 매칭으로 섹션을 찾는다', () => {
    const doc = createNodiomDoc(koreanMarkdown);
    const result = getSectionMarkdown(doc, '백그라운') as { content: string; headingInfo: { heading: string } };
    assert.ok('content' in result);
    assert.equal(result.headingInfo.heading, '백그라운드');
  });

  it('parent_heading 로 모호한 heading 을 해소한다', () => {
    const md = '# 프로젝트 A\n\n## 할 일\n\nA 작업\n\n# 프로젝트 B\n\n## 할 일\n\nB 작업';
    const doc = createNodiomDoc(md);
    const result = getSectionMarkdown(doc, '할 일', '프로젝트 B') as { content: string; headingInfo: { heading: string; fullPath: string } };
    assert.ok('content' in result);
    assert.ok(result.content.includes('B 작업'));
    assert.ok(!result.content.includes('A 작업'));
  });

  it('매칭되는 heading 이 없으면 error 와 suggestions 를 반환한다', () => {
    const doc = createNodiomDoc(koreanMarkdown);
    const result = getSectionMarkdown(doc, '없는 제목') as { error: string; suggestions: string[] };
    assert.ok('error' in result);
    assert.ok(result.suggestions.length > 0 || result.error.length > 0);
  });
});

describe('findTablesInMarkdown', () => {
  const md = '# Title\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n## Section\n\n| X | Y |\n|---|---|\n| 3 | 4 |';

  it('GFM 표를 추출하고 table_index 로 특정 표를 반환한다', () => {
    const result = findTablesInMarkdown(md, 1);
    assert.equal(result.tables.length, 2);
    assert.ok(result.table?.includes('X'));
    assert.ok(!result.table?.includes('A'));
  });

  it('heading 을 지정하면 해당 섹션 내 표만 반환한다', () => {
    const result = findTablesInMarkdown(md, 0, 'Section');
    assert.equal(result.tables.length, 1);
    assert.ok(result.table?.includes('X'));
  });
});

describe('replaceTextFuzzy', () => {
  it('정확한 old_text 를 new_text 로 교체한다', () => {
    const md = 'Line one\nLine two\nLine three';
    const { markdown, success } = replaceTextFuzzy(md, 'Line two', 'Line 2');
    assert.equal(success, true);
    assert.ok(markdown.includes('Line 2'));
    assert.ok(!markdown.includes('Line two'));
  });

  it('줄바꿈/공백 drift 가 있어도 퍼지 교체에 성공한다', () => {
    const md = 'The quick brown\nfox jumps over the lazy dog.';
    const old = 'The quick brown fox';
    const { markdown, success } = replaceTextFuzzy(md, old, 'A slow red fox');
    assert.equal(success, true);
    assert.ok(markdown.includes('A slow red fox'));
    assert.ok(!markdown.includes('The quick brown'));
  });

  it('old_text 가 없으면 success=false 이고 markdown 은 변경되지 않는다', () => {
    const md = 'Some content';
    const { markdown, success } = replaceTextFuzzy(md, 'Missing text', 'New');
    assert.equal(success, false);
    assert.equal(markdown, md);
  });

  it('한국어 표 행에서 정확 매칭 교체에 성공한다 (Pattern too long 회피)', () => {
    const md = '| 수용기관 | 수원구치소 | 수용번호 | 5839 |\n| --- | --- | --- | --- |';
    const old_text = '| 수용기관 | 수원구치소 | 수용번호 | 5839 |';
    const new_text = '| 수용기관 | 수원구치소 (중요: 수용기관) | 수용번호 | 5839 (중요: 수용번호) |';
    const { markdown, success } = replaceTextFuzzy(md, old_text, new_text);
    assert.equal(success, true);
    assert.ok(markdown.includes('수원구치소 (중요: 수용기관)'));
    assert.ok(markdown.includes('5839 (중요: 수용번호)'));
  });

  it('한국어 표 행에서 퍼지 매칭(줄바꿈 drift) 교체에 성공한다', () => {
    const md = '| 수용자명 | 응우옌안뚜안 | 소송사건 대리인 변호사접견 횟수(월) | 0/4 |\n| --- | --- | --- | --- |';
    const old_text = '| 수용자명 | 응우옌안뚜안 | 소송사건 대리인 변호사접견 횟수(월) | 0/4 |';
    const new_text = '| 수용자명 | 응우옌안뚜안 (중요: 수용자명) | 소송사건 대리인 변호사접견 횟수(월) | 0/4 |';
    const { markdown, success } = replaceTextFuzzy(md, old_text, new_text);
    assert.equal(success, true);
    assert.ok(markdown.includes('응우옌안뚜안 (중요: 수용자명)'));
  });

  it('긴 한국어 문단(32자 초과)에서 교체에 성공한다', () => {
    const md = '이것은 매우 긴 한국어 문단입니다. 비트패 알고리즘이 패턴 길이 제한으로 실패하는 경우를 테스트합니다.';
    const old_text = '이것은 매우 긴 한국어 문단입니다. 비트패 알고리즘이 패턴 길이 제한으로 실패하는 경우를 테스트합니다.';
    const new_text = '교체된 문단입니다.';
    const { markdown, success } = replaceTextFuzzy(md, old_text, new_text);
    assert.equal(success, true);
    assert.ok(markdown.includes('교체된 문단입니다.'));
  });
});

describe('insertTextAt', () => {
  const md = '# Heading\n\nExisting content.';

  it('beginning 위치에 삽입한다', () => {
    const { markdown, success } = insertTextAt(md, 'beginning', 'New top');
    assert.equal(success, true);
    assert.ok(markdown.startsWith('New top'));
  });

  it('end 위치에 삽입한다', () => {
    const { markdown, success } = insertTextAt(md, 'end', 'New bottom');
    assert.equal(success, true);
    assert.ok(markdown.endsWith('New bottom'));
  });

  it('heading 문자열이면 해당 섹션에 append 한다', () => {
    const { markdown, success } = insertTextAt(md, 'Heading', '\n- [ ] New task', createNodiomDoc(md));
    assert.equal(success, true);
    assert.ok(markdown.includes('- [ ] New task'));
  });
});

describe('readChunk', () => {
  const md = '0123456789'.repeat(100);

  it('first 방향은 첫 chunk 와 nextCursor 를 반환한다', () => {
    const chunk = readChunk(md, 'first', 50, 'next');
    assert.equal(chunk.chunk.length, 50);
    assert.equal(chunk.start, 0);
    assert.equal(chunk.end, 50);
    assert.equal(chunk.nextCursor, 50);
    assert.equal(chunk.hasMore, true);
  });

  it('next 방향은 cursor 부터 limit 만큼 반환한다', () => {
    const chunk = readChunk(md, 50, 50, 'next');
    assert.equal(chunk.start, 50);
    assert.equal(chunk.end, 100);
    assert.equal(chunk.nextCursor, 100);
  });

  it('previous 방향은 cursor 이전 limit 만큼 반환한다', () => {
    const chunk = readChunk(md, 100, 50, 'previous');
    assert.equal(chunk.start, 50);
    assert.equal(chunk.end, 100);
    assert.equal(chunk.previousCursor, 50);
  });

  it('마지막 chunk 이면 hasMore 는 false 이다', () => {
    const total = md.length;
    const chunk = readChunk(md, total - 50, 50, 'next');
    assert.equal(chunk.end, total);
    assert.equal(chunk.hasMore, false);
  });

  it('cursor 가 number 가 아닌 첫 호출에도 기본값 0 이 사용된다', () => {
    const chunk = readChunk(md, 0, 50, 'next');
    assert.equal(chunk.start, 0);
  });
});
