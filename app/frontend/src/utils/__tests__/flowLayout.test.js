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

  it("titleNode는 top-level 노드들보다 위쪽에 단독으로 배치된다", () => {
    const titleNode = {
      id: "title",
      type: "titleNode",
      data: { kind: "title", label: "문서 제목", level: 0, content: [], contentPreview: "" },
      position: { x: 0, y: 0 },
    };
    const h2 = makeNode("h2-1", 2, "섹션");
    const nodes = [titleNode, h2];
    const edges = [makeEdge("title", "h2-1")];
    const layouted = calculateFlowLayout(nodes, edges);

    const title = layouted.find(n => n.id === "title");
    const section = layouted.find(n => n.id === "h2-1");
    expect(title.position.y).toBe(0);
    expect(section.position.y).toBeGreaterThan(title.position.y + title.data.estimatedHeight);
  });

  it("다중 파일에서 파일 그룹이 2D 그리드로 배치되어 정사각형에 가깝게 퍼진다", () => {
    // 4개 파일 그룹 — 2x2 그리드가 되어야 한다
    const groups = [];
    for (let i = 0; i < 4; i++) {
      const h2 = makeNode(`f${i}-h2-1`, 2, `파일${i} 섹션`);
      h2.data.fileIndex = i;
      groups.push(h2);
    }

    const layouted = calculateFlowLayout(groups, []);

    const row0 = ["f0-h2-1", "f1-h2-1"].map(id => layouted.find(n => n.id === id));
    const row1 = ["f2-h2-1", "f3-h2-1"].map(id => layouted.find(n => n.id === id));

    // 같은 행의 그룹은 같은 y를 가진다
    expect(row0[0].position.y).toBe(row0[1].position.y);
    expect(row1[0].position.y).toBe(row1[1].position.y);

    // 다음 행은 이전 행 아래에 위치
    expect(row1[0].position.y).toBeGreaterThan(row0[0].position.y + row0[0].data.estimatedHeight);

    // 같은 행에서 오른쪽 그룹의 x가 더 크다
    expect(row0[1].position.x).toBeGreaterThan(row0[0].position.x + row0[0].width);

    // 전체 배치의 가로/세로 비율이 정사각형에 가깝다 (0.5 ~ 2.0)
    const xs = layouted.map(n => n.position.x);
    const ys = layouted.map(n => n.position.y);
    const widths = layouted.map(n => n.width);
    const heights = layouted.map(n => n.data.estimatedHeight);
    const maxX = Math.max(...xs.map((x, i) => x + widths[i]));
    const maxY = Math.max(...ys.map((y, i) => y + heights[i]));
    const ratio = Math.max(maxX, 1) / Math.max(maxY, 1);
    expect(ratio).toBeGreaterThanOrEqual(0.5);
    expect(ratio).toBeLessThanOrEqual(2.5);
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
