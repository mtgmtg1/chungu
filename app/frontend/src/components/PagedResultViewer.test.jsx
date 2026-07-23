// [Flow: Step 1 (PagedResultViewer를 leftPanelOpen/rightPanelOpen prop과 렌더링)
//       -> Step 2 (react-resizable-panels Panel ref의 expand/collapse 호출 검증)
//       -> Step 3 (prop 토글 시 올바른 메서드가 호출되는지 확인)]
// 마크다운 모드에서 좌·우 패널 보이기/숨기기 토글이 작동하는지 검증하는 회귀 테스트.
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { act, forwardRef, useMemo } from "react";
import PagedResultViewer from "./PagedResultViewer.jsx";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key) => key }),
}));

vi.mock("../api.js", () => ({
  api: { previewJob: vi.fn().mockResolvedValue({ markdown: "" }), saveResultPage: vi.fn().mockResolvedValue({}) },
}));

vi.mock("./SourcePanel.jsx", () => ({
  default: function MockSourcePanel() {
    return <div data-testid="source-panel" />;
  },
}));

vi.mock("./SimpleEditor.jsx", () => ({
  default: function MockSimpleEditor() {
    return <div data-testid="simple-editor" />;
  },
}));

// [Flow: Panel ref에 expand/collapse 스파이를 노출하는 mock]
// 각 Panel 인스턴스는 data-panel-side 속성으로 좌/우를 식별하여 spy를 등록한다.
const panelSpies = { left: null, right: null };
vi.mock("react-resizable-panels", () => {
  const Panel = forwardRef(function MockPanel({ children, "data-panel-side": side }, ref) {
    // [Flow: 실제 Panel처럼 imperative handle을 인스턴스당 한 번만 생성해 안정적으로 유지]
    // 매 렌더마다 새 spy를 만들면 비동기 재렌더링 후 spy가 덮어씌워져 호출 기록이 사라진다.
    const spy = useMemo(() => ({ expand: vi.fn(), collapse: vi.fn() }), []);
    if (side === "left") panelSpies.left = spy;
    if (side === "right") panelSpies.right = spy;
    if (typeof ref === "function") ref(spy);
    else if (ref && "current" in ref) ref.current = spy;
    return children;
  });
  return {
    PanelGroup: ({ children }) => <>{children}</>,
    Panel,
    PanelResizeHandle: () => null,
  };
});

describe("PagedResultViewer — 좌·우 패널 토글 제어", () => {
  it("leftPanelOpen=false면 왼쪽 패널 collapse()가 호출된다", () => {
    render(
      <PagedResultViewer
        jobId="job-1"
        pages={[{ page_num: 1 }]}
        sourceFiles={[]}
        leftPanelOpen={false}
        rightPanelOpen={true}
      />
    );
    expect(panelSpies.left).toBeTruthy();
    expect(panelSpies.left.collapse).toHaveBeenCalled();
  });

  it("leftPanelOpen=true면 왼쪽 패널 expand()가 호출된다", () => {
    render(
      <PagedResultViewer
        jobId="job-2"
        pages={[{ page_num: 1 }]}
        sourceFiles={[]}
        leftPanelOpen={true}
        rightPanelOpen={true}
      />
    );
    expect(panelSpies.left).toBeTruthy();
    expect(panelSpies.left.expand).toHaveBeenCalled();
  });

  it("rightPanelOpen=false면 오른쪽 패널 collapse()가 호출된다", () => {
    render(
      <PagedResultViewer
        jobId="job-3"
        pages={[{ page_num: 1 }]}
        sourceFiles={[]}
        leftPanelOpen={true}
        rightPanelOpen={false}
      />
    );
    expect(panelSpies.right).toBeTruthy();
    expect(panelSpies.right.collapse).toHaveBeenCalled();
  });

  it("rightPanelOpen=true면 오른쪽 패널 expand()가 호출된다", () => {
    render(
      <PagedResultViewer
        jobId="job-4"
        pages={[{ page_num: 1 }]}
        sourceFiles={[]}
        leftPanelOpen={true}
        rightPanelOpen={true}
      />
    );
    expect(panelSpies.right).toBeTruthy();
    expect(panelSpies.right.expand).toHaveBeenCalled();
  });

  it("leftPanelOpen prop을 true→false로 변경하면 collapse()가 추가 호출된다", () => {
    const { rerender } = render(
      <PagedResultViewer
        jobId="job-5"
        pages={[{ page_num: 1 }]}
        sourceFiles={[]}
        leftPanelOpen={true}
        rightPanelOpen={true}
      />
    );
    expect(panelSpies.left.collapse).not.toHaveBeenCalled();
    act(() => {
      rerender(
        <PagedResultViewer
          jobId="job-5"
          pages={[{ page_num: 1 }]}
          sourceFiles={[]}
          leftPanelOpen={false}
          rightPanelOpen={true}
        />
      );
    });
    expect(panelSpies.left.collapse).toHaveBeenCalled();
  });
});
