// [Flow: Step 1 (테스트용 노드/엣지 생성) -> Step 2 (calculateFlowLayout 호출) -> Step 3 (좌표/크기/계층 검증)]
// calculateFlowLayout이 top-level H2는 가로로, H3 자식은 부모 아래 세로로 배치하는지 검증.

import { describe, it, expect } from "vitest";
import { calculateFlowLayout } from "../flowLayout.js";

/**
 * 테스트용 heading 노드를 생성한다.
 *
 * @param {string} id - 노드 ID
 * @param {number} level - heading 레벨
 * @param {string} label - 라벨
 * @param {string} [preview] - contentPreview
 * @returns {Object} headingNode
 */
function makeNode(id, level, label, preview = "") {
  return {
    id,
    type: "headingNode",
    data: {
      label,
      level,
      contentPreview: preview,
      content: [],
    },
    position: { x: 0, y: 0 },
  };
}

/**
 * 테스트용 hierarchy 엣지를 생성한다.
 *
 * @param {string} source - 부모 노드 ID
 * @param {string} target - 자식 노드 ID
 * @returns {Object} hierarchy 엣지
 */
function makeEdge(source, target) {
  return {
    id: `e-${source}-${target}`,
    source,
    target,
    type: "hierarchy",
  };
}

describe("calculateFlowLayout", () => {
  it("top-level H2 노드는 가로로(y=0) 배치되고 x가 증가한다", () => {
    const nodes = [makeNode("h2-1", 2, "H2-1"), makeNode("h2-2", 2, "H2-2")];
    const layouted = calculateFlowLayout(nodes, []);

    const first = layouted.find(n => n.id === "h2-1");
    const second = layouted.find(n => n.id === "h2-2");

    expect(first.position.y).toBe(0);
    expect(second.position.y).toBe(0);
    expect(second.position.x).toBeGreaterThan(first.position.x);
  });

  it("H3 자식 노드는 H2 부모 아래 세로로 배치된다", () => {
    const issue = makeNode("h2-1", 2, "쟁점");
    const claim = makeNode("h3-1", 3, "주장");
    const nodes = [issue, claim];
    const edges = [makeEdge("h2-1", "h3-1")];
    const layouted = calculateFlowLayout(nodes, edges);

    const issueNode = layouted.find(n => n.id === "h2-1");
    const claimNode = layouted.find(n => n.id === "h3-1");

    expect(claimNode.position.y).toBeGreaterThan(issueNode.position.y + issueNode.data.estimatedHeight);
    expect(claimNode.position.x).toBe(issueNode.position.x);
  });

  it("형제 H3 노드는 가로로 순서대로 배치된다", () => {
    const issue = makeNode("h2-1", 2, "쟁점");
    const claim1 = makeNode("h3-1", 3, "주장 1");
    const claim2 = makeNode("h3-2", 3, "주장 2");
    const nodes = [issue, claim1, claim2];
    const edges = [makeEdge("h2-1", "h3-1"), makeEdge("h2-1", "h3-2")];
    const layouted = calculateFlowLayout(nodes, edges);

    const c1 = layouted.find(n => n.id === "h3-1");
    const c2 = layouted.find(n => n.id === "h3-2");

    // 형제 노드는 같은 y(부모 아래)에 가로로 배치
    expect(c1.position.y).toBe(c2.position.y);
    expect(c2.position.x).toBeGreaterThan(c1.position.x + c1.width);
  });

  it("top-level H2 노드 사이 겹침이 없도록 충분한 가로 간격이 확보된다", () => {
    const nodes = [makeNode("h2-1", 2, "H2-1"), makeNode("h2-2", 2, "H2-2"), makeNode("h2-3", 2, "H2-3")];
    const layouted = calculateFlowLayout(nodes, []);

    const sorted = [...layouted].sort((a, b) => a.position.x - b.position.x);
    for (let i = 0; i < sorted.length - 1; i++) {
      expect(sorted[i + 1].position.x).toBeGreaterThanOrEqual(sorted[i].position.x + sorted[i].width);
    }
  });

  it("모든 노드에 width와 estimatedHeight가 설정된다", () => {
    const nodes = [makeNode("h2-1", 2, "H2-1"), makeNode("h3-1", 3, "H3-1", "미리보기")];
    const edges = [makeEdge("h2-1", "h3-1")];
    const layouted = calculateFlowLayout(nodes, edges);

    for (const node of layouted) {
      expect(node.width).toBeGreaterThan(0);
      // height는 React Flow가 DOM에서 측정하므로 설정하지 않음
      // estimatedHeight는 레이아웃 계산용 추정값으로 존재
      expect(node.data.estimatedHeight).toBeGreaterThan(0);
    }
  });

  it("다중 파일에서 파일 그룹이 세로로 스택된다", () => {
    // 파일 0의 heading 노드들
    const f0h2 = makeNode("f0-h2-1", 2, "파일0 섹션");
    f0h2.data.fileIndex = 0;
    // 파일 1의 fileNode
    const fileNode = {
      id: "file-1",
      type: "fileNode",
      data: { kind: "file", label: "file2.md", level: 1, fileIndex: 1, contentPreview: "", content: [] },
      position: { x: 0, y: 0 },
    };
    // 파일 1의 heading 노드들
    const f1h2 = makeNode("f1-h2-1", 2, "파일1 섹션");
    f1h2.data.fileIndex = 1;

    const nodes = [f0h2, fileNode, f1h2];
    const layouted = calculateFlowLayout(nodes, []);

    const f0Node = layouted.find(n => n.id === "f0-h2-1");
    const fnNode = layouted.find(n => n.id === "file-1");
    const f1Node = layouted.find(n => n.id === "f1-h2-1");

    // 파일 0의 heading이 가장 위 (y=0)
    expect(f0Node.position.y).toBe(0);
    // fileNode가 파일 0보다 아래에 위치
    expect(fnNode.position.y).toBeGreaterThan(f0Node.position.y + f0Node.data.estimatedHeight);
    // 파일 1의 heading이 fileNode보다 아래에 위치
    expect(f1Node.position.y).toBeGreaterThan(fnNode.position.y + fnNode.data.estimatedHeight);
  });

  it("다중 파일에서 같은 파일의 heading 노드들은 가로로 배치된다", () => {
    const f0h2a = makeNode("f0-h2-1", 2, "섹션 A");
    f0h2a.data.fileIndex = 0;
    const f0h2b = makeNode("f0-h2-2", 2, "섹션 B");
    f0h2b.data.fileIndex = 0;

    const nodes = [f0h2a, f0h2b];
    const layouted = calculateFlowLayout(nodes, []);

    const a = layouted.find(n => n.id === "f0-h2-1");
    const b = layouted.find(n => n.id === "f0-h2-2");

    // 같은 파일 내에서는 가로로 배치 (같은 y, x가 증가)
    expect(a.position.y).toBe(b.position.y);
    expect(b.position.x).toBeGreaterThan(a.position.x);
  });
});
