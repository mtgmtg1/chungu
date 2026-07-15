/**
 * heading 노드 배열에 대해 트리뷰 + 페이지 순서 레이아웃을 계산한다.
 *
 * - top-level 노드(부모가 없는 노드)는 가로로 배치.
 * - top-level 노드의 자식은 해당 노드 아래로 세로 배치.
 * - H2 -> H2: 좌우, H2 -> H3: 상하.
 *
 * [Flow: Step 1 (노드/엣지 매핑 + 부모-자식 트리 구성)
 *       -> Step 2 (각 노드 크기 추정)
 *       -> Step 3 (subtree 크기 bottom-up 계산)
 *       -> Step 4 (top-level 노드 가로 배치 및 자식 세로 배치)
 *       -> Step 5 (레이아웃이 적용된 노드 배열 반환)]
 *
 * @param {Array} nodes - headingNode 객체 배열
 * @param {Array} [edges=[]] - React Flow 엣지 배열 (hierarchy 타입 기준)
 * @param {Object} [options] - 레이아웃 옵션
 * @param {number} [options.nodeWidth=360] - 노드 고정 너비
 * @param {number} [options.gapX=80] - top-level 노드 간 가로 간격
 * @param {number} [options.gapY=40] - 부모-자식 노드 간 세로 간격
 * @param {number} [options.fileGapY=120] - 파일 그룹 간 세로 간격 (다중 파일 시)
 * @param {number} [options.titleCharsPerLine=28] - 제목 한 줄당 문자 수 추정
 * @param {number} [options.previewCharsPerLine=30] - 미리보기 한 줄당 문자 수 추정
 * @param {number} [options.titleLineHeight=20] - 제목 줄 높이
 * @param {number} [options.previewLineHeight=16] - 미리보기 줄 높이
 * @param {number} [options.baseHeight=48] - 기본 높이 (패딩/배지 포함)
 * @returns {Array} position/width/height가 설정된 노드 배열
 */
export function calculateFlowLayout(nodes, edges = [], options = {}) {
  const {
    nodeWidth = 360,
    gapX = 80,
    gapY = 40,
    fileGapY = 120,
    titleCharsPerLine = 28,
    previewCharsPerLine = 30,
    titleLineHeight = 40,       // 기존 20의 2배 — 노드가 잘리지 않도록 여유 확보
    previewLineHeight = 32,     // 기존 16의 2배
    baseHeight = 96,            // 기존 48의 2배 — 패딩/배지/여백 포함
  } = options;

  // Step 1: 노드 맵과 부모-자식 트리 구성
  const nodeMap = {};
  const childrenMap = {};

  for (const node of nodes) {
    const mapped = { ...node, children: [], parentId: null };
    nodeMap[node.id] = mapped;
    childrenMap[node.id] = [];
  }

  for (const edge of edges) {
    if (edge.type === "hierarchy" && nodeMap[edge.source] && nodeMap[edge.target]) {
      nodeMap[edge.target].parentId = edge.source;
      childrenMap[edge.source].push(nodeMap[edge.target]);
    }
  }

  for (const node of nodes) {
    nodeMap[node.id].children = childrenMap[node.id];
  }

  // top-level 노드는 원본 순서를 유지
  const topLevelNodes = nodes
    .map(n => nodeMap[n.id])
    .filter(n => !n.parentId);

  // Step 2: 각 노드 크기 추정
  // contentNode는 headingNode보다 컴팩트하게 추정 (이미지 썸네일 등은 추가 높이)
  // fileNode는 파일 구분 노드로 넓게 추정
  for (const node of Object.values(nodeMap)) {
    const label = node.data.label || "";
    const preview = node.data.contentPreview || "";
    const isContent = node.data.kind === "content";
    const isFile = node.data.kind === "file";
    const isTitle = node.data.kind === "title";

    if (isTitle) {
      // 타이틀 노드 — H1 제목, 큰 폰트 + 여유 높이
      const labelLines = Math.min(2, Math.max(1, Math.ceil(label.length / titleCharsPerLine)));
      node.width = nodeWidth;
      node.height = baseHeight + titleLineHeight * labelLines + 32; // 타이틀은 추가 여백
    } else if (isFile) {
      // 파일 구분 노드 — 큰 라벨 + 여유 높이
      const labelLines = Math.min(2, Math.max(1, Math.ceil(label.length / titleCharsPerLine)));
      node.width = nodeWidth;
      node.height = baseHeight + titleLineHeight * labelLines + 20; // 추가 여백
    } else if (isContent) {
      // 콘텐츠 노드 — 라벨 2줄 + 미디어 썸네일(이미지/동영상) 추가 높이
      const labelLines = Math.min(2, Math.max(1, Math.ceil(label.length / previewCharsPerLine)));
      // 이미지/동영상 썸네일을 128px로 추정 (기존 64px의 2배)
      const mediaExtra = (node.data.contentType === "image" || node.data.contentType === "video") ? 128 : 0;
      node.width = nodeWidth;
      node.height = baseHeight + previewLineHeight * labelLines + mediaExtra;
    } else {
      const titleLines = Math.min(2, Math.max(1, Math.ceil(label.length / titleCharsPerLine)));
      const previewLines = preview ? Math.min(3, Math.max(1, Math.ceil(preview.length / previewCharsPerLine))) : 0;
      node.width = nodeWidth;
      node.height = baseHeight + titleLineHeight * titleLines + previewLineHeight * previewLines;
    }
    node.subtreeWidth = node.width;
    node.subtreeHeight = node.height;
  }

  // Step 3: subtree 크기 bottom-up 계산
  // contentNode 자식은 부모 아래 세로로 스택, headingNode 자식은 가로로 나란히 배치.
  function computeSubtree(node) {
    if (node.children.length === 0) {
      node.subtreeWidth = node.width;
      node.subtreeHeight = node.height;
      return;
    }

    // contentNode 자식과 headingNode 자식을 분리
    const contentChildren = node.children.filter(c => c.data.kind === "content");
    const headingChildren = node.children.filter(c => c.data.kind !== "content");

    // contentNode 자식은 세로 스택 — 너비는 최대값, 높이는 누적
    let contentWidth = 0;
    let contentHeight = 0;
    for (let i = 0; i < contentChildren.length; i++) {
      const child = contentChildren[i];
      computeSubtree(child);
      contentWidth = Math.max(contentWidth, child.subtreeWidth);
      contentHeight += child.subtreeHeight + (i > 0 ? gapY : 0);
    }

    // headingNode 자식은 가로 배치 — 너비는 누적, 높이는 최대값
    let headingWidth = 0;
    let headingHeight = 0;
    for (let i = 0; i < headingChildren.length; i++) {
      const child = headingChildren[i];
      computeSubtree(child);
      headingWidth += child.subtreeWidth + (i > 0 ? gapX : 0);
      headingHeight = Math.max(headingHeight, child.subtreeHeight);
    }

    // contentNode 세로 스택 아래에 headingNode 가로 배치
    const contentBlockHeight = contentHeight > 0 ? contentHeight + gapY : 0;
    const headingBlockHeight = headingHeight > 0 ? headingHeight + gapY : 0;

    node.subtreeWidth = Math.max(node.width, contentWidth, headingWidth);
    node.subtreeHeight = node.height + contentBlockHeight + headingBlockHeight;
  }

  for (const node of topLevelNodes) {
    computeSubtree(node);
  }

  // Step 4: top-level 노드 배치 — 다중 파일이면 파일별 세로 스택, 단일 파일이면 가로 배치
  // contentNode 자식은 부모 바로 아래 세로로 스택, headingNode 자식은 그 아래 가로로 배치.
  function placeNode(node, originX, originY) {
    // 부모 subtree 안에서 현재 노드를 가로 중앙에 배치
    node.position = {
      x: originX + (node.subtreeWidth - node.width) / 2,
      y: originY,
    };

    if (node.children.length === 0) return;

    // contentNode 자식과 headingNode 자식을 분리
    const contentChildren = node.children.filter(c => c.data.kind === "content");
    const headingChildren = node.children.filter(c => c.data.kind !== "content");

    // contentNode 자식들을 부모 바로 아래 세로로 스택
    let currentY = originY + node.height + gapY;
    for (const child of contentChildren) {
      placeNode(child, originX + (node.subtreeWidth - child.subtreeWidth) / 2, currentY);
      currentY += child.subtreeHeight + gapY;
    }

    // headingNode 자식들을 contentNode 스택 아래 가로로 배치
    const headingWidth = headingChildren.reduce(
      (sum, child, i) => sum + child.subtreeWidth + (i > 0 ? gapX : 0),
      0,
    );
    const headingStartX = originX + (node.subtreeWidth - headingWidth) / 2;
    let childX = headingStartX;
    for (const child of headingChildren) {
      placeNode(child, childX, currentY);
      childX += child.subtreeWidth + gapX;
    }
  }

  // [Flow: 다중 파일 세로 배치 — fileIndex별 그룹화 후 세로 스택]
  // fileIndex가 있으면 파일별로 그룹화하여 세로로 배치, fileNode는 각 파일 그룹의 최상단에 표시.
  // fileIndex가 없으면(단일 파일) 기존대로 모든 top-level 노드를 가로로 배치.
  const hasMultiFiles = topLevelNodes.some(n => n.data.fileIndex !== undefined);

  if (hasMultiFiles) {
    // fileIndex별로 그룹화 — fileNode와 heading 노드를 분리하여 관리
    const fileGroups = {};
    for (const node of topLevelNodes) {
      const fi = node.data.fileIndex ?? 0;
      if (!fileGroups[fi]) fileGroups[fi] = { fileNodes: [], headingNodes: [] };
      if (node.data.kind === "file") {
        fileGroups[fi].fileNodes.push(node);
      } else {
        fileGroups[fi].headingNodes.push(node);
      }
    }

    const sortedFileIndices = Object.keys(fileGroups).map(Number).sort((a, b) => a - b);
    let currentY = 0;

    for (const fi of sortedFileIndices) {
      const group = fileGroups[fi];
      let groupY = currentY;

      // fileNode를 해당 파일 그룹의 최상단에 배치
      if (group.fileNodes.length > 0) {
        const fn = group.fileNodes[0];
        placeNode(fn, 0, groupY);
        groupY += fn.subtreeHeight + fileGapY;
      }

      // heading 노드들을 가로로 배치 (파일 내 H2-H2 가로 흐름)
      let x = 0;
      let headingRowHeight = 0;
      for (const node of group.headingNodes) {
        placeNode(node, x, groupY);
        x += node.subtreeWidth + gapX;
        headingRowHeight = Math.max(headingRowHeight, node.subtreeHeight);
      }

      currentY = groupY + headingRowHeight + fileGapY;
    }
  } else {
    // 단일 파일: 모든 top-level 노드를 가로로 배치 (기존 동작)
    let x = 0;
    for (const node of topLevelNodes) {
      placeNode(node, x, 0);
      x += node.subtreeWidth + gapX;
    }
  }

  // Step 5: 원본 순서를 유지하며 position/width 반영
  // height는 React Flow가 실제 DOM에서 측정하도록 설정하지 않는다 (동적 높이).
  // 추정 높이는 data.estimatedHeight에 보관하여 참조용으로 사용한다.
  return nodes.map(node => {
    const m = nodeMap[node.id];
    return {
      ...node,
      position: m.position,
      width: m.width,
      // height를 설정하지 않으면 React Flow가 DOM을 측정하여 자동 결정
      data: { ...node.data, width: m.width, estimatedHeight: m.height },
      draggable: true,
    };
  });
}
