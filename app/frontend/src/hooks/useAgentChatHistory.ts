// [Flow: Step 1 (프로젝트 ID 수신) -> Step 2 (localStorage에서 대화 목록 로드)
//       -> Step 3 (대화 생성/선택/저장/삭제 API 제공) -> Step 4 (대화 목록 상태 반환)]
// 프로젝트(Job)별로 AI 에이전트 채팅 대화 이력을 브라우저 localStorage에 저장하고 관리하는 훅.
// 현재는 프론트엔드 로컬 저장소 기반으로 구현되며, 향후 백엔드 API로 교체 가능하도록 인터페이스를 분리한다.
import type { UIMessage } from 'ai';
import { useCallback, useEffect, useMemo, useState } from 'react';

// [Flow: localStorage 키 접두사 + 프로젝트 ID 조합]
const STORAGE_KEY_PREFIX = 'proof_agent_chat_history';

export interface ChatConversation {
  id: string;
  title: string;
  messages: UIMessage[];
  createdAt: number;
  updatedAt: number;
}

export interface UseAgentChatHistoryResult {
  conversations: ChatConversation[];
  currentConversation: ChatConversation | null;
  currentId: string | null;
  createConversation: () => ChatConversation;
  selectConversation: (id: string) => void;
  saveConversation: (id: string, messages: UIMessage[]) => void;
  deleteConversation: (id: string) => void;
}

/**
 * [Flow: Step 1 (프로젝트 ID) -> Step 2 (localStorage 키 문자열 생성)]
 *
 * @param projectId 현재 프로젝트(결과보기 Job)의 고유 ID
 * @returns localStorage에 사용할 키 문자열
 */
function buildStorageKey(projectId: string): string {
  return `${STORAGE_KEY_PREFIX}:${projectId}`;
}

/**
 * [Flow: Step 1 (타임스탬프 + 랜덤 문자열) -> Step 2 (대화 ID 생성)]
 *
 * @returns 충돌 가능성이 낮은 대화 ID
 */
function generateConversationId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * [Flow: Step 1 (메시지 목록 순회) -> Step 2 (첫 번째 사용자 텍스트 추출)]
 *
 * @param messages UIMessage 배열
 * @returns 첫 사용자 메시지의 텍스트(없으면 빈 문자열)
 */
function extractFirstUserText(messages: UIMessage[]): string {
  for (const message of messages) {
    if (message.role !== 'user') continue;

    for (const part of message.parts || []) {
      if (part.type === 'text' && part.text?.trim()) {
        return part.text.trim();
      }
    }

    if (typeof message.content === 'string' && message.content.trim()) {
      return message.content.trim();
    }
  }
  return '';
}

/**
 * [Flow: Step 1 (첫 사용자 메시지 추출) -> Step 2 (길이 제한 후 제목 반환)]
 *
 * @param messages UIMessage 배열
 * @returns 대화 제목(첫 사용자 메시지 기반)
 */
function makeConversationTitle(messages: UIMessage[]): string {
  const text = extractFirstUserText(messages);
  if (!text) return '';
  return text.length > 28 ? `${text.slice(0, 28)}…` : text;
}

/**
 * [Flow: Step 1 (localStorage 읽기) -> Step 2 (JSON 파싱) -> Step 3 (배열 검증 후 반환)]
 *
 * @param projectId 현재 프로젝트 ID
 * @returns 저장된 대화 목록(없거나 오류면 빈 배열)
 */
function loadConversations(projectId: string): ChatConversation[] {
  try {
    const raw = localStorage.getItem(buildStorageKey(projectId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed;
  } catch {
    // localStorage 파싱 실패 시 무시하고 빈 목록 반환
  }
  return [];
}

/**
 * [Flow: Step 1 (대화 목록 직렬화) -> Step 2 (localStorage 저장)]
 *
 * @param projectId 현재 프로젝트 ID
 * @param conversations 저장할 대화 목록
 */
function persistConversations(projectId: string, conversations: ChatConversation[]): void {
  try {
    localStorage.setItem(buildStorageKey(projectId), JSON.stringify(conversations));
  } catch {
    // localStorage quota 등의 오류 발생 시 조용히 무시
  }
}

/**
 * [Flow: Step 1 (프로젝트 ID) -> Step 2 (localStorage 로드) -> Step 3 (대화 상태 관리)
//       -> Step 4 (생성/선택/저장/삭제 함수 제공)]
 *
 * @param projectId 현재 프로젝트(결과보기 Job) ID. undefined면 아무 동작도 하지 않는다.
 * @returns 대화 이력 상태와 조작 함수들
 */
export function useAgentChatHistory(
  projectId: string | undefined,
): UseAgentChatHistoryResult {
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);

  // [Flow: 프로젝트 ID 변경 시 localStorage에서 대화 목록 로드]
  useEffect(() => {
    if (!projectId) {
      setConversations([]);
      setCurrentId(null);
      return;
    }
    const loaded = loadConversations(projectId);
    setConversations(loaded);
    setCurrentId((prev) => prev || (loaded.length > 0 ? loaded[0].id : null));
  }, [projectId]);

  // [Flow: Step 1 (새 대화 객체 생성) -> Step 2 (목록 최상단 추가) -> Step 3 (localStorage 저장)]
  const createConversation = useCallback(() => {
    const newConversation: ChatConversation = {
      id: generateConversationId(),
      title: '',
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
    };

    setConversations((prev) => {
      const next = [newConversation, ...prev];
      if (projectId) persistConversations(projectId, next);
      return next;
    });
    setCurrentId(newConversation.id);
    return newConversation;
  }, [projectId]);

  // [Flow: Step 1 (대화 ID 수신) -> Step 2 (현재 대화로 설정)]
  const selectConversation = useCallback((id: string) => {
    setCurrentId(id);
  }, []);

  // [Flow: Step 1 (ID + 메시지 목록) -> Step 2 (해당 대화 갱신) -> Step 3 (updatedAt 기준 정렬 후 저장)]
  const saveConversation = useCallback(
    (id: string, messages: UIMessage[]) => {
      if (!projectId) return;

      setConversations((prev) => {
        const next = prev.map((conversation) => {
          if (conversation.id !== id) return conversation;
          const title = conversation.title || makeConversationTitle(messages);
          return { ...conversation, title, messages, updatedAt: Date.now() };
        });
        const sorted = [...next].sort((a, b) => b.updatedAt - a.updatedAt);
        persistConversations(projectId, sorted);
        return sorted;
      });
    },
    [projectId],
  );

  // [Flow: Step 1 (대화 ID) -> Step 2 (목록에서 제거) -> Step 3 (현재 대화가 삭제된 경우 다른 대화 선택)]
  const deleteConversation = useCallback(
    (id: string) => {
      if (!projectId) return;

      setConversations((prev) => {
        const next = prev.filter((conversation) => conversation.id !== id);
        persistConversations(projectId, next);
        return next;
      });

      setCurrentId((prev) => {
        if (prev !== id) return prev;
        const remaining = conversations.filter((conversation) => conversation.id !== id);
        return remaining[0]?.id || null;
      });
    },
    [projectId, conversations],
  );

  const currentConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === currentId) || null,
    [conversations, currentId],
  );

  return {
    conversations,
    currentConversation,
    currentId,
    createConversation,
    selectConversation,
    saveConversation,
    deleteConversation,
  };
}
