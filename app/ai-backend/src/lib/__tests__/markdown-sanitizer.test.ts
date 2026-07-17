// [Flow: Step 1 (sanitizeMarkdownForLLM 함수 임포트) -> Step 2 (base64 PNG 헬퍼 생성)
//       -> Step 3 (HTML/markdown data URI 제거/보존 케이스 검증) -> Step 4 (결과 출력)]
// 마크다운 내 data:image base64 인라인 이미지 제거 기능을 검증하는 경량 유닛 테스트.
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { sanitizeMarkdownForLLM } from '../markdown-sanitizer.js';

function makeBase64Png(): string {
  // 1x1 픽셀 빨간색 PNG를 base64 data URI로 반환한다.
  const b64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
  return `data:image/png;base64,${b64}`;
}

describe('sanitizeMarkdownForLLM', () => {
  it('src="data:image..." HTML 이미지 태그를 placeholder로 치환한다', () => {
    const b64Uri = makeBase64Png();
    const markdown = `문서\n\n<img src="${b64Uri}" alt="테스트">\n\n끝`;
    const result = sanitizeMarkdownForLLM(markdown);

    assert.ok(!result.includes('data:image'));
    assert.ok(!result.includes(b64Uri));
    assert.ok(result.includes('[image]'));
    assert.ok(result.includes('문서'));
    assert.ok(result.includes('끝'));
  });

  it("src='data:image...' HTML 이미지 태그도 처리한다", () => {
    const b64Uri = makeBase64Png();
    const markdown = `<img src='${b64Uri}' alt='테스트'>`;
    const result = sanitizeMarkdownForLLM(markdown);

    assert.ok(!result.includes('data:image'));
    assert.ok(result.includes('[image]'));
  });

  it('![alt](data:image...) 마크다운 이미지를 placeholder URL로 치환한다', () => {
    const b64Uri = makeBase64Png();
    const markdown = `![테스트 이미지](${b64Uri})`;
    const result = sanitizeMarkdownForLLM(markdown);

    assert.ok(!result.includes('data:image'));
    assert.ok(!result.includes(b64Uri));
    assert.ok(result.includes('[image]'));
  });

  it('여러 base64 이미지를 모두 제거한다', () => {
    const b64Uri = makeBase64Png();
    const markdown = `${b64Uri}\n\n![alt](${b64Uri})\n\n<img src="${b64Uri}">`;
    const result = sanitizeMarkdownForLLM(markdown);

    assert.equal(result.includes('data:image'), false);
    assert.ok(result.split('[image]').length - 1 >= 3);
  });

  it('일반 http(s) 이미지 URL은 변경하지 않는다', () => {
    const markdown = '![external](https://example.com/img.png)\n\n<img src="/api/jobs/123/ocr-images/results/123/images/abc.png">';
    const result = sanitizeMarkdownForLLM(markdown);

    assert.equal(result, markdown);
  });

  it('표와 페이지 마커를 보존한다', () => {
    const b64Uri = makeBase64Png();
    const markdown = `<!-- Page 1 -->\n\n| 이름 | 나이 |\n| --- | --- |\n| 홍길동 | 25 |\n\n<img src="${b64Uri}">`;
    const result = sanitizeMarkdownForLLM(markdown);

    assert.ok(result.includes('<!-- Page 1 -->'));
    assert.ok(result.includes('| 이름 | 나이 |'));
    assert.ok(result.includes('홍길동'));
    assert.ok(!result.includes('data:image'));
  });

  it('빈 문자열은 빈 문자열을 반환한다', () => {
    assert.equal(sanitizeMarkdownForLLM(''), '');
  });

  it('base64 이미지가 없으면 입력이 그대로 반환된다', () => {
    const markdown = '# 제목\n\n일반 텍스트\n\n| a | b |\n| 1 | 2 |';
    assert.equal(sanitizeMarkdownForLLM(markdown), markdown);
  });

  it('사용자 정의 placeholder를 사용할 수 있다', () => {
    const b64Uri = makeBase64Png();
    const markdown = `<img src="${b64Uri}">`;
    const result = sanitizeMarkdownForLLM(markdown, '[IMAGE_PLACEHOLDER]');

    assert.ok(result.includes('[IMAGE_PLACEHOLDER]'));
  });
});
