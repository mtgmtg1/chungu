import { marked } from "marked";
import { v4 as uuidv4 } from "uuid";

/**
 * 마크다운 문자열을 React Flow 노드/에지 배열로 변환하는 순방향 파서.
 * marked.lexer()로 토큰화한 뒤 heading 토큰을 노드로, heading 간 부모-자식 관계를 에지로 생성.
 *
 * [Flow: Step 1 (marked.lexer 토큰화) -> Step 2 (heading 기준 노드 분할 + UUID 할당) -> Step 3 (스택 기반 부모-자식 에지 생성) -> Step 4 (하위 콘텐츠를 content/contentPreview에 축적) -> Step 5 (결과 반환)]
 *
 * @param {string} markdownText - 변환할 마크다운 문자열
 * @returns {{ nodes: Array, edges: Array }} React Flow 노드/에지 배열
 */
export function parseMarkdownToFlow(markdownText) {
  // Step 1: marked.lexer로 토큰 배열 추출 (토큰 소모 0, 순수 파싱)
  const tokens = marked.lexer(markdownText || "");

  const nodes = [];
  const edges = [];
  const stack = []; // heading 레벨 스택 (부모 추적용)

  for (const token of tokens) {
    if (token.type === "heading") {
      // Step 2: heading 토큰을 React Flow 노드로 변환
      const node = {
        id: uuidv4(),
        type: "headingNode",
        data: {
          label: token.text,
          level: token.depth,        // H1=1, H2=2, ... (marked 토큰의 depth 속성)
          content: [],               // 다음 heading 전까지의 하위 토큰
          contentPreview: "",        // 첫 200자 미리보기
        },
        position: { x: 0, y: 0 },    // elkjs가 계산
      };
      nodes.push(node);

      // Step 3: 부모-자식 에지 생성 (스택 기반 — 현재 depth 이상의 노드들을 pop)
      while (stack.length > 0 && stack[stack.length - 1].level >= token.depth) {
        stack.pop();
      }
      if (stack.length > 0) {
        const parent = stack[stack.length - 1];
        edges.push({
          id: `e-${parent.id}-${node.id}`,
          source: parent.id,
          target: node.id,
          type: "hierarchy",         // 실선 (커스텀 엣지 타입)
          animated: false,
        });
      }
      stack.push(node);
    } else if (nodes.length > 0) {
      // Step 4: 현재 최상위 heading 노드의 content에 하위 토큰 추가
      const current = nodes[nodes.length - 1];
      current.data.content.push(token);
      if (token.type === "paragraph" || token.type === "text") {
        current.data.contentPreview += (current.data.contentPreview ? " " : "") + (token.text || "");
      }
    }
  }

  // contentPreview를 200자로 제한
  nodes.forEach(n => {
    n.data.contentPreview = (n.data.contentPreview || "").slice(0, 200);
  });

  // Step 5: 결과 반환
  return { nodes, edges };
}
