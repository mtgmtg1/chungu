// [Flow: Step 1 (DOM 요소 생성 — h1/h2/p 형제 구조)
//       -> Step 2 (hideFollowingSiblings/showFollowingSiblings 호출)
//       -> Step 3 (같거나 상위 레벨 헤딩 전까지 숨김/표시 검증)]
//
// CollapsibleHeading의 DOM 조작 유틸리티 함수들이 노션 스타일
// "제목이 아래 본문을 토글" 동작을 올바르 수행하는지 검증한다.

import { describe, it, expect } from "vitest";
import {
  getHeadingLevel,
  hideFollowingSiblings,
  showFollowingSiblings,
} from "../CollapsibleHeading.jsx";

/**
 * [Flow: 테스트용 DOM 구조 생성 — 헤딩 + 본문 + 하위 헤딩 + 본문]
 *
 * @param {string} html - 생성할 HTML 문자열
 * @returns {HTMLDivElement} DOM 컨테이너
 */
function createDomContainer(html) {
  const container = document.createElement("div");
  container.innerHTML = html;
  return container;
}

describe("getHeadingLevel", () => {
  it("h1~h6 태그에서 올바른 레벨을 추출한다", () => {
    for (let i = 1; i <= 6; i++) {
      const el = document.createElement(`h${i}`);
      expect(getHeadingLevel(el)).toBe(i);
    }
  });

  it("헤딩이 아닌 요소는 null을 반환한다", () => {
    expect(getHeadingLevel(document.createElement("p"))).toBeNull();
    expect(getHeadingLevel(document.createElement("div"))).toBeNull();
    expect(getHeadingLevel(null)).toBeNull();
  });
});

describe("hideFollowingSiblings", () => {
  it("같은 레벨 다음 헤딩 전까지 형제를 숨긴다", () => {
    const container = createDomContainer(`
      <h1>제목 1</h1>
      <p>본문 1</p>
      <p>본문 2</p>
      <h1>제목 2</h1>
      <p>본문 3</p>
    `);
    const h1 = container.querySelector("h1");
    hideFollowingSiblings(h1, 1);

    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs[0].style.display).toBe("none");
    expect(paragraphs[1].style.display).toBe("none");
    expect(paragraphs[2].style.display).toBe("");
  });

  it("상위 레벨 헤딩이 나오면 숨김을 중단한다", () => {
    const container = createDomContainer(`
      <h2>하위 제목</h2>
      <p>본문 1</p>
      <h1>상위 제목</h1>
      <p>본문 2</p>
    `);
    const h2 = container.querySelector("h2");
    hideFollowingSiblings(h2, 2);

    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs[0].style.display).toBe("none");
    expect(paragraphs[1].style.display).toBe("");
  });

  it("같은 레벨 헤딩이 나오면 숨김을 중단한다", () => {
    const container = createDomContainer(`
      <h2>제목 A</h2>
      <p>본문 A</p>
      <h2>제목 B</h2>
      <p>본문 B</p>
    `);
    const firstH2 = container.querySelector("h2");
    hideFollowingSiblings(firstH2, 2);

    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs[0].style.display).toBe("none");
    expect(paragraphs[1].style.display).toBe("");
  });

  it("하위 레벨 헤딩은 숨김 대상에 포함한다", () => {
    const container = createDomContainer(`
      <h1>제목 1</h1>
      <h2>하위 제목</h2>
      <p>하위 본문</p>
      <h1>제목 2</h1>
    `);
    const h1 = container.querySelector("h1");
    hideFollowingSiblings(h1, 1);

    const h2 = container.querySelector("h2");
    const p = container.querySelector("p");
    expect(h2.style.display).toBe("none");
    expect(p.style.display).toBe("none");
  });

  it("끝까지 헤딩이 없으면 모든 후속 형제를 숨긴다", () => {
    const container = createDomContainer(`
      <h1>제목</h1>
      <p>본문 1</p>
      <p>본문 2</p>
      <p>본문 3</p>
    `);
    const h1 = container.querySelector("h1");
    hideFollowingSiblings(h1, 1);

    const paragraphs = container.querySelectorAll("p");
    paragraphs.forEach((p) => {
      expect(p.style.display).toBe("none");
    });
  });
});

describe("showFollowingSiblings", () => {
  it("숨겨진 형제를 다시 표시한다", () => {
    const container = createDomContainer(`
      <h1>제목</h1>
      <p>본문 1</p>
      <p>본문 2</p>
      <h1>제목 2</h1>
    `);
    const h1 = container.querySelector("h1");
    // 먼저 숨긴 후
    hideFollowingSiblings(h1, 1);
    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs[0].style.display).toBe("none");
    expect(paragraphs[1].style.display).toBe("none");

    // 다시 표시
    showFollowingSiblings(h1, 1);
    expect(paragraphs[0].style.display).toBe("");
    expect(paragraphs[1].style.display).toBe("");
  });

  it("상위 레벨 헤딩 전까지만 표시 복원", () => {
    const container = createDomContainer(`
      <h2>하위 제목</h2>
      <p>본문 1</p>
      <h1>상위 제목</h1>
      <p>본문 2</p>
    `);
    const h2 = container.querySelector("h2");
    showFollowingSiblings(h2, 2);

    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs[0].style.display).toBe("");
    // 상위 헤딩 이후는 showFollowingSiblings 범위 밖 — display 변경 없음
    expect(paragraphs[1].style.display).toBe("");
  });
});
