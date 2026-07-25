// [Flow: Step 1 (삭제된 주석 ID 추출 헬퍼 단위 테스트) -> Step 2 (Happy Path + edge case 검증)]
import { describe, it, expect } from "vitest";
import { computeRemovedAnnotationIds, extractAnnotationId } from "./annotationDiffUtils.js";

describe("extractAnnotationId", () => {
  it("annotation.id 가 있으면 추출한다", () => {
    const item = { annotation: { id: "ann-1", type: 9, pageIndex: 0 } };
    expect(extractAnnotationId(item)).toBe("ann-1");
  });

  it("annotation 래퍼가 없으면 최상위 id 를 추출한다", () => {
    const item = { id: "ann-2", type: 9, pageIndex: 0 };
    expect(extractAnnotationId(item)).toBe("ann-2");
  });

  it("dict 가 아니면 빈 문자열을 반환한다", () => {
    expect(extractAnnotationId(null)).toBe("");
    expect(extractAnnotationId("not-an-object")).toBe("");
    expect(extractAnnotationId(42)).toBe("");
  });

  it("id 가 없으면 빈 문자열을 반환한다", () => {
    expect(extractAnnotationId({ annotation: { type: 9 } })).toBe("");
    expect(extractAnnotationId({ type: 9 })).toBe("");
  });
});

describe("computeRemovedAnnotationIds", () => {
  // [Flow: Happy Path — previous 에는 있고 current 에는 없는 ID가 removals]
  it("삭제된 주석 ID만 removals 로 반환한다", () => {
    const previous = [
      { annotation: { id: "a", type: 9, pageIndex: 0 } },
      { annotation: { id: "b", type: 9, pageIndex: 0 } },
      { annotation: { id: "c", type: 9, pageIndex: 0 } },
    ];
    const current = [
      { annotation: { id: "a", type: 9, pageIndex: 0 } },
      { annotation: { id: "c", type: 9, pageIndex: 0 } },
    ];
    expect(computeRemovedAnnotationIds(previous, current).sort()).toEqual(["b"]);
  });

  it("삭제가 없으면 빈 배열을 반환한다", () => {
    const previous = [
      { annotation: { id: "a", type: 9, pageIndex: 0 } },
    ];
    const current = [
      { annotation: { id: "a", type: 9, pageIndex: 0 } },
    ];
    expect(computeRemovedAnnotationIds(previous, current)).toEqual([]);
  });

  it("새로 추가된 주석은 removals 에 포함되지 않는다", () => {
    const previous = [
      { annotation: { id: "a", type: 9, pageIndex: 0 } },
    ];
    const current = [
      { annotation: { id: "a", type: 9, pageIndex: 0 } },
      { annotation: { id: "new", type: 9, pageIndex: 0 } },
    ];
    expect(computeRemovedAnnotationIds(previous, current)).toEqual([]);
  });

  it("previous 가 null 이면 빈 배열을 반환한다", () => {
    const current = [{ annotation: { id: "a", type: 9, pageIndex: 0 } }];
    expect(computeRemovedAnnotationIds(null, current)).toEqual([]);
  });

  it("current 가 null 이면 previous 의 모든 ID를 removals 로 반환한다", () => {
    const previous = [
      { annotation: { id: "a", type: 9, pageIndex: 0 } },
      { annotation: { id: "b", type: 9, pageIndex: 0 } },
    ];
    expect(computeRemovedAnnotationIds(previous, null).sort()).toEqual(["a", "b"]);
  });

  it("둘 다 비어 있으면 빈 배열을 반환한다", () => {
    expect(computeRemovedAnnotationIds([], [])).toEqual([]);
    expect(computeRemovedAnnotationIds(null, null)).toEqual([]);
  });

  it("ID가 없는 항목은 무시한다", () => {
    const previous = [
      { annotation: { id: "a", type: 9, pageIndex: 0 } },
      { annotation: { type: 9, pageIndex: 0 } }, // id 없음
    ];
    const current = [];
    expect(computeRemovedAnnotationIds(previous, current)).toEqual(["a"]);
  });

  it("래퍼 없는 최상위 id 형식도 처리한다", () => {
    const previous = [
      { id: "x", type: 9, pageIndex: 0 },
      { id: "y", type: 9, pageIndex: 0 },
    ];
    const current = [{ id: "x", type: 9, pageIndex: 0 }];
    expect(computeRemovedAnnotationIds(previous, current)).toEqual(["y"]);
  });
});
