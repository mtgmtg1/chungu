// [Flow: Step 1 (가짜 Chrono items 생성) -> Step 2 (EdiscoveryTimelineStrip 렌더링)
//       -> Step 3 (타임라인 헤더, 리사이저 핸들, Chrono 컨테이너 존재 여부 검증)]
// e-Discovery 하단 타임라인 스트립 컴포넌트의 기본 렌더링을 검증하는 단위 테스트.

import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import EdiscoveryTimelineStrip from "./EdiscoveryTimelineStrip.jsx";

const items = [
  { id: "item-1", title: "2023-03-10", cardTitle: "주장 1", cardSubtitle: "원고", cardDetailedText: "요약 1", node: {} },
  { id: "item-2", title: "2023-03-11", cardTitle: "반박 1", cardSubtitle: "피고", cardDetailedText: "요약 2", node: {} },
  { id: "item-3", title: "2023-03-12", cardTitle: "증거 1", cardSubtitle: "증거", cardDetailedText: "요약 3", node: {} },
];

describe("EdiscoveryTimelineStrip", () => {
  it("타임라인 헤더와 리사이저 핸들을 렌더링한다", () => {
    render(
      <EdiscoveryTimelineStrip
        items={items}
        activeItemIndex={0}
        onItemSelected={vi.fn()}
        timelineHeight={300}
        onResizePointerDown={vi.fn()}
        title="전체 타임라인"
      />
    );
    expect(screen.getByText("전체 타임라인")).toBeInTheDocument();
    expect(screen.getByTitle("전체 타임라인")).toBeInTheDocument();
  });

  it("React Chrono 컨테이너와 카드가 렌더링된다", () => {
    const { container } = render(
      <EdiscoveryTimelineStrip
        items={items}
        activeItemIndex={0}
        onItemSelected={vi.fn()}
        timelineHeight={300}
        onResizePointerDown={vi.fn()}
        title="전체 타임라인"
      />
    );
    const chronoSection = container.querySelector('[data-oid="ediscovery-chrono-section"]');
    const chrono = container.querySelector('[data-oid="ediscovery-chrono"]');
    expect(chronoSection).toBeInTheDocument();
    expect(chrono).toBeInTheDocument();
  });

  it("items가 비어 있으면 Chrono 컨테이너를 렌더링하지 않는다", () => {
    const { container } = render(
      <EdiscoveryTimelineStrip
        items={[]}
        activeItemIndex={0}
        onItemSelected={vi.fn()}
        timelineHeight={300}
        onResizePointerDown={vi.fn()}
        title="전체 타임라인"
      />
    );
    const chrono = container.querySelector('[data-oid="ediscovery-chrono"]');
    expect(chrono).not.toBeInTheDocument();
  });
});
