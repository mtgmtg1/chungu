// [Flow: Step 1 (가짜 e-Discovery graph 노드 생성)
//       -> Step 2 (classifyNodesBySide 호출) -> Step 3 (원고/피고 측 주장/증거 분류 결과 검증)]
// EdiscoveryTimelinePanel이 graph 노드를 원고/피고 양측 주장·증거로 올바르게 분류하는지 검증.

import { describe, it, expect } from "vitest";
import { classifyNodesBySide } from "../../utils/ediscoveryTimelineUtils.js";

const nodes = [
  { id: "p-claim", type: "plaintiff", data: { label: "원고 주장", page: 2, entity: "plaintiff" } },
  { id: "d-claim", type: "defendant", data: { label: "피고 반박", page: 4, entity: "defendant" } },
  { id: "p-ev", type: "evidence", data: { label: "원고 증거", page: 3, entity: "plaintiff" } },
  { id: "d-ev", type: "evidence", data: { label: "피고 증거", page: 5, entity: "defendant" } },
  { id: "neutral-ev", type: "evidence", data: { label: "중립 증거", page: 6, entity: "third_party" } },
  { id: "issue", type: "issue", data: { label: "쟁점", page: 1 } },
  { id: "legacy", type: "evidence", data: { label: "구식 증거", page: 7 } },
];

describe("classifyNodesBySide", () => {
  it("원고 측에는 plaintiff 타입 + plaintiff entity 증거를 포함한다", () => {
    const { plaintiff } = classifyNodesBySide(nodes);
    const ids = plaintiff.claims.map((n) => n.id).concat(plaintiff.evidence.map((n) => n.id));
    expect(ids).toContain("p-claim");
    expect(ids).toContain("p-ev");
    expect(ids).not.toContain("d-claim");
    expect(ids).not.toContain("d-ev");
  });

  it("피고 측에는 defendant 타입 + defendant entity 증거를 포함한다", () => {
    const { defendant } = classifyNodesBySide(nodes);
    const ids = defendant.claims.map((n) => n.id).concat(defendant.evidence.map((n) => n.id));
    expect(ids).toContain("d-claim");
    expect(ids).toContain("d-ev");
    expect(ids).not.toContain("p-claim");
    expect(ids).not.toContain("p-ev");
  });

  it("entity가 없는 증거는 제3자/중립으로 분류되지 않는다", () => {
    const { plaintiff, defendant } = classifyNodesBySide(nodes);
    const allIds = plaintiff.claims.concat(plaintiff.evidence, defendant.claims, defendant.evidence).map((n) => n.id);
    expect(allIds).not.toContain("neutral-ev");
    expect(allIds).not.toContain("legacy");
    expect(allIds).not.toContain("issue");
  });

  it("빈 배열 입력 시 양측 모두 빈 claims/evidence를 반환한다", () => {
    const result = classifyNodesBySide([]);
    expect(result.plaintiff.claims).toEqual([]);
    expect(result.plaintiff.evidence).toEqual([]);
    expect(result.defendant.claims).toEqual([]);
    expect(result.defendant.evidence).toEqual([]);
  });
});
