// [Flow: Step 1 (AgentChatModal의 의존 모듈 모의) -> Step 2 (닫힌/열린 상태에서 렌더링)
//       -> Step 3 (useAgentChat 호출 여부 및 초기 메시지 검증)]
// 이전 대화 복원 버그 회귀 테스트.
// 모달이 닫혀 있을 때는 현재 대화 세션을 마운트하지 않아야 하며,
// 모달이 열릴 때는 DB에서 로드된 messages를 초기값으로 useAgentChat을 호출해야 한다.

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import AgentChatModal from "./AgentChatModal.jsx";
import { useAgentChat } from "../hooks/useAgentChat.js";

const mockMessages = [
  { id: "msg-1", role: "user", parts: [{ type: "text", text: "이전 대화 내용" }] },
];

vi.mock("../api.js", () => ({
  api: {
    me: vi.fn(() => Promise.resolve({})),
    updateAISettings: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("../AuthContext.jsx", () => ({
  useAuth: () => ({ user: null }),
}));

vi.mock("../hooks/useMediaQuery.js", () => ({
  useIsMobile: () => false,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key) => key, i18n: { language: "ko" } }),
}));

vi.mock("../hooks/useAgentChatHistory.js", () => ({
  useAgentChatHistory: () => ({
    conversations: [
      {
        id: "conv-1",
        title: "테스트 대화",
        messages: mockMessages,
        createdAt: 1,
        updatedAt: 2,
      },
    ],
    currentConversation: {
      id: "conv-1",
      title: "테스트 대화",
      messages: mockMessages,
      createdAt: 1,
      updatedAt: 2,
    },
    currentId: "conv-1",
    isLoadingList: false,
    isLoadingMessages: false,
    error: null,
    clearError: vi.fn(),
    createConversation: vi.fn(),
    selectConversation: vi.fn(),
    saveConversation: vi.fn(),
    deleteConversation: vi.fn(),
    isMessageLoaded: () => true,
  }),
  makeConversationTitle: () => "테스트 대화",
}));

vi.mock("../hooks/useAgentChat.js", () => ({
  useAgentChat: vi.fn(() => ({
    messages: [],
    input: "",
    setInput: vi.fn(),
    status: "ready",
    stop: vi.fn(),
    sendContextualMessage: vi.fn(),
    regenerate: vi.fn(),
    error: undefined,
    clearError: vi.fn(),
    setMessages: vi.fn(),
    resumeStream: vi.fn(),
    addToolResult: vi.fn(),
    addToolOutput: vi.fn(),
  })),
}));

describe("AgentChatModal", () => {
  it("모달이 닫혀 있으면 현재 대화 세션을 마운트하지 않는다", () => {
    render(<AgentChatModal isOpen={false} onClose={vi.fn()} context={{ jobId: "job-1" }} />);
    expect(useAgentChat).not.toHaveBeenCalled();
  });

  it("모달이 열리면 이전 대화 messages를 초기값으로 useAgentChat을 호출한다", () => {
    render(<AgentChatModal isOpen={true} onClose={vi.fn()} context={{ jobId: "job-1" }} />);
    expect(useAgentChat).toHaveBeenCalledTimes(1);
    expect(useAgentChat).toHaveBeenCalledWith(
      expect.objectContaining({ jobId: "job-1" }),
      expect.objectContaining({
        chatId: "conv-1",
        initialMessages: mockMessages,
      }),
    );
  });

  it("전송 버튼 클릭 시 입력값을 즉시 비우고 메시지를 보낸다", () => {
    const setInput = vi.fn();
    const sendContextualMessage = vi.fn();
    useAgentChat.mockReturnValue({
      messages: [],
      input: "보낼 메시지",
      setInput,
      status: "ready",
      stop: vi.fn(),
      sendContextualMessage,
      regenerate: vi.fn(),
      error: undefined,
      clearError: vi.fn(),
    });

    render(<AgentChatModal isOpen={true} onClose={vi.fn()} context={{ jobId: "job-1" }} />);
    const sendButton = screen.getByTestId("ai-chat-send");
    fireEvent.click(sendButton);

    // 입력값은 전송 후 초기화되어야 한다.
    expect(sendContextualMessage).toHaveBeenCalledWith("보낼 메시지");
    expect(setInput).toHaveBeenCalledWith("");
  });

  it("제안 액션 클릭 시 입력값을 비우고 해당 프롬프트를 보낸다", () => {
    const setInput = vi.fn();
    const sendContextualMessage = vi.fn();
    useAgentChat.mockReturnValue({
      messages: [],
      input: "",
      setInput,
      status: "ready",
      stop: vi.fn(),
      sendContextualMessage,
      regenerate: vi.fn(),
      error: undefined,
      clearError: vi.fn(),
    });

    render(<AgentChatModal isOpen={true} onClose={vi.fn()} context={{ jobId: "job-1" }} />);
    const suggestButton = screen.getByText(/suggestDefaultTitle1/);
    fireEvent.click(suggestButton);

    expect(sendContextualMessage).toHaveBeenCalled();
    expect(setInput).toHaveBeenCalledWith("");
  });
});
