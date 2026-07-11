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
