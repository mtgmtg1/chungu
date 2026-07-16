// [Flow: Step 1 (ReasoningBlock 렌더링) -> Step 2 (기본 접힘 상태 검증)
//       -> Step 3 (토글 클릭) -> Step 4 (내용 표시/숨김 검증)]
// 어시스턴트 메시지의 reasoning(사고) 영역이 기본적으로 접혀 있고,
// 클릭으로 펼쳐 볼 수 있는지 확인하는 단위 테스트.
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ReasoningBlock from "./ReasoningBlock.jsx";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key, fallback) => fallback,
    i18n: { language: "ko" },
  }),
}));

describe("ReasoningBlock", () => {
  it("기본적으로 내용을 숨기고 토글 버튼만 보여준다", () => {
    render(<ReasoningBlock text="내부 사고 과정" />);

    expect(screen.getByText("생각 과정 보기")).toBeInTheDocument();
    expect(screen.queryByText("내부 사고 과정")).not.toBeInTheDocument();
  });

  it("토글 클릭 시 reasoning 내용을 표시하고, 다시 클릭하면 숨긴다", () => {
    render(<ReasoningBlock text="내부 사고 과정" />);
    const button = screen.getByRole("button");

    fireEvent.click(button);
    expect(screen.getByText("내부 사고 과정")).toBeInTheDocument();

    fireEvent.click(button);
    expect(screen.queryByText("내부 사고 과정")).not.toBeInTheDocument();
  });

  it("텍스트가 비어 있으면 아무것도 렌더링하지 않는다", () => {
    const { container } = render(<ReasoningBlock text="" />);

    expect(container.firstChild).toBeNull();
  });
});
