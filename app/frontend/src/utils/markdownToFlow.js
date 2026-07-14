import { marked } from "marked";

/**
 * 마크다운 문자열을 React Flow 노드/에지 배열로 변환하는 순방향 파서.
 *
 * [Flow: Step 1 (marked.lexer 토큰화) -> Step 2 (첫 H1/첫 heading을 제목으로 추출)
 *       -> Step 3 (제목을 가상 루트로 삼아 heading 노드 및 depth 생성)
 *       -> Step 4 (heading 하위 콘텐츠를 content/contentPreview에 축적)
 *       -> Step 5 (페이지 순서대로 next 에지 생성) -> Step 6 (결과 반환)]
 *
 * @param {string} markdownText - 변환할 마크다운 문자열
 * @returns {{ nodes: Array, edges: Array, title: string|null, titleLevel: number|null }} React Flow 노드/에지 배열과 제목
 */
export function parseMarkdownToFlow(markdownText) {
  // Step 1: marked.lexer로 토큰 배열 추출
  const tokens = marked.lexer(markdownText || "");

  // Step 2: 제목 heading 탐지 — 첫 H1이 있으면 그것, 없으면 첫 heading
  let titleIndex = -1;
  let title = null;
  let titleLevel = null;

  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (token.type !== "heading") continue;

    if (token.depth === 1) {
      titleIndex = i;
      title = token.text;
      titleLevel = token.depth;
      break;
    }

    if (titleIndex === -1) {
      titleIndex = i;
      title = token.text;
      titleLevel = token.depth;
    }
  }

  const nodes = [];
  const edges = [];
  const stack = []; // heading depth 스택; 제목 heading은 가상 루트로 포함
  let currentPage = 1;
  let headingIndex = 0;

  // 페이지 마커 정규식 — `<!-- 페이지 N -->` 형식
  const PAGE_MARKER_RE = /<!--\s*페이지\s*(\d+)\s*-->/i;

  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];

    if (token.type === "html" && token.text) {
      const match = token.text.match(PAGE_MARKER_RE);
      if (match) {
        currentPage = parseInt(match[1], 10) || currentPage;
      }
    }

    if (token.type !== "heading") {
      if (nodes.length === 0) continue;
      const current = nodes[nodes.length - 1];
      current.data.content.push(token);
      if (token.type === "paragraph" || token.type === "text") {
        current.data.contentPreview += (current.data.contentPreview ? " " : "") + (token.text || "");
      }
      continue;
    }

    if (i === titleIndex) {
      // Step 3: 제목 heading은 노드로 만들지 않고 depth 기준 가상 루트로만 사용
      stack.push({ level: titleLevel, isVirtual: true });
      continue;
    }

    while (stack.length > 0 && stack[stack.length - 1].level >= token.depth) {
      stack.pop();
    }

    const depth = stack.length;
    const node = {
      id: `heading-${headingIndex++}`,
      type: "headingNode",
      data: {
        label: token.text,
        level: token.depth,
        depth,
        content: [],
        contentPreview: "",
        page: currentPage,
      },
      position: { x: 0, y: 0 },
    };
    nodes.push(node);
    stack.push({ level: token.depth, id: node.id, isVirtual: false });
  }

  // Step 4: contentPreview를 200자로 제한
  nodes.forEach((node) => {
    node.data.contentPreview = (node.data.contentPreview || "").slice(0, 200);
  });

  // Step 5: 페이지 순서대로 next 에지 생성
  for (let i = 0; i < nodes.length - 1; i++) {
    const source = nodes[i];
    const target = nodes[i + 1];
    edges.push({
      id: `next-${source.id}-${target.id}`,
      source: source.id,
      target: target.id,
      type: "smoothstep",
      markerEnd: "url(#arrow-closed)",
      selectable: false,
      updatable: false,
      style: { stroke: "#6366f1", strokeWidth: 2 },
    });
  }

  // Step 6: 결과 반환
  return { nodes, edges, title, titleLevel };
}
