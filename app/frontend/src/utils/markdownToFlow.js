import { marked } from "marked";

/**
 * 마크다운 문자열을 React Flow 노드/에지 배열로 변환하는 순방향 파서.
 * marked.lexer()로 토큰화한 뒤 heading 토큰을 노드로, 제목은 가상 루트, heading 간 부모-자식 관계는 hierarchy 엣지,
 * 같은 등급 heading의 선후 관계는 next 엣지로 생성.
 * heading 하위의 본문/이미지/리스트/표/코드/인용/동영상 등 콘텐츠 블록도 contentNode 자식 노드로 생성한다.
 *
 * [Flow: Step 1 (marked.lexer 토큰화 + H1 제목 추출) -> Step 2 (heading 토큰을 노드로 변환)
 *       -> Step 3 (스택 기반 부모-자식 hierarchy 엣지 생성) -> Step 4 (콘텐츠 토큰을 타입별 contentNode로 그룹화)
 *       -> Step 5 (동일 등급 heading next 엣지 생성) -> Step 6 (Handle ID / has* 플래그 주입) -> Step 7 (결과 반환)]
 *
 * @param {string} markdownText - 변환할 마크다운 문자열
 * @returns {{ nodes: Array, edges: Array, title: string|null, titleLevel: number|null }} React Flow 노드/에지/제목
 */

// 콘텐츠 타입별 라벨/아이콘 매핑 — FlowViewer의 ContentNode와 대응
const CONTENT_TYPE_LABELS = {
  image: "이미지",
  video: "동영상",
  list: "목록",
  table: "표",
  code: "코드",
  quote: "인용",
  text: "본문",
  mixed: "본문",
};

/**
 * marked 토큰에서 콘텐츠 타입을 감지한다.
 * paragraph 토큰은 내부 토큰에 image가 있으면 image, 비디오 확장자 링크가 있으면 video, 그 외는 text.
 * html 토큰은 <video> 태그면 video, <img> 태그면 image, 그 외는 text.
 *
 * @param {Object} token - marked 토큰
 * @returns {string} "image" | "video" | "list" | "table" | "code" | "quote" | "text"
 */
function detectContentType(token) {
  if (token.type === "list") return "list";
  if (token.type === "table") return "table";
  if (token.type === "code") return "code";
  if (token.type === "blockquote") return "quote";

  if (token.type === "html" && token.text) {
    if (/<video[\s>]/i.test(token.text)) return "video";
    if (/<img[\s>]/i.test(token.text)) return "image";
    return "text";
  }

  if (token.type === "paragraph") {
    // 내부 토큰에 image가 있으면 image 노드
    const innerTypes = (token.tokens || []).map(t => t.type);
    if (innerTypes.includes("image")) return "image";

    // 텍스트에 비디오 확장자 링크가 있으면 video 노드
    const videoExt = /\.(mp4|webm|mov|avi|mkv|flv|wmv|m4v)(\?|$)/i;
    if (videoExt.test(token.text || "")) return "video";

    return "text";
  }

  return "text";
}

/**
 * 단일 토큰에서 라벨(미리보기용 짧은 텍스트)을 추출한다.
 * 타입별로 적절한 요약을 반환한다.
 *
 * @param {string} contentType - detectContentType 반환값
 * @param {Object} token - marked 토큰
 * @returns {string} 라벨 텍스트 (최대 80자)
 */
function extractTokenLabel(contentType, token) {
  switch (contentType) {
    case "image": {
      const imgToken = (token.tokens || []).find(t => t.type === "image");
      if (imgToken) return imgToken.text || imgToken.title || "이미지";
      return token.text?.replace(/!\[([^\]]*)\]\([^)]+\)/, "$1") || "이미지";
    }
    case "video":
      return token.text?.match(/src="([^"]+)"/)?.[1]?.split("/").pop() || "동영상";
    case "list": {
      const count = token.items?.length || 0;
      const firstItem = token.items?.[0]?.text || "";
      return `${count}개 항목 — ${firstItem.slice(0, 50)}`;
    }
    case "table": {
      const cols = token.header?.length || 0;
      const rows = token.rows?.length || 0;
      const headerText = (token.header || []).map(h => h.text).join(", ");
      return `${cols}열 × ${rows}행 — ${headerText.slice(0, 40)}`;
    }
    case "code":
      return `${token.lang || "text"} — ${(token.text || "").split("\n")[0].slice(0, 50)}`;
    case "quote":
      return (token.text || "").slice(0, 60);
    case "text":
    default:
      return (token.text || "").slice(0, 80);
  }
}

/**
 * 여러 타입의 콘텐츠 토큰 배열에서 통합 라벨을 생성한다.
 * 각 토큰의 타입별 라벨을 순서대로 결합하여 하나의 긴 미리보기 텍스트로 만든다.
 *
 * [Flow: Step 1 (각 토큰의 타입 감지) -> Step 2 (토큰별 라벨 추출) -> Step 3 (순서대로 결합)]
 *
 * @param {Object[]} tokens - heading 하위의 모든 콘텐츠 토큰 배열 (순서 보존)
 * @returns {string} 통합 라벨 텍스트
 */
function extractCombinedLabel(tokens) {
  const parts = tokens.map(token => {
    const type = detectContentType(token);
    return extractTokenLabel(type, token);
  });
  return parts.join(" | ").slice(0, 200);
}

/**
 * 콘텐츠 토큰 배열에서 포함된 모든 타입을 수집한다.
 * 단일 타입이면 해당 타입을, 여러 타입이면 "mixed"를 반환한다.
 *
 * @param {Object[]} tokens - 콘텐츠 토큰 배열
 * @returns {string} contentType ("text" | "image" | "video" | "list" | "table" | "code" | "quote" | "mixed")
 */
function detectCombinedContentType(tokens) {
  const types = new Set(tokens.map(t => detectContentType(t)));
  if (types.size === 1) return [...types][0];
  return "mixed";
}

/**
 * 콘텐츠 토큰 배열에서 타입별 세그먼트 정보를 생성한다.
 * 순서를 유지하면서 각 토큰의 타입과 라벨을 배열로 반환 — FlowViewer에서 순차 렌더링용.
 *
 * @param {Object[]} tokens - 콘텐츠 토큰 배열
 * @returns {Array<{ type: string, label: string, token: Object }>} 타입별 세그먼트 배열
 */
function buildContentSegments(tokens) {
  return tokens.map(token => ({
    type: detectContentType(token),
    label: extractTokenLabel(detectContentType(token), token),
    token,
  }));
}

export function parseMarkdownToFlow(markdownText) {
  // Step 1: marked.lexer로 토큰 배열 추출 (토큰 소모 0, 순수 파싱)
  const tokens = marked.lexer(markdownText || "");

  const nodes = [];
  const edges = [];
  const stack = []; // heading 레벨 스택 (부모 추적용, 제목은 가상 루트)
  let currentPage = 1; // 페이지 마커 추적 — `<!-- 페이지 N -->` 형식
  let headingIndex = 0; // 결정론적 ID용 heading 순번
  let contentIndex = 0; // 콘텐츠 노드용 순번

  // 페이지 마커 정규식 — 마크다운 HTML 주석에서 페이지 번호 추출
  const PAGE_MARKER_RE = /<!--\s*페이지\s*(\d+)\s*-->/i;

  // Step 1-1: 첫 H1 제목 추출 (H1이 없으면 title은 null)
  let titleIndex = -1;
  let title = null;
  let titleLevel = null;
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (token.type === "heading" && token.depth === 1) {
      titleIndex = i;
      title = token.text;
      titleLevel = token.depth;
      break;
    }
  }

  // 현재 heading에 쌓이는 모든 콘텐츠 토큰 버퍼 — 타입에 관계없이 하나의 contentNode로 통합
  let pendingContentTokens = [];

  // [Flow: Step 4-1 (버퍼에 쌓인 모든 토큰을 하나의 contentNode로 flush) -> Step 4-2 (heading 노드에 hierarchy 연결)]
  function flushContentTokens() {
    if (pendingContentTokens.length === 0) return;
    const parent = stack.length > 0 ? stack[stack.length - 1] : null;
    if (!parent) {
      pendingContentTokens = [];
      return;
    }

    // 모든 콘텐츠 토큰을 하나의 contentNode로 통합 — 타입별 세그먼트 정보 포함
    const contentType = detectCombinedContentType(pendingContentTokens);
    const segments = buildContentSegments(pendingContentTokens);
    const label = extractCombinedLabel(pendingContentTokens);
    const contentNode = {
      id: `content-${contentIndex++}`,
      type: "contentNode",
      data: {
        kind: "content",
        contentType,
        contentTypeLabel: CONTENT_TYPE_LABELS[contentType] || "본문",
        label,
        segments, // 타입별 세그먼트 배열 — FlowViewer에서 순차 렌더링용
        level: parent.data.level + 1,
        content: pendingContentTokens,
        contentPreview: label,
        page: currentPage,
      },
      position: { x: 0, y: 0 },
    };
    nodes.push(contentNode);

    edges.push({
      id: `e-${parent.id}-${contentNode.id}`,
      source: parent.id,
      target: contentNode.id,
      type: "hierarchy",
      sourceHandle: "bottom",
      targetHandle: "top",
      animated: false,
      updatable: false,
      selectable: false,
    });

    pendingContentTokens = [];
  }

  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];

    // 페이지 마커 감지 — html 토큰의 text에서 정규식 매칭
    if (token.type === "html" && token.text) {
      const match = token.text.match(PAGE_MARKER_RE);
      if (match) {
        currentPage = parseInt(match[1], 10) || currentPage;
        continue; // 페이지 마커는 콘텐츠 노드로 만들지 않음
      }
    }

    // space 토큰은 무시 (그룹화에 영향 주지 않음)
    if (token.type === "space") continue;

    if (token.type !== "heading") {
      if (nodes.length === 0) continue;

      // Step 4: 모든 콘텐츠 토큰을 타입에 관계없이 하나의 버퍼에 누적
      // heading이 바뀔 때 한 번에 flush하여 하나의 통합 contentNode로 생성
      pendingContentTokens.push(token);
      continue;
    }

    // heading 토큰 진입 시 — 쌓인 콘텐츠 버퍼를 먼저 flush
    flushContentTokens();

    if (i === titleIndex) {
      // Step 1-2: 제목 heading을 titleNode로 생성 — 캔버스 상단에 H1 제목 노드로 표시
      const titleNode = {
        id: `title-${headingIndex++}`,
        type: "titleNode",
        data: {
          kind: "title",
          label: token.text,
          level: token.depth,
          content: [],
          contentPreview: "",
          page: currentPage,
        },
        position: { x: 0, y: 0 },
      };
      nodes.push(titleNode);
      stack.push(titleNode);
      continue;
    }

    // Step 3: 부모-자식 에지 생성 (스택 기반 — 현재 depth 이상의 노드들을 pop)
    // titleNode(H1)는 level 1이므로 H2 이상에서 자동으로 상위 부모로 유지됨
    while (stack.length > 0) {
      const top = stack[stack.length - 1];
      if (top.data.level >= token.depth) {
        stack.pop();
      } else {
        break;
      }
    }

    const top = stack.length > 0 ? stack[stack.length - 1] : null;
    const parent = top || null;

    const node = {
      id: `heading-${headingIndex++}`,
      type: "headingNode",
      data: {
        kind: "heading",
        label: token.text,
        level: token.depth,        // H1=1, H2=2, ... (marked 토큰의 depth 속성)
        content: [],               // 다음 heading 전까지의 하위 토큰 (참조용)
        contentPreview: "",        // 호환성 유지 — contentNode로 분리되어 빈 값
        page: currentPage,         // 해당 heading이 속한 원본 PDF 페이지 번호
      },
      position: { x: 0, y: 0 },    // calculateFlowLayout이 계산
    };
    nodes.push(node);

    if (parent) {
      edges.push({
        id: `e-${parent.id}-${node.id}`,
        source: parent.id,
        target: node.id,
        type: "hierarchy",         // 실선 (트리 부모-자식)
        sourceHandle: "bottom",    // 부모 노드 아래쪽
        targetHandle: "top",       // 자식 노드 위쪽
        animated: false,
        updatable: false,
        selectable: false,
      });
    }

    stack.push(node);
  }

  // 마지막 heading에 쌓인 콘텐츠 버퍼 flush
  flushContentTokens();

  // contentPreview를 200자로 제한 (heading 노드는 빈 값, contentNode는 label)
  nodes.forEach(n => {
    n.data.contentPreview = (n.data.contentPreview || "").slice(0, 200);
  });

  // Step 5: 같은 부모를 가진 같은 레벨 노드들을 원본 순서대로 next 엣지로 연결
  // 부모-자식 관계(hierarchy)에는 화살표를 쓰지 않고, 동일 등급(H2-H2, H3-H3, content-content) 노드의 선후 관계만 화살표로 표시한다.
  // heading 노드는 level 기준으로, contentNode는 부모가 같으면 모두 같은 그룹으로 묶어 선후 관계를 표시한다.
  // 모든 동일 등급 next 엣지는 가로(Right -> Left) 방향으로 통일한다.

  // [Flow: Step 5-1 (hierarchy 엣지로 parentId 맵 구성) -> Step 5-2 (부모+레벨별 노드 그룹화)
  //       -> Step 5-3 (원본 순서대로 next 엣지 생성 — 항상 Right -> Left 가로 방향)]
  const parentMap = {};
  for (const edge of edges) {
    if (edge.type === "hierarchy" && !parentMap[edge.target]) {
      parentMap[edge.target] = edge.source;
    }
  }

  // 원본 순서를 보장하기 위해 nodes 배열의 인덱스로 정렬
  const orderMap = {};
  nodes.forEach((n, idx) => { orderMap[n.id] = idx; });

  // heading 노드는 level 기준으로, contentNode는 같은 부모면 같은 그룹으로 묶어 next 엣지 생성
  // contentNode끼리는 level이 아닌 부모 기준으로 묶어 순서대로 연결한다.
  const groupsByParent = {};
  for (const node of nodes) {
    const parentId = parentMap[node.id] || null;
    // heading은 level까지 키에 포함 (H2-H2, H3-H3 그룹 분리)
    // content는 level과 무관하게 같은 부모면 같은 그룹
    const levelKey = node.data.kind === "heading" ? node.data.level : "content";
    const key = `${parentId}::${levelKey}`;
    if (!groupsByParent[key]) groupsByParent[key] = [];
    groupsByParent[key].push(node);
  }

  for (const group of Object.values(groupsByParent)) {
    group.sort((a, b) => orderMap[a.id] - orderMap[b.id]);
    for (let i = 0; i < group.length - 1; i++) {
      const source = group[i];
      const target = group[i + 1];
      edges.push({
        id: `next-${source.id}-${target.id}`,
        source: source.id,
        target: target.id,
        type: "next",                // 동일 등급 heading 선후 관계 — 항상 가로
        sourceHandle: "right",       // 현재 노드 오른쪽
        targetHandle: "left",        // 다음 노드 왼쪽
        animated: false,
        updatable: false,
        selectable: false,
        markerEnd: "arrow-next",
        style: { stroke: "#6366f1", strokeWidth: 2 },
      });
    }
  }

  // Step 6: Handle 렌더링용 플래그 주입
  nodes.forEach(n => {
    n.data.hasParent = edges.some(e => e.type === "hierarchy" && e.target === n.id);
    n.data.hasChildren = edges.some(e => e.type === "hierarchy" && e.source === n.id);
    n.data.hasNext = edges.some(e => e.type === "next" && e.source === n.id);
    n.data.hasPrev = edges.some(e => e.type === "next" && e.target === n.id);
  });

  // Step 7: 결과 반환
  return { nodes, edges, title, titleLevel };
}

/**
 * 여러 파일의 마크다운을 각각 파싱하여 하나의 플로우로 결합한다.
 * 각 파일은 독립적으로 parseMarkdownToFlow로 처리되고, 파일 경계에 fileNode(파일 구분 노드)를 삽입한다.
 * 파일들은 세로로 배치되며, 이전 파일의 마지막 top-level heading과 다음 파일의 fileNode 사이에
 * next 엣지(화살표)로 선후 관계를 표시한다.
 *
 * [Flow: Step 1 (각 파일을 parseMarkdownToFlow로 파싱) -> Step 2 (노드 ID에 파일 인덱스 prefix)
 *       -> Step 3 (fileNode 삽입 + 이전 파일 마지막 heading과 next 엣지 연결) -> Step 4 (결과 병합)]
 *
 * @param {Array<{ filename: string, markdown: string }>} files - 파일별 마크다운 배열
 * @returns {{ nodes: Array, edges: Array, title: string|null, titleLevel: number|null }} 결합된 노드/에지
 */
export function parseMultiFileMarkdownToFlow(files) {
  if (!files || files.length === 0) {
    return { nodes: [], edges: [], title: null, titleLevel: null };
  }

  // 파일이 1개면 단일 파싱 결과 반환
  if (files.length === 1) {
    return parseMarkdownToFlow(files[0].markdown || "");
  }

  const allNodes = [];
  const allEdges = [];
  let combinedTitle = null;
  let combinedTitleLevel = null;

  // [Flow: Step 1 + Step 2 — 각 파일 파싱 + ID prefix 부여]
  for (let fileIdx = 0; fileIdx < files.length; fileIdx++) {
    const { filename, markdown } = files[fileIdx];
    const parsed = parseMarkdownToFlow(markdown || "");

    // 첫 번째 파일의 제목을 전체 제목으로 사용
    if (fileIdx === 0) {
      combinedTitle = parsed.title;
      combinedTitleLevel = parsed.titleLevel;
    }

    // 노드 ID에 파일 인덱스 prefix 부여 (충돌 방지)
    const idPrefix = `f${fileIdx}-`;
    const nodeIdMap = {}; // 원본 ID -> prefix된 ID
    for (const node of parsed.nodes) {
      const newId = idPrefix + node.id;
      nodeIdMap[node.id] = newId;
      allNodes.push({
        ...node,
        id: newId,
        data: {
          ...node.data,
          fileIndex: fileIdx,
          filename: filename || `파일 ${fileIdx + 1}`,
        },
      });
    }

    // 엣지 ID/source/target에 prefix 부여
    for (const edge of parsed.edges) {
      allEdges.push({
        ...edge,
        id: idPrefix + edge.id,
        source: nodeIdMap[edge.source] || edge.source,
        target: nodeIdMap[edge.target] || edge.target,
      });
    }

    // [Flow: Step 3 — fileNode 삽입 + 이전 파일 마지막 top-level heading과 연결]
    // fileNode는 각 파일의 시작을 표시하는 구분 노드 (첫 번째 파일 제외)
    if (fileIdx > 0) {
      const fileNodeId = `file-${fileIdx}`;
      const fileNode = {
        id: fileNodeId,
        type: "fileNode",
        data: {
          kind: "file",
          label: filename || `파일 ${fileIdx + 1}`,
          level: 1, // top-level
          fileIndex: fileIdx,
          filename: filename || `파일 ${fileIdx + 1}`,
          contentPreview: "",
          page: 1,
        },
        position: { x: 0, y: 0 },
      };
      allNodes.push(fileNode);

      // 이전 파일의 마지막 heading 노드 찾기 (titleNode 제외, H2/H3 중 원본 순서 마지막)
      const prevFilePrefix = `f${fileIdx - 1}-`;
      const prevFileHeadings = allNodes.filter(
        n => n.id.startsWith(prevFilePrefix) &&
             n.data.kind === "heading",
      );

      // 이전 파일의 마지막 heading과 fileNode 사이에 next 엣지 생성
      if (prevFileHeadings.length > 0) {
        const lastHeading = prevFileHeadings[prevFileHeadings.length - 1];
        allEdges.push({
          id: `next-${lastHeading.id}-${fileNodeId}`,
          source: lastHeading.id,
          target: fileNodeId,
          type: "next",
          sourceHandle: "right",
          targetHandle: "left",
          animated: false,
          updatable: false,
          selectable: false,
          markerEnd: "arrow-next",
          style: { stroke: "#6366f1", strokeWidth: 2 },
        });
      }
    }
  }

  // [Flow: Step 4 — has* 플래그 재주입 (결합된 노드/엣지 기준)]
  allNodes.forEach(n => {
    n.data.hasParent = allEdges.some(e => e.type === "hierarchy" && e.target === n.id);
    n.data.hasChildren = allEdges.some(e => e.type === "hierarchy" && e.source === n.id);
    n.data.hasNext = allEdges.some(e => e.type === "next" && e.source === n.id);
    n.data.hasPrev = allEdges.some(e => e.type === "next" && e.target === n.id);
  });

  return { nodes: allNodes, edges: allEdges, title: combinedTitle, titleLevel: combinedTitleLevel };
}
