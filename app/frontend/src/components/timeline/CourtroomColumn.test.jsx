// [Flow: Step 1 (i18n 번역 리소스 로드) -> Step 2 (CourtroomColumn 렌더링)
//       -> Step 3 (헤더 텍스트가 기본값 또는 사용자 지정 headerKey로 렌더링되는지 검증)]
// CourtroomColumn의 주체 헤더 라벨 커스터마이징 기능을 검증하는 단위 테스트.

import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import CourtroomColumn from "./CourtroomColumn.jsx";

const plaintiffClaim = {
  id: "claim-1",
  type: "plaintiff",
  data: { label: "대여금 반환 청구", page: 3 },
};

const defendantClaim = {
  id: "claim-2",
  type: "defendant",
  data: { label: "이미 상환 완료", page: 5 },
};

describe("CourtroomColumn", () => {
  it("기본 headerKey로 원고/피고 헤더를 표시한다", () => {
    render(
      <CourtroomColumn
        side="plaintiff"
        claims={[plaintiffClaim]}
        evidence={[]}
        onNodeClick={() => {}}
      />
    );
    expect(screen.getByText("원고 · 검사")).toBeInTheDocument();
  });

  it("사용자 지정 headerKey prop을 헤더에 표시한다", () => {
    render(
      <CourtroomColumn
        side="plaintiff"
        headerKey="page:result.ediscoveryClientArguments"
        claims={[plaintiffClaim]}
        evidence={[]}
        onNodeClick={() => {}}
      />
    );
    expect(screen.getByText("CLIENT ARGUMENTS (PLAINTIFF)")).toBeInTheDocument();
  });

  it("피고 측에 사용자 지정 반박 헤더를 표시한다", () => {
    render(
      <CourtroomColumn
        side="defendant"
        headerKey="page:result.ediscoveryOpponentRebuttals"
        claims={[defendantClaim]}
        evidence={[]}
        onNodeClick={() => {}}
      />
    );
    expect(screen.getByText("OPPONENT REBUTTALS (DEFENDANT)")).toBeInTheDocument();
  });
});
