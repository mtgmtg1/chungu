// [Flow: Step 1 (테스트용 마크다운 생성) -> Step 2 (parseMarkdownToFlow 호출) -> Step 3 (title/nodes/edges/depth 검증)]
// parseMarkdownToFlow가 제목 추출, 페이지 순 next edge, depth 기반 들여쓰기를 올바르게 수행하는지 검증.

import { describe, it, expect } from "vitest";
import { parseMarkdownToFlow } from "../markdownToFlow.js";

/**
 * 테스트용 마크다운 문자열을 생성한다.
 *
 * @param {string[]} headings - heading 텍스트 배열
 * @returns {string} 마크다운 문자열
 */
function createMarkdown(headings) {
  return headings.map((h) => `${h}`).join("\n\n");
}

describe("parseMarkdownToFlow", () => {
  it("첫 H1을 제목으로 추출하고 노드에서 제외한다", () => {
    const markdown = createMarkdown([
      "# Contract Agreement",
      "## Section 1",
      "### 1.1 Details",
      "## Section 2",
    ]);
    const { title, nodes, edges } = parseMarkdownToFlow(markdown);

    expect(title).toBe("Contract Agreement");
    expect(nodes.length).toBe(3);
    expect(nodes[0].data.label).toBe("Section 1");
    expect(nodes[0].data.level).toBe(2);
    expect(nodes[0].data.depth).toBe(1);
    expect(nodes[1].data.label).toBe("1.1 Details");
    expect(nodes[1].data.depth).toBe(2);
    expect(nodes[2].data.label).toBe("Section 2");
    expect(nodes[2].data.depth).toBe(1);

    const hierarchyEdges = edges.filter((e) => e.type === "hierarchy");
    expect(hierarchyEdges.length).toBe(0);

    const nextEdges = edges.filter((e) => e.type === "smoothstep");
    expect(nextEdges.length).toBe(2);
    expect(nextEdges[0].source).toBe(nodes[0].id);
    expect(nextEdges[0].target).toBe(nodes[1].id);
    expect(nextEdges[1].source).toBe(nodes[1].id);
    expect(nextEdges[1].target).toBe(nodes[2].id);
  });

  it("H1이 없으면 첫 heading을 제목으로 사용한다", () => {
    const markdown = createMarkdown([
      "## First Section",
      "### Sub A",
      "## Second Section",
    ]);
    const { title, nodes } = parseMarkdownToFlow(markdown);

    expect(title).toBe("First Section");
    expect(nodes.length).toBe(2);
    expect(nodes[0].data.label).toBe("Sub A");
    expect(nodes[0].data.depth).toBe(1);
    expect(nodes[1].data.label).toBe("Second Section");
    expect(nodes[1].data.depth).toBe(0);
  });

  it("페이지 마커를 파싱해 node.data.page에 반영한다", () => {
    const markdown = `
# Title

<!-- 페이지 2 -->

## Section on page 2

<!-- 페이지 5 -->

### Sub on page 5
`;
    const { nodes } = parseMarkdownToFlow(markdown);

    expect(nodes.length).toBe(2);
    expect(nodes[0].data.page).toBe(2);
    expect(nodes[1].data.page).toBe(5);
  });

  it("빈 마크다운은 빈 노드와 null 제목을 반환한다", () => {
    const { title, nodes, edges } = parseMarkdownToFlow("");
    expect(title).toBeNull();
    expect(nodes.length).toBe(0);
    expect(edges.length).toBe(0);
  });

  it("heading 하위 본문을 contentPreview에 축적한다", () => {
    const markdown = `
# Title

## Section

This is the first paragraph.

This is the second paragraph.

## Next Section
`;
    const { nodes } = parseMarkdownToFlow(markdown);

    expect(nodes.length).toBe(2);
    expect(nodes[0].data.contentPreview).toContain("first paragraph");
    expect(nodes[0].data.contentPreview.length).toBeLessThanOrEqual(200);
  });
});
