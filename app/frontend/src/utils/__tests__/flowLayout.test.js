// [Flow: Step 1 (테스트용 heading 노드 생성) -> Step 2 (calculateFlowLayout 호출) -> Step 3 (x/depth, y/순서, width/height 검증)]
// calculateFlowLayout이 depth 기반 들여쓰기와 페이지 순 누적 배치를 올바르게 수행하는지 검증.

import { describe, it, expect } from "vitest";
import { calculateFlowLayout } from "../flowLayout.js";

/**
 * 테스트용 heading 노드를 생성한다.
 *
 * @param {string} id - 노드 ID
 * @param {number} depth - 들여쓰기 depth
 * @param {number} level - 원본 heading level
 * @param {string} label - 제목
 * @param {string} [contentPreview] - 미리보기 텍스트
 * @returns {Object} heading 노드
 */
function baseNode(id, depth, level, label, contentPreview = "") {
  return {
    id,
    type: "headingNode",
    data: { label, depth, level, contentPreview },
    position: { x: 0, y: 0 },
  };
}

describe("calculateFlowLayout", () => {
  it("depth에 따라 x좌표가 들여쓰기된다", () => {
    const nodes = [
      baseNode("h-1", 0, 1, "Root"),
      baseNode("h-2", 1, 2, "Child"),
      baseNode("h-3", 0, 1, "Another Root"),
    ];
    const layouted = calculateFlowLayout(nodes);

    expect(layouted[0].position.x).toBe(16);
    expect(layouted[1].position.x).toBe(16 + 32);
    expect(layouted[2].position.x).toBe(16);
    expect(layouted[0].width).toBe(360);
  });

  it("노드 순서대로 y좌표가 누적된다", () => {
    const nodes = [
      baseNode("h-1", 0, 1, "A"),
      baseNode("h-2", 0, 1, "B"),
      baseNode("h-3", 0, 1, "C"),
    ];
    const layouted = calculateFlowLayout(nodes);

    expect(layouted[0].position.y).toBe(24);
    expect(layouted[1].position.y).toBeGreaterThan(layouted[0].position.y);
    expect(layouted[2].position.y).toBeGreaterThan(layouted[1].position.y);
  });

  it("contentPreview가 없으면 높이가 작고, 있으면 높이가 커진다", () => {
    const nodesWithout = [baseNode("h-1", 0, 1, "A")];
    const nodesWith = [baseNode("h-1", 0, 1, "A", "preview text line one. preview text line two.")];

    const layoutedWithout = calculateFlowLayout(nodesWithout);
    const layoutedWith = calculateFlowLayout(nodesWith);

    expect(layoutedWith[0].height).toBeGreaterThan(layoutedWithout[0].height);
    expect(layoutedWithout[0].height).toBeGreaterThan(0);
  });

  it("heading 노드는 draggable이 false로 설정된다", () => {
    const nodes = [baseNode("h-1", 0, 1, "A")];
    const layouted = calculateFlowLayout(nodes);
    expect(layouted[0].draggable).toBe(false);
  });

  it("sourcePosition과 targetPosition이 위/아래로 설정된다", () => {
    const nodes = [baseNode("h-1", 0, 1, "A")];
    const layouted = calculateFlowLayout(nodes);
    expect(layouted[0].sourcePosition).toBe("bottom");
    expect(layouted[0].targetPosition).toBe("top");
  });
});
