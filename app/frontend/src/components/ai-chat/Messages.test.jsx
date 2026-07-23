// [Flow: Step 1 (Messages 컴포넌트 렌더링)
//       -> Step 2 (status별 AgentActivityIndicator 노출 확인)
//       -> Step 3 (streaming 중에도 대화 최하단에 인디케이터가 표시되는지 검증)]
// 에이전트 활동 인디케이터가 "submitted" 및 "streaming" 상태에서
// 항상 대화 목록 최하단에 표시되는지 회귀 테스트한다.
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import Messages from "./Messages.jsx";

// [Flow: jsdom에는 scrollIntoView가 없으므로 테스트 시작 전 no-op으로 대체]
beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

// [Flow: 테스트용 UIMessage 팩토리 — 보일러플레이트 제거]
function makeMessage({ id, role, text }) {
  return {
    id,
    role,
    parts: [{ type: "text", text }],
  };
}

describe("Messages", () => {
  it("ready 상태에서는 활동 인디케이터를 표시하지 않는다", () => {
    render(
      <Messages
        messages={[makeMessage({ id: "m1", role: "user", text: "안녕" })]}
        status="ready"
      />,
    );
    expect(screen.queryByTestId("message-assistant-loading")).not.toBeInTheDocument();
  });

  it("submitted 상태에서 대화 최하단에 활동 인디케이터를 표시한다", () => {
    render(
      <Messages
        messages={[makeMessage({ id: "m1", role: "user", text: "안녕" })]}
        status="submitted"
      />,
    );
    expect(screen.getByTestId("message-assistant-loading")).toBeInTheDocument();
  });

  it("streaming 상태에서도 텍스트가 이미 들어온 assistant 메시지 아래에 인디케이터를 표시한다", () => {
    render(
      <Messages
        messages={[
          makeMessage({ id: "m1", role: "user", text: "요약해줘" }),
          makeMessage({ id: "m2", role: "assistant", text: "이것은 이미 생성된 답변 내용입니다." }),
        ]}
        status="streaming"
      />,
    );
    expect(screen.getByTestId("message-assistant-loading")).toBeInTheDocument();
  });

  it("streaming 상태에서 마지막 메시지가 user이면 인디케이터를 표시한다", () => {
    render(
      <Messages
        messages={[makeMessage({ id: "m1", role: "user", text: "계속해" })]}
        status="streaming"
      />,
    );
    expect(screen.getByTestId("message-assistant-loading")).toBeInTheDocument();
  });

  // [Flow: 프롬프트 복사/수정 버튼 — 마지막 사용자 메시지 아래에만 표시]
  it("ready 상태에서 마지막 사용자 메시지 아래에 프롬프트 복사/수정 버튼을 표시한다", () => {
    render(
      <Messages
        messages={[
          makeMessage({ id: "m1", role: "user", text: "표를 정리해줘" }),
          makeMessage({ id: "m2", role: "assistant", text: "정리했습니다." }),
          makeMessage({ id: "m3", role: "user", text: "다시 요약해줘" }),
        ]}
        status="ready"
        onCopyPrompt={() => {}}
        onEditPrompt={() => {}}
      />,
    );
    // 마지막 user 메시지(m3) 아래에 버튼이 있어야 한다
    expect(screen.getByTestId("agent-message-copy-prompt")).toBeInTheDocument();
    expect(screen.getByTestId("agent-message-edit-prompt")).toBeInTheDocument();
  });

  it("streaming 중에는 프롬프트 복사/수정 버튼을 표시하지 않는다", () => {
    render(
      <Messages
        messages={[makeMessage({ id: "m1", role: "user", text: "요약해줘" })]}
        status="streaming"
        onCopyPrompt={() => {}}
        onEditPrompt={() => {}}
      />,
    );
    expect(screen.queryByTestId("agent-message-copy-prompt")).not.toBeInTheDocument();
    expect(screen.queryByTestId("agent-message-edit-prompt")).not.toBeInTheDocument();
  });

  it("onCopyPrompt 클릭 시 콜백이 호출된다", () => {
    const handleCopy = vi.fn();
    render(
      <Messages
        messages={[makeMessage({ id: "m1", role: "user", text: "복사 대상" })]}
        status="ready"
        onCopyPrompt={handleCopy}
      />,
    );
    screen.getByTestId("agent-message-copy-prompt").click();
    expect(handleCopy).toHaveBeenCalledTimes(1);
  });

  it("onEditPrompt 클릭 시 콜백이 호출된다", () => {
    const handleEdit = vi.fn();
    render(
      <Messages
        messages={[makeMessage({ id: "m1", role: "user", text: "수정 대상" })]}
        status="ready"
        onEditPrompt={handleEdit}
      />,
    );
    screen.getByTestId("agent-message-edit-prompt").click();
    expect(handleEdit).toHaveBeenCalledTimes(1);
  });

  it("onCopyPrompt/onEditPrompt가 전달되지 않으면 버튼을 표시하지 않는다", () => {
    render(
      <Messages
        messages={[makeMessage({ id: "m1", role: "user", text: "대상" })]}
        status="ready"
      />,
    );
    expect(screen.queryByTestId("agent-message-copy-prompt")).not.toBeInTheDocument();
    expect(screen.queryByTestId("agent-message-edit-prompt")).not.toBeInTheDocument();
  });
});
