// [Flow: Step 1 (초기 markdown으로 SimpleEditor 렌더링) -> Step 2 (markdown prop을 새 값으로 변경)
//       -> Step 3 (Tiptap 에디터 내용이 새 markdown으로 동기화되었는지 검증)]
// 에이전트 도구(apply_edits)가 백엔드에 저장 후 부모가 markdown prop을 갱신할 때
// SimpleEditor가 Tiptap 내용을 동기화하는지 확인하는 회귀 테스트.
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import SimpleEditor from "./SimpleEditor.jsx";

// [Flow: 외부 의존성 mock — Tiptap 자체는 실제로 동작시켜 동기화 로직을 검증]
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key) => key }),
}));

vi.mock("./AiMenu.jsx", () => ({
  default: function MockAiMenu() {
    return null;
  },
}));

vi.mock("./editor/TocSidebar.jsx", () => ({
  default: function MockTocSidebar() {
    return null;
  },
}));

// IntersectionObserver mock (PageMarker 감시용)
class MockIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

global.IntersectionObserver = MockIntersectionObserver;

describe("SimpleEditor — markdown prop 동기화", () => {
  it("markdown prop이 변경되면 Tiptap 에디터 내용이 갱신된다", async () => {
    const initialMarkdown = "# 제목 A\n\n첫 번째 내용입니다.";
    const updatedMarkdown = "# 제목 B\n\n에이전트가 수정한 내용입니다.";

    const { rerender } = render(
      <SimpleEditor markdown={initialMarkdown} editable={true} />
    );

    // [Flow: 초기 렌더링 — Tiptap가 마운트되어 초기 content를 표시]
    await waitFor(() => {
      expect(screen.getByText("제목 A")).toBeTruthy();
    });

    // [Flow: markdown prop 변경 — 에이전트가 apply_edits로 저장 후 부모가 갱신한 상황 시뮬레이션]
    rerender(<SimpleEditor markdown={updatedMarkdown} editable={true} />);

    // [Flow: 검증 — 새 markdown 내용이 에디터에 반영되었는지 확인]
    await waitFor(() => {
      expect(screen.getByText("제목 B")).toBeTruthy();
      expect(screen.getByText("에이전트가 수정한 내용입니다.")).toBeTruthy();
    });

    // [Flow: 이전 내용이 제거되었는지 확인]
    expect(screen.queryByText("제목 A")).toBeNull();
    expect(screen.queryByText("첫 번째 내용입니다.")).toBeNull();
  });

  it("markdown prop이 변경되어도 onChange 콜백이 발생하지 않는다 (emitUpdate:false)", async () => {
    const initialMarkdown = "# 원본\n\n내용";
    const updatedMarkdown = "# 수정됨\n\n새 내용";
    const onChange = vi.fn();

    const { rerender } = render(
      <SimpleEditor markdown={initialMarkdown} editable={true} onChange={onChange} />
    );

    await waitFor(() => {
      expect(screen.getByText("원본")).toBeTruthy();
    });

    // [Flow: onChange 호출 카운트 초기화 — 초기 마운트로 인한 호출 제거]
    onChange.mockClear();

    // [Flow: markdown prop 변경]
    rerender(
      <SimpleEditor markdown={updatedMarkdown} editable={true} onChange={onChange} />
    );

    await waitFor(() => {
      expect(screen.getByText("수정됨")).toBeTruthy();
    });

    // [Flow: 검증 — setContent가 emitUpdate:false로 호출되므로 onChange가 발생하지 않아야 함]
    // debounce 타이머(1초) 후에도 호출되지 않는지 확인
    await new Promise((resolve) => setTimeout(resolve, 1200));
    expect(onChange).not.toHaveBeenCalled();
  });
});
