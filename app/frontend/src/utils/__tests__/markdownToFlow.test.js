// [Flow: Step 1 (테스트용 마크다운 문자열 준비) -> Step 2 (parseMarkdownToFlow 파싱) -> Step 3 (노드/엣지/제목/플래그 검증)]
// parseMarkdownToFlow가 마크다운 heading 구조를 올바른 트리 + 페이지 순서 엣지로 변환하는지 검증.

import { describe, it, expect } from "vitest";
import { parseMarkdownToFlow, parseMultiFileMarkdownToFlow } from "../markdownToFlow.js";

/**
 * 테스트용 마크다운 문자열을 생성한다.
 *
 * @returns {string} 테스트용 마크다운
 */
function getTestMarkdown() {
  return `# 문서 제목

<!-- 페이지 1 -->

## 쟁점 1

쟁점 1 본문입니다.

### 주장 1-1

주장 1-1 내용입니다.

### 주장 1-2

주장 1-2 내용입니다.

<!-- 페이지 2 -->

## 쟁점 2

쟁점 2 본문입니다.

### 주장 2-1

주장 2-1 내용입니다.
`;
}

describe("parseMarkdownToFlow", () => {
  it("H1을 titleNode로 생성하고 title/titleLevel을 추출한다", () => {
    const { nodes, title, titleLevel } = parseMarkdownToFlow(getTestMarkdown());
    expect(title).toBe("문서 제목");
    expect(titleLevel).toBe(1);
    // H1이 titleNode(kind="title")로 노드에 포함되어야 함
    const titleNode = nodes.find(n => n.data.kind === "title");
    expect(titleNode).toBeDefined();
    expect(titleNode.data.label).toBe("문서 제목");
    expect(titleNode.type).toBe("titleNode");
  });

  it("H2 노드를 top-level로 생성한다", () => {
    const { nodes } = parseMarkdownToFlow(getTestMarkdown());
    const h2Labels = nodes.filter(n => n.data.level === 2).map(n => n.data.label);
    expect(h2Labels).toEqual(["쟁점 1", "쟁점 2"]);
  });

  it("H2 노드 사이에 next 엣지가 생성된다", () => {
    const { edges, nodes } = parseMarkdownToFlow(getTestMarkdown());
    const issue1 = nodes.find(n => n.data.label === "쟁점 1");
    const issue2 = nodes.find(n => n.data.label === "쟁점 2");
    const nextEdge = edges.find(e => e.type === "next" && e.source === issue1.id && e.target === issue2.id);
    expect(nextEdge).toBeDefined();
    expect(nextEdge.sourceHandle).toBe("right");
    expect(nextEdge.targetHandle).toBe("left");
    expect(nextEdge.markerEnd).toBe("arrow-next");
  });

  it("H3 형제 노드 사이에 next 엣지가 생성된다", () => {
    const { edges, nodes } = parseMarkdownToFlow(getTestMarkdown());
    const claim1 = nodes.find(n => n.data.label === "주장 1-1");
    const claim2 = nodes.find(n => n.data.label === "주장 1-2");
    const nextEdge = edges.find(e => e.type === "next" && e.source === claim1.id && e.target === claim2.id);
    expect(nextEdge).toBeDefined();
    expect(nextEdge.sourceHandle).toBe("right");
    expect(nextEdge.targetHandle).toBe("left");
    expect(nextEdge.markerEnd).toBe("arrow-next");
  });

  it("H2 -> H3 hierarchy 엣지가 생성된다", () => {
    const { edges, nodes } = parseMarkdownToFlow(getTestMarkdown());
    const issue1 = nodes.find(n => n.data.label === "쟁점 1");
    const claim1 = nodes.find(n => n.data.label === "주장 1-1");
    const hierarchyEdge = edges.find(e => e.type === "hierarchy" && e.source === issue1.id && e.target === claim1.id);
    expect(hierarchyEdge).toBeDefined();
    expect(hierarchyEdge.sourceHandle).toBe("bottom");
    expect(hierarchyEdge.targetHandle).toBe("top");
  });

  it("노드에 hasParent/hasChildren/hasNext/hasPrev 플래그가 주입된다", () => {
    const { nodes } = parseMarkdownToFlow(getTestMarkdown());
    const issue1 = nodes.find(n => n.data.label === "쟁점 1");
    const claim1 = nodes.find(n => n.data.label === "주장 1-1");
    const issue2 = nodes.find(n => n.data.label === "쟁점 2");

    // H2 노드들은 이제 titleNode(H1)를 부모로 가짐
    expect(issue1.data.hasParent).toBe(true);
    expect(issue1.data.hasChildren).toBe(true);
    expect(issue1.data.hasNext).toBe(true);
    expect(issue1.data.hasPrev).toBe(false);

    expect(claim1.data.hasParent).toBe(true);
    // 주장 1-1 아래에 본문 contentNode가 있으므로 hasChildren=true
    expect(claim1.data.hasChildren).toBe(true);
    expect(claim1.data.hasNext).toBe(true);
    expect(claim1.data.hasPrev).toBe(false);

    const claim2 = nodes.find(n => n.data.label === "주장 1-2");
    expect(claim2.data.hasParent).toBe(true);
    // 주장 1-2 아래에도 본문 contentNode가 있으므로 hasChildren=true
    expect(claim2.data.hasChildren).toBe(true);
    expect(claim2.data.hasNext).toBe(false);
    expect(claim2.data.hasPrev).toBe(true);

    expect(issue2.data.hasNext).toBe(false);
    expect(issue2.data.hasPrev).toBe(true);
  });

  it("페이지 마커를 기준으로 노드의 page 값이 설정된다", () => {
    const { nodes } = parseMarkdownToFlow(getTestMarkdown());
    const issue1 = nodes.find(n => n.data.label === "쟁점 1");
    const issue2 = nodes.find(n => n.data.label === "쟁점 2");
    const claim2 = nodes.find(n => n.data.label === "주장 2-1");

    expect(issue1.data.page).toBe(1);
    expect(issue2.data.page).toBe(2);
    expect(claim2.data.page).toBe(2);
  });

  it("contentPreview가 200자 이내로 축약된다", () => {
    const { nodes } = parseMarkdownToFlow(getTestMarkdown());
    // heading 노드의 contentPreview는 contentNode 분리 후 빈 값이지만,
    // contentNode의 contentPreview(label)는 200자 이내여야 한다
    const contentNodes = nodes.filter(n => n.data.kind === "content");
    for (const cn of contentNodes) {
      expect(cn.data.contentPreview.length).toBeLessThanOrEqual(200);
    }
  });

  it("H1이 없으면 title은 null이고 모든 heading은 노드가 된다", () => {
    const markdown = `## 첫 번째\n\n### 하위\n\n## 두 번째\n`;
    const { nodes, title, titleLevel } = parseMarkdownToFlow(markdown);
    expect(title).toBeNull();
    expect(titleLevel).toBeNull();
    const headingLabels = nodes.filter(n => n.data.kind === "heading").map(n => n.data.label);
    expect(headingLabels).toEqual(["첫 번째", "하위", "두 번째"]);
  });

  it("본문 토큰이 contentNode(text)로 생성된다", () => {
    const { nodes } = parseMarkdownToFlow(getTestMarkdown());
    const textNodes = nodes.filter(n => n.data.kind === "content" && n.data.contentType === "text");
    expect(textNodes.length).toBeGreaterThan(0);
    // "쟁점 1 본문입니다"를 포함하는 contentNode가 있어야 함
    const issue1Text = textNodes.find(n => n.data.label.includes("쟁점 1 본문"));
    expect(issue1Text).toBeDefined();
  });

  it("이미지/리스트/표/코드/인용 콘텐츠가 통합 contentNode의 segments에 포함된다", () => {
    const md = `# 제목

## 섹션

![설명](https://example.com/img.png)

- 항목 A
- 항목 B

| A | B |
|---|---|
| 1 | 2 |

` + "```js\nconst x = 1;\n```\n\n" + `> 인용구

<video src="https://example.com/v.mp4" />
`;
    const { nodes } = parseMarkdownToFlow(md);
    const contentNodes = nodes.filter(n => n.data.kind === "content");

    // heading별로 하나의 통합 contentNode가 생성됨
    expect(contentNodes.length).toBe(1);
    const cn = contentNodes[0];
    // contentType은 여러 타입이 섞였으므로 "mixed"
    expect(cn.data.contentType).toBe("mixed");
    // segments 배열에 각 타입이 포함되어야 함
    const segTypes = (cn.data.segments || []).map(s => s.type);
    expect(segTypes).toContain("image");
    expect(segTypes).toContain("list");
    expect(segTypes).toContain("table");
    expect(segTypes).toContain("code");
    expect(segTypes).toContain("quote");
    expect(segTypes).toContain("video");
  });

  it("contentNode는 부모 heading에 hierarchy 엣지로 연결된다", () => {
    const { nodes, edges } = parseMarkdownToFlow(getTestMarkdown());
    const issue1 = nodes.find(n => n.data.label === "쟁점 1");
    const issue1Content = nodes.find(n => n.data.kind === "content" && n.data.label.includes("쟁점 1 본문"));
    expect(issue1Content).toBeDefined();
    const hierarchyEdge = edges.find(
      e => e.type === "hierarchy" && e.source === issue1.id && e.target === issue1Content.id,
    );
    expect(hierarchyEdge).toBeDefined();
    expect(hierarchyEdge.sourceHandle).toBe("bottom");
    expect(hierarchyEdge.targetHandle).toBe("top");
  });

  it("같은 부모 아래 통합 contentNode가 하나만 생성된다", () => {
    const md = `# 제목

## 섹션

본문 1입니다.

![이미지](https://example.com/img.png)

- 항목 A
- 항목 B

> 인용구
`;
    const { nodes, edges } = parseMarkdownToFlow(md);
    const contentNodes = nodes.filter(n => n.data.kind === "content");
    // heading별로 하나의 통합 contentNode가 생성됨
    expect(contentNodes.length).toBe(1);
    // 통합 contentNode는 부모 heading에 hierarchy 엣지로 연결됨
    const section = nodes.find(n => n.data.label === "섹션");
    const hierarchyEdge = edges.find(
      e => e.type === "hierarchy" && e.source === section.id && e.target === contentNodes[0].id,
    );
    expect(hierarchyEdge).toBeDefined();
  });

  it("통합 contentNode에 hasParent 플래그가 주입된다", () => {
    const md = `# 제목

## 섹션

본문 1입니다.

![이미지](https://example.com/img.png)

- 항목 A
- 항목 B
`;
    const { nodes } = parseMarkdownToFlow(md);
    const contentNodes = nodes.filter(n => n.data.kind === "content");
    // heading별로 하나의 통합 contentNode
    expect(contentNodes.length).toBe(1);
    // 통합 contentNode는 부모 heading에 연결되므로 hasParent=true
    expect(contentNodes[0].data.hasParent).toBe(true);
  });
});

describe("parseMultiFileMarkdownToFlow", () => {
  it("파일이 1개면 단일 파싱 결과와 동일하다", () => {
    const files = [{ filename: "a.md", markdown: "# 제목\n\n## 섹션\n\n본문\n" }];
    const multi = parseMultiFileMarkdownToFlow(files);
    const single = parseMarkdownToFlow(files[0].markdown);
    expect(multi.nodes.length).toBe(single.nodes.length);
    expect(multi.title).toBe(single.title);
  });

  it("파일이 0개면 빈 결과를 반환한다", () => {
    const result = parseMultiFileMarkdownToFlow([]);
    expect(result.nodes).toEqual([]);
    expect(result.edges).toEqual([]);
  });

  it("다중 파일에서 fileNode가 생성되고 next 엣지로 연결된다", () => {
    const files = [
      { filename: "file1.md", markdown: "# 문서1\n\n## 섹션 A\n\n본문 A\n" },
      { filename: "file2.md", markdown: "# 문서2\n\n## 섹션 B\n\n본문 B\n" },
    ];
    const { nodes, edges } = parseMultiFileMarkdownToFlow(files);

    // fileNode가 1개 있어야 함 (두 번째 파일 앞)
    const fileNodes = nodes.filter(n => n.data.kind === "file");
    expect(fileNodes.length).toBe(1);
    expect(fileNodes[0].data.label).toBe("file2.md");

    // fileNode와 이전 파일의 마지막 top-level heading 사이에 next 엣지가 있어야 함
    const fileNode = fileNodes[0];
    const nextEdgeToFile = edges.find(
      e => e.type === "next" && e.target === fileNode.id,
    );
    expect(nextEdgeToFile).toBeDefined();
    expect(nextEdgeToFile.sourceHandle).toBe("right");
    expect(nextEdgeToFile.targetHandle).toBe("left");
  });

  it("다중 파일의 노드 ID가 충돌하지 않는다", () => {
    const files = [
      { filename: "file1.md", markdown: "## 섹션\n\n본문\n" },
      { filename: "file2.md", markdown: "## 섹션\n\n본문\n" },
    ];
    const { nodes } = parseMultiFileMarkdownToFlow(files);
    const ids = nodes.map(n => n.id);
    const uniqueIds = new Set(ids);
    expect(ids.length).toBe(uniqueIds.size);
  });

  it("각 노드에 fileIndex와 filename이 주입된다", () => {
    const files = [
      { filename: "file1.md", markdown: "## 섹션 A\n" },
      { filename: "file2.md", markdown: "## 섹션 B\n" },
    ];
    const { nodes } = parseMultiFileMarkdownToFlow(files);
    const file0Nodes = nodes.filter(n => n.data.fileIndex === 0);
    const file1Nodes = nodes.filter(n => n.data.fileIndex === 1);
    expect(file0Nodes.length).toBeGreaterThan(0);
    expect(file1Nodes.length).toBeGreaterThan(0);
    expect(file0Nodes[0].data.filename).toBe("file1.md");
    expect(file1Nodes[0].data.filename).toBe("file2.md");
  });
});
