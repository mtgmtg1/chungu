// [Flow: Step 1 (분류된 양측 노드 데이터 생성) -> Step 2 (ResizableCourtroomCards 렌더링)
//       -> Step 3 (react-resizable-panels 핸들과 양측 헤더가 모두 존재하는지 검증)]
// 중앙 양측 카드의 수평 리사이즈 레이아웃을 검증하는 단위 테스트.

import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import ResizableCourtroomCards from "./ResizableCourtroomCards.jsx";

const classifiedSides = {
  plaintiff: {
    claims: [{ id: "p-claim", type: "plaintiff", data: { label: "원고 주장", page: 2 } }],
    evidence: [{ id: "p-ev", type: "evidence", data: { label: "원고 증거", page: 3, entity: "plaintiff" } }],
  },
  defendant: {
    claims: [{ id: "d-claim", type: "defendant", data: { label: "피고 반박", page: 4 } }],
    evidence: [{ id: "d-ev", type: "evidence", data: { label: "피고 증거", page: 5, entity: "defendant" } }],
  },
};

describe("ResizableCourtroomCards", () => {
  it("양측 헤더를 모두 렌더링한다", () => {
    render(<ResizableCourtroomCards classifiedSides={classifiedSides} onNodeClick={vi.fn()} />);
    expect(screen.getByText("CLIENT ARGUMENTS (PLAINTIFF)")).toBeInTheDocument();
    expect(screen.getByText("OPPONENT REBUTTALS (DEFENDANT)")).toBeInTheDocument();
  });

  it("주장과 증거 카드가 양측에 모두 존재한다", () => {
    render(<ResizableCourtroomCards classifiedSides={classifiedSides} onNodeClick={vi.fn()} />);
    expect(screen.getByText("원고 주장")).toBeInTheDocument();
    expect(screen.getByText("원고 증거")).toBeInTheDocument();
    expect(screen.getByText("피고 반박")).toBeInTheDocument();
    expect(screen.getByText("피고 증거")).toBeInTheDocument();
  });

  it("리사이즈 핸들 역할을 하는 구분자가 존재한다", () => {
    const { container } = render(<ResizableCourtroomCards classifiedSides={classifiedSides} onNodeClick={vi.fn()} />);
    const resizeHandle = container.querySelector('[data-oid="ediscovery-cards-resize-handle"]');
    expect(resizeHandle).toBeInTheDocument();
  });
});
