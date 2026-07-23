// [Flow: Step 1 (MarkdownDiffApproval 컴포넌트 렌더링)
//       -> Step 2 (diff 표시 확인 — 추가/삭제 라인 색상)
//       -> Step 3 (수락 클릭 -> api.saveResultPage 호출 -> onApprove 콜백)
//       -> Step 4 (거부 클릭 -> onDeny 콜백, 저장 API 미호출)]
// 마크다운 AI 편집 diff 승인 컴포넌트의 핵심 동작을 검증하는 테스트.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import MarkdownDiffApproval from "./MarkdownDiffApproval.jsx";

// [Flow: api.saveResultPage 를 모의 — 호출 인수 기록]
const saveResultPageMock = vi.fn(() => Promise.resolve({}));

vi.mock("../../api.js", () => ({
  api: {
    saveResultPage: (...args) => saveResultPageMock(...args),
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key, fallback) => fallback || key }),
}));

beforeEach(() => {
  saveResultPageMock.mockClear();
  saveResultPageMock.mockResolvedValue({});
});

describe("MarkdownDiffApproval", () => {
  const baseProps = {
    jobId: "job-123",
    pageNum: 2,
    originalMarkdown: "# 제목\n\n기존 내용입니다.\n",
    editedMarkdown: "# 제목\n\n새로운 내용입니다.\n\n추가된 줄.\n",
    onApprove: vi.fn(),
    onDeny: vi.fn(),
  };

  it("diff를 표시한다 — 추가 라인과 삭제 라인이 모두 보인다", () => {
    render(<MarkdownDiffApproval {...baseProps} />);
    // [Flow: 추가된 텍스트와 삭제된 텍스트가 diff에 표시되는지 확인]
    // 추가 라인(녹색 배경)에 새 텍스트가, 삭제 라인(적색 배경)에旧 텍스트가 표시됨
    expect(screen.getByText("새로운 내용입니다.")).toBeInTheDocument();
    expect(screen.getByText("기존 내용입니다.")).toBeInTheDocument();
    expect(screen.getByText("추가된 줄.")).toBeInTheDocument();
  });

  it("수락 클릭 시 api.saveResultPage 를 호출하고 onApprove 콜백을 실행한다", async () => {
    const onApprove = vi.fn();
    render(<MarkdownDiffApproval {...baseProps} onApprove={onApprove} />);

    fireEvent.click(screen.getByTestId("markdown-diff-accept"));

    // [Flow: 저장 API 가 올바른 인수로 호출되었는지 검증]
    await waitFor(() => {
      expect(saveResultPageMock).toHaveBeenCalledTimes(1);
    });
    expect(saveResultPageMock).toHaveBeenCalledWith(
      "job-123",
      2,
      baseProps.editedMarkdown,
    );
    // [Flow: 승인 콜백이 호출되었는지 검증]
    await waitFor(() => {
      expect(onApprove).toHaveBeenCalledTimes(1);
    });
  });

  it("거부 클릭 시 저장 API 를 호출하지 않고 onDeny 콜백만 실행한다", () => {
    const onDeny = vi.fn();
    render(<MarkdownDiffApproval {...baseProps} onDeny={onDeny} />);

    fireEvent.click(screen.getByTestId("markdown-diff-reject"));

    // [Flow: 저장 API 가 호출되지 않아야 함]
    expect(saveResultPageMock).not.toHaveBeenCalled();
    // [Flow: 거부 콜백이 호출되어야 함]
    expect(onDeny).toHaveBeenCalledTimes(1);
  });

  it("저장 실패 시 에러 메시지를 표시한다", async () => {
    saveResultPageMock.mockRejectedValue(new Error("네트워크 오류"));
    render(<MarkdownDiffApproval {...baseProps} />);

    fireEvent.click(screen.getByTestId("markdown-diff-accept"));

    // [Flow: 에러 메시지가 표시되는지 확인]
    await waitFor(() => {
      expect(screen.getByText("네트워크 오류")).toBeInTheDocument();
    });
  });

  it("수락 후 상태 메시지로 전환된다", async () => {
    render(<MarkdownDiffApproval {...baseProps} />);

    fireEvent.click(screen.getByTestId("markdown-diff-accept"));

    // [Flow: 수락 완료 메시지가 표시되는지 확인]
    await waitFor(() => {
      expect(screen.getByText("변경사항을 적용했습니다.")).toBeInTheDocument();
    });
    // [Flow: 수락/거부 버튼이 더 이상 표시되지 않아야 함]
    expect(screen.queryByTestId("markdown-diff-accept")).not.toBeInTheDocument();
    expect(screen.queryByTestId("markdown-diff-reject")).not.toBeInTheDocument();
  });
});
