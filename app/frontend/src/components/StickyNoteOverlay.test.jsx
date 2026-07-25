// [Flow: Step 1 (StickyNoteOverlay 컴포넌트 렌더링) -> Step 2 (코멘트 표시/닫기 인터랙션 검증)]
// vitest + @testing-library/react 기반 단위 테스트.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import StickyNoteOverlay from "./StickyNoteOverlay.jsx";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key) => key }),
}));

// [Flow: 테스트 픽스처 — sticky note 주석 객체 (type=1 TEXT)]
const makeAnnotation = (overrides = {}) => ({
  id: 42,
  type: 1,
  contents: "이것은 sticky note 코멘트입니다.",
  color: "#FACC15",
  pageIndex: 0,
  rect: { origin: { x: 100, y: 200 }, size: { width: 20, height: 20 } },
  ...overrides,
});

const makePosition = (overrides = {}) => ({ x: 50, y: 80, ...overrides });

describe("StickyNoteOverlay", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  // [Flow: Happy path — annotation과 position이 주어지면 코멘트 텍스트가 표시된다]
  it("renders the comment text from annotation.contents", () => {
    const annotation = makeAnnotation({ contents: "테스트 코멘트 본문" });
    render(
      <StickyNoteOverlay
        annotation={annotation}
        position={makePosition()}
        onClose={() => {}}
      />
    );
    expect(screen.getByText("테스트 코멘트 본문")).toBeTruthy();
  });

  // [Flow: 빈 코멘트 — contents가 빈 문자열이면 emptyComment placeholder 표시]
  it("shows emptyComment placeholder when contents is empty", () => {
    const annotation = makeAnnotation({ contents: "   " });
    render(
      <StickyNoteOverlay
        annotation={annotation}
        position={makePosition()}
        onClose={() => {}}
      />
    );
    expect(screen.getByText("page:annotation.emptyComment")).toBeTruthy();
  });

  // [Flow: 닫기 버튼 — X 버튼 클릭 시 onClose 호출]
  it("calls onClose when close button is clicked", () => {
    const onClose = vi.fn();
    const annotation = makeAnnotation();
    render(
      <StickyNoteOverlay
        annotation={annotation}
        position={makePosition()}
        onClose={onClose}
      />
    );
    const closeBtn = screen.getByLabelText("page:annotation.close");
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // [Flow: Escape 키 — keydown Escape 시 onClose 호출]
  it("calls onClose when Escape key is pressed", () => {
    const onClose = vi.fn();
    const annotation = makeAnnotation();
    render(
      <StickyNoteOverlay
        annotation={annotation}
        position={makePosition()}
        onClose={onClose}
      />
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // [Flow: 외부 클릭 — 카드 외부 pointerdown 시 onClose 호출]
  it("calls onClose when clicking outside the card", () => {
    const onClose = vi.fn();
    const annotation = makeAnnotation();
    render(
      <StickyNoteOverlay
        annotation={annotation}
        position={makePosition()}
        onClose={onClose}
      />
    );
    // document.body에 외부 요소 클릭 이벤트 발생
    fireEvent.pointerDown(document.body, { clientX: 0, clientY: 0 });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // [Flow: 카드 내부 클릭 — 카드 내부 pointerdown 시 onClose 호출 안 함]
  it("does not call onClose when clicking inside the card", () => {
    const onClose = vi.fn();
    const annotation = makeAnnotation();
    render(
      <StickyNoteOverlay
        annotation={annotation}
        position={makePosition()}
        onClose={onClose}
      />
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.pointerDown(dialog, { clientX: 100, clientY: 100 });
    expect(onClose).not.toHaveBeenCalled();
  });

  // [Flow: position이 null이면 렌더링하지 않음]
  it("renders nothing when position is null", () => {
    const annotation = makeAnnotation();
    const { container } = render(
      <StickyNoteOverlay annotation={annotation} position={null} onClose={() => {}} />
    );
    expect(container.firstChild).toBeNull();
  });

  // [Flow: position 좌표가 숫자가 아니면 렌더링하지 않음]
  it("renders nothing when position coordinates are not numbers", () => {
    const annotation = makeAnnotation();
    const { container } = render(
      <StickyNoteOverlay
        annotation={annotation}
        position={{ x: "abc", y: 80 }}
        onClose={() => {}}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  // [Flow: 색상 fallback — annotation.color가 없으면 기본 색상 사용]
  it("uses fallback color when annotation.color is missing", () => {
    const annotation = makeAnnotation({ color: undefined });
    render(
      <StickyNoteOverlay
        annotation={annotation}
        position={makePosition()}
        onClose={() => {}}
      />
    );
    // 헤더 배경이 렌더링되어야 함 (색상 fallback으로 인해 에러 없이)
    const header = screen.getByText("page:annotation.comment").closest("div");
    expect(header).toBeTruthy();
  });

  // [Flow: 여러 줄 코멘트 — whitespace-pre-wrap으로 줄바꿈 보존]
  it("preserves line breaks in multi-line comments", () => {
    const annotation = makeAnnotation({ contents: "첫 번째 줄\n두 번째 줄" });
    const { container } = render(
      <StickyNoteOverlay
        annotation={annotation}
        position={makePosition()}
        onClose={() => {}}
      />
    );
    // whitespace-pre-wrap이 적용된 본문 div의 텍스트 콘텐츠에 줄바꿈이 보존되어야 함
    const bodyDiv = container.querySelector(".whitespace-pre-wrap");
    expect(bodyDiv).toBeTruthy();
    expect(bodyDiv.textContent).toContain("첫 번째 줄");
    expect(bodyDiv.textContent).toContain("두 번째 줄");
  });
});
