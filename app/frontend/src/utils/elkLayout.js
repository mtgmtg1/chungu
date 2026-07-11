import ELK from "elkjs/lib/elk.bundled.js";

const elk = new ELK();

/**
 * elkjs layered 알고리즘으로 React Flow 노드에 자동 좌표를 부여.
 * 노드 배열을 ELK JSON 그래프 형식으로 변환하여 elk.layout() 호출 후,
 * 계산된 x/y 좌표를 원본 노드에 매핑하여 반환.
 *
 * [Flow: Step 1 (ELK JSON 그래프 구성) -> Step 2 (layered 레이아웃 계산) -> Step 3 (좌표 매핑 반환)]
 *
 * @param {Array} nodes - React Flow 노드 배열 (position 미사용)
 * @param {Array} edges - React Flow 에지 배열
 * @returns {Promise<Array>} 좌표가 계산된 노드 배열
 */
export async function calculateElkLayout(nodes, edges) {
  if (!nodes.length) return nodes;

  // Step 1: elkjs JSON 그래프 구성
  const elkGraph = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "DOWN",
      "elk.spacing.nodeNode": "80",
      "elk.layered.spacing.nodeNodeBetweenLayers": "100",
      "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
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
  return nodes.map(node => {
    const elkNode = layouted.children?.find(c => c.id === node.id);
    return {
      ...node,
      position: { x: elkNode?.x || 0, y: elkNode?.y || 0 },
    };
  });
}
