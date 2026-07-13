// [Flow: Step 1 (ediscovery_graphs.nodes 배열 수신) -> Step 2 (plaintiff/defendant 타입 및 entity 기준 분류)
//       -> Step 3 ({ plaintiff, defendant } 객체 반환)]
// e-Discovery Timeline 패널에서 양측 주장과 증거를 분류하는 순수 유틸리티 함수 모음.

/**
 * classifyNodesBySide — e-Discovery graph 노드를 원고/피고 양측의 주장과 증거로 분류한다.
 * 플랫폼 주체 분류 규칙: 노드 타입이 plaintiff/defendant면 주장으로, type=evidence이면 entity 기준으로 배정.
 * entity가 없는 증거는 어느 측에도 속하지 않으므로 제외한다.
 *
 * @param {Array<Object>} nodes - ediscovery_graphs.nodes
 * @returns {{ plaintiff: { claims: Array<Object>, evidence: Array<Object> }, defendant: { claims: Array<Object>, evidence: Array<Object> } }} 분류 결과
 */
export function classifyNodesBySide(nodes) {
  const result = {
    plaintiff: { claims: [], evidence: [] },
    defendant: { claims: [], evidence: [] },
  };

  for (const node of nodes) {
    const type = node.type;
    const entity = node.data?.entity || "";

    if (type === "plaintiff") {
      result.plaintiff.claims.push(node);
      continue;
    }
    if (type === "defendant") {
      result.defendant.claims.push(node);
      continue;
    }
    if (type === "evidence" && entity === "plaintiff") {
      result.plaintiff.evidence.push(node);
      continue;
    }
    if (type === "evidence" && entity === "defendant") {
      result.defendant.evidence.push(node);
      continue;
    }
  }

  return result;
}
