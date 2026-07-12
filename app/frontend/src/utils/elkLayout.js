import ELK from "elkjs/lib/elk.bundled.js";

const elk = new ELK();

/**
 * elkjs mrtree 알고리즘으로 React Flow 노드에 트리 형태 자동 좌표를 부여.
 * 노드 배열을 ELK JSON 그래프 형식으로 변환하여 elk.layout() 호출 후,
 * 계산된 x/y 좌표를 원본 노드에 매핑하여 반환.
 *
 * [Flow: Step 1 (ELK JSON 그래프 구성) -> Step 2 (mrtree 레이아웃 계산) -> Step 3 (좌표 매핑 반환)]
 *
 * @param {Array} nodes - React Flow 노드 배열 (position 미사용)
 * @param {Array} edges - React Flow 에지 배열
 * @returns {Promise<Array>} 좌표가 계산된 노드 배열
 */
export async function calculateElkLayout(nodes, edges) {
  if (!nodes.length) return nodes;

  // Step 1: elkjs JSON 그래프 구성 — mrtree 알고리즘으로 트리 레이아웃
  const elkGraph = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "mrtree",
      "elk.direction": "DOWN",
      "elk.spacing.nodeNode": "80",
      "elk.mrtree.nodeNodeSpacing": "80",
      "elk.mrtree.layerNodeSpacing": "100",
    },
    children: nodes.map(n => ({
      id: n.id,
      width: n.data?.width || 280,
      height: n.data?.height || 140,
    })),
    edges: edges.map(e => ({
      id: e.id,
      sources: [e.source],
      targets: [e.target],
    })),
  };

  // Step 2: layered 레이아웃 계산
  const layouted = await elk.layout(elkGraph);

  // Step 3: 계산된 좌표를 React Flow 노드에 매핑
  // width/height를 노드 최상위 속성에도 설정 — NodeResizer가 node.width/node.height를 갱신하므로
  // 내부 div가 width:100%로 래퍼에 맞춰지려면 최상위 속성이 초기값을 가져야 함
  return nodes.map(node => {
    const elkNode = layouted.children?.find(c => c.id === node.id);
    const w = elkNode?.width || node.data?.width || 280;
    const h = elkNode?.height || node.data?.height || 140;
    return {
      ...node,
      position: { x: elkNode?.x || 0, y: elkNode?.y || 0 },
      width: w,
      height: h,
      data: { ...node.data, width: w, height: h },
    };
  });
}

/**
 * elkjs layered + partitioning 알고리즘으로 스윔레인 타임라인 배치를 계산.
 * 부모 노드(swimlane) 안에 자식 노드들이 가로축(시간)을 따라 분배되도록 ELK JSON을
 * 부모-자식 중첩 구조로 구성한다. React Flow v12 마이그레이션 규칙에 따라
 * 동적 노드 크기는 node.measured.width를 우선 참조하고, 폴백으로 node.data.width를 사용.
 *
 * [Flow: Step 1 (부모/자식 노드 분리) -> Step 2 (ELK JSON 중첩 그래프 구성 - layered + partitioning)
 *       -> Step 3 (레이아웃 계산) -> Step 4 (부모/자식 좌표 매핑 - 자식은 부모 기준 상대좌표)]
 *
 * @param {Array} nodes - React Flow 노드 배열 (swimlane 부모 + parentId를 가진 자식)
 * @param {Array} edges - React Flow 에지 배열
 * @returns {Promise<Array>} 좌표가 계산된 노드 배열 (부모/자식 모두 절대좌표)
 */
export async function calculateElkSwimlaneLayout(nodes, edges) {
  if (!nodes.length) return nodes;

  // Step 1: 부모(swimlane)와 자식(parentId 보유) 분리
  const parents = nodes.filter(n => !n.parentId && n.type === "eDiscovery-swimlane");
  const children = nodes.filter(n => n.parentId);
  const parentIds = new Set(parents.map(p => p.id));

  // 부모가 없으면 평면 레이아웃으로 폴백
  if (parents.length === 0) return calculateElkLayout(nodes, edges);

  // 자식 노드 크기 결정 — v12 규칙: node.measured.width 우선, 폴백 node.data.width
  const childWidth = (n) => n.measured?.width || n.data?.width || 220;
  const childHeight = (n) => n.measured?.height || n.data?.height || 100;

  // 부모별 자식 그룹화
  const childrenByParent = new Map();
  for (const c of children) {
    if (!parentIds.has(c.parentId)) continue;
    if (!childrenByParent.has(c.parentId)) childrenByParent.set(c.parentId, []);
    childrenByParent.get(c.parentId).push(c);
  }

  // Step 2: ELK JSON 중첩 그래프 구성 — layered + partitioning
  // 부모 노드의 children 배열에 자식을 중첩하고, 자식에 partitioning activation 설정
  const elkChildren = parents.map(p => {
    const laneChildren = (childrenByParent.get(p.id) || []).map(c => ({
      id: c.id,
      width: childWidth(c),
      height: childHeight(c),
      layoutOptions: {
        "elk.partitioning.activate": "true",
        "elk.partitioning.partition": p.id,
      },
    }));
    // swimlane 폭 = 자식 수 * (자식폭 + 간격), 높이 = 자식 높이 + 패딩
    const laneWidth = Math.max(400, laneChildren.length * (220 + 40) + 40);
    const laneHeight = Math.max(160, 160);
    return {
      id: p.id,
      width: p.data?.width || laneWidth,
      height: p.data?.height || laneHeight,
      layoutOptions: {
        "elk.partitioning.activate": "true",
      },
      children: laneChildren,
    };
  });

  // 엣지는 부모 간 + 자식 간 모두 최상위 edges에 평면화 (ELK가 partitioning으로 배치)
  const elkEdges = edges
    .filter(e => {
      const sInParent = parents.some(p => p.id === e.source) || children.some(c => c.id === e.source);
      const tInParent = parents.some(p => p.id === e.target) || children.some(c => c.id === e.target);
      return sInParent && tInParent;
    })
    .map(e => ({
      id: e.id,
      sources: [e.source],
      targets: [e.target],
    }));

  const elkGraph = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.spacing.nodeNode": "60",
      "elk.layered.spacing.nodeNodeBetweenLayers": "80",
      "elk.partitioning.activate": "true",
      "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
    },
    children: elkChildren,
    edges: elkEdges,
  };

  // Step 3: 레이아웃 계산
  const layouted = await elk.layout(elkGraph);

  // Step 4: 부모/자식 좌표 매핑
  // 부모는 절대좌표, 자식은 부모 내부 상대좌표 → React Flow는 parentId 지정 시 상대좌표 사용
  const resultById = new Map();
  for (const p of layouted.children || []) {
    const parentWidth = p.width || 400;
    const parentHeight = p.height || 160;
    resultById.set(p.id, {
      x: p.x || 0,
      y: p.y || 0,
      width: parentWidth,
      height: parentHeight,
    });
    for (const c of p.children || []) {
      resultById.set(c.id, {
        x: c.x || 0,
        y: c.y || 0,
        width: c.width || 220,
        height: c.height || 100,
        parentId: p.id,
      });
    }
  }

  return nodes.map(node => {
    const pos = resultById.get(node.id);
    if (!pos) {
      // 매칭 실패 시 원본 유지
      return node;
    }
    const isParent = !node.parentId;
    return {
      ...node,
      position: { x: pos.x, y: pos.y },
      width: pos.width,
      height: pos.height,
      data: { ...node.data, width: pos.width, height: pos.height },
      // 자식 노드는 parentId 유지 (React Flow가 부모 기준 상대좌표로 해석)
    };
  });
}
