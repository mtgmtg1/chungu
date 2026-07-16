// [Flow: Step 1 (EdiscoveryDetailCard의 react-i18next 모의)
//       -> Step 2 (노드 + sourceFiles로 렌더링)
//       -> Step 3 (헤더/요약/마크다운 원문 렌더링 및 콜백 동작 검증)]
// EdiscoveryDetailCard 상세 팝업의 기본 렌더링과 사용자 상호작용 회귀 테스트.

import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import EdiscoveryDetailCard from "./EdiscoveryDetailCard.jsx";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key) => key, i18n: { language: "ko" } }),
}));

/**
 * 테스트용 e-Discovery 노드를 생성한다.
 *
 * @param {string} id - 노드 ID
 * @param {string} type - 노드 타입
 * @param {number} page - 페이지 번호
 * @param {string} label - 라벨
 * @param {string} summary - 요약
 * @returns {Object} e-Discovery graph 노드
 */
function baseNode(id, type, page, label, summary) {
  return {
    id,
    type,
    data: { label, page, summary, entity: type },
  };
}

describe("EdiscoveryDetailCard", () => {
  it("노드 라벨, 페이지, 요약, 마크다운 원문을 렌더링한다", () => {
    const node = baseNode("node-1", "issue", 3, "쟁점 1", "요약 텍스트입니다.");
    const sourceFiles = [
      {
        page_num: 3,
        type: "pdf",
        url: "https://example.com/doc.pdf",
        name: "doc.pdf",
        result_markdown: "# 원문 제목\n\n원문 내용입니다.",
      },
    ];

    const { container } = render(
      <EdiscoveryDetailCard
        node={node}
        sourceFiles={sourceFiles}
        onClose={() => {}}
        onViewSource={() => {}}
      />
    );

    expect(container.textContent).toContain("쟁점 1");
    expect(container.textContent).toContain("p.3");
    expect(container.textContent).toContain("요약 텍스트입니다.");
    expect(container.textContent).toContain("원문 제목");
    expect(container.textContent).toContain("원문 내용입니다.");
  });

  it("닫기 버튼 클릭 시 onClose를 호출한다", () => {
    const node = baseNode("node-2", "evidence", 1, "증거", "요약");
    const onClose = vi.fn();

    const { getByLabelText } = render(
      <EdiscoveryDetailCard
        node={node}
        sourceFiles={[]}
        onClose={onClose}
        onViewSource={() => {}}
      />
    );

    fireEvent.click(getByLabelText("page:result.ediscoveryClose"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("원본 PDF 보기 버튼 클릭 시 onViewSource를 호출한다", () => {
    const node = baseNode("node-3", "evidence", 2, "증거 2", "요약");
    const onViewSource = vi.fn();

    const { getByText } = render(
      <EdiscoveryDetailCard
        node={node}
        sourceFiles={[]}
        onClose={() => {}}
        onViewSource={onViewSource}
      />
    );

    fireEvent.click(getByText("page:result.ediscoveryViewSource"));
    expect(onViewSource).toHaveBeenCalledTimes(1);
    expect(onViewSource).toHaveBeenCalledWith(node);
  });
});
