// [Flow: Step 1 (buildIntentHint 함수 임포트) -> Step 2 (대표적인 사용자 발화 케이스 정의)
//       -> Step 3 (각 케이스별 힌트 포함 여부/부재 여부 검증) -> Step 4 (결과 출력)]
// 의도 정규화 모듈의 핵심 동작을 검증하는 경량 유닛 테스트.
// node 내장 test runner + tsx --test로 실행한다.
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { buildIntentHint } from '../intent-synonyms.js';

describe('buildIntentHint', () => {
  it('보고서/문서 관련 표현은 markdown 힌트를 반환한다', () => {
    const hint = buildIntentHint('요약 좀 보고서로 정리해줘');
    assert.ok(hint.includes('markdown editor tools'));
    assert.ok(!hint.includes('sandbox tools'));
  });

  it('메모/글쓰기 표현도 markdown 힌트를 반환한다', () => {
    const hint = buildIntentHint('메모장에 이 내용 적어줘');
    assert.ok(hint.includes('markdown editor tools'));
  });

  it('코드/파이썬/스크립트 표현은 sandbox 힌트를 반환한다', () => {
    const hint = buildIntentHint('파이썬으로 표 하나 만들어줘');
    assert.ok(hint.includes('sandbox tools'));
    assert.ok(!hint.includes('markdown editor tools'));
  });

  it('영어 표현도 sandbox 힌트를 반환한다', () => {
    const hint = buildIntentHint('run a python script to calculate total');
    assert.ok(hint.includes('sandbox tools'));
  });

  it('두 카테고리가 함께 언급되면 둘 다 포함한다', () => {
    const hint = buildIntentHint('보고서에 있는 표를 파이썬으로 계산해줘');
    assert.ok(hint.includes('markdown editor tools'));
    assert.ok(hint.includes('sandbox tools'));
  });

  it('관련 없는 일상 대화는 빈 문자열을 반환한다', () => {
    const hint = buildIntentHint('안녕하세요?');
    assert.equal(hint, '');
  });

  it('description 같은 단어 내부의 script는 false positive가 아니다', () => {
    const hint = buildIntentHint('description field in the document');
    assert.equal(hint, '');
  });

  it('undefined 입력에도 빈 문자열을 반환한다', () => {
    const hint = buildIntentHint(undefined);
    assert.equal(hint, '');
  });
});
