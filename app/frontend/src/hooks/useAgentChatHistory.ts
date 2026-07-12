// [Flow: Step 1 (프로젝트 ID 수신) -> Step 2 (DB에서 대화 목록 로드, messages 제외)
//       -> Step 3 (대화 선택 시 messages 지연 로드) -> Step 4 (생성/저장/삭제 API 호출)
//       -> Step 5 (저장 시 도구 결과 요약 적용) -> Step 6 (대화 목록 상태 반환)]
// 프로젝트(Job)별로 AI 에이전트 채팅 대화 이력을 DB에 저장하고 관리하는 훅.
// 기존 localStorage 기반에서 DB 백엔드 API로 전환하여 단일 진실 공급원을 구축한다.
// 대화 목록 조회 시 messages를 제외하여 경량화하고, 대화 선택 시 messages를 별도 로드한다.
// 저장 시 도구 input/output이 임계값(500자)을 초과하면 핵심 필드 + 크기 정보로 요약하여
// 저장 용량을 최적화한다 (chatMessageUtils.compactMessagesForStorage).
import type { UIMessage } from 'ai';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api.js';
import { compactMessagesForStorage } from '../utils/chatMessageUtils.js';

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
  isLoadingList: boolean;
  isLoadingMessages: boolean;
  createConversation: () => ChatConversation;
  selectConversation: (id: string) => void;
  saveConversation: (id: string, messages: UIMessage[]) => void;
  deleteConversation: (id: string) => void;
  isMessageLoaded: (id: string) => boolean;
}

/**
 * [Flow: Step 1 (타임스탬프 + 랜덤 문자열) -> Step 2 (대화 ID 생성)]
 *
 * 클라이언트에서 대화 ID를 생성하여 DB PK로 사용한다.
 * 백엔드 upsert 패턴이므로 클라이언트 ID를 그대로 전달한다.
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

    // UIMessage 5.x는 content 대신 parts 배열을 사용한다.
    for (const part of message.parts || []) {
      if (part.type === 'text' && part.text?.trim()) {
        return part.text.trim();
      }
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
 * [Flow: Step 1 (프로젝트 ID) -> Step 2 (DB에서 대화 목록 로드) -> Step 3 (대화 상태 관리)
//       -> Step 4 (생성/선택/저장/삭제 함수 제공)]
 *
 * 대화 목록은 messages를 제외한 메타데이터만 로드하고,
 * 대화 선택 시 getChatConversation으로 messages를 별도 로드한다.
 *
 * @param projectId 현재 프로젝트(결과보기 Job) ID. undefined면 아무 동작도 하지 않는다.
 * @returns 대화 이력 상태와 조작 함수들
 */
export function useAgentChatHistory(
  projectId: string | undefined,
): UseAgentChatHistoryResult {
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);

  // [Flow: messages 로드 완료된 대화 ID 집합 — 중복 fetch 방지]
  const loadedIdsRef = useRef<Set<string>>(new Set());

  // [Flow: projectId 변경 시 DB에서 대화 목록 로드 (messages 제외)]
  useEffect(() => {
    if (!projectId) {
      setConversations([]);
      setCurrentId(null);
      loadedIdsRef.current = new Set();
      setIsLoadingList(false);
      return;
    }

    let cancelled = false;
    setIsLoadingList(true);
    api
      .listChatConversations(projectId)
      .then((list: Array<{ id: string; title: string; createdAt: number; updatedAt: number }>) => {
        if (cancelled) return;
        const loaded: ChatConversation[] = list.map((item) => ({
          id: item.id,
          title: item.title || '',
          messages: [],
          createdAt: item.createdAt || 0,
          updatedAt: item.updatedAt || 0,
        }));
        setConversations(loaded);
        // 목록에 있는 대화는 messages가 아직 로드되지 않음
        loadedIdsRef.current = new Set();
        // 가장 최근 대화를 기본 선택
        if (loaded.length > 0) {
          setCurrentId(loaded[0].id);
        } else {
          setCurrentId(null);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        console.error('[useAgentChatHistory] 목록 로드 실패:', err);
        setConversations([]);
        setCurrentId(null);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingList(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // [Flow: currentId 변경 시 messages 지연 로드 — 아직 로드되지 않은 대화면 fetch]
  useEffect(() => {
    if (!projectId || !currentId) return;
    if (loadedIdsRef.current.has(currentId)) return;

    setIsLoadingMessages(true);
    api
      .getChatConversation(projectId, currentId)
      .then((data: { id: string; title: string; messages: UIMessage[]; createdAt: number; updatedAt: number } | null) => {
        loadedIdsRef.current.add(currentId);
        if (!data) {
          // DB에 없는 대화 (예: 방금 생성된 새 대화) — 빈 messages로 처리
          setConversations((prev) =>
            prev.map((c) =>
              c.id === currentId ? { ...c, messages: [] } : c,
            ),
          );
          return;
        }
        setConversations((prev) =>
          prev.map((c) =>
            c.id === currentId
              ? { ...c, title: data.title || c.title, messages: data.messages || [], updatedAt: data.updatedAt || c.updatedAt }
              : c,
          ),
        );
      })
      .catch((err) => {
        console.error('[useAgentChatHistory] messages 로드 실패:', err);
        loadedIdsRef.current.add(currentId); // 실패해도 재시도 무한루프 방지
      })
      .finally(() => {
        setIsLoadingMessages(false);
      });
  }, [projectId, currentId]);

  // [Flow: Step 1 (새 대화 객체 생성) -> Step 2 (목록 최상단 추가) -> Step 3 (DB에 빈 대화 PUT)]
  const createConversation = useCallback(() => {
    const newConversation: ChatConversation = {
      id: generateConversationId(),
      title: '',
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
    };

    setConversations((prev) => [newConversation, ...prev]);
    setCurrentId(newConversation.id);
    loadedIdsRef.current.add(newConversation.id); // 새 대화는 messages가 빈 배열로 이미 로드됨

    // DB에 빈 대화 저장 (사용자가 메시지 전송 전에 닫아도 대화 존재)
    if (projectId) {
      api
        .saveChatConversation(projectId, newConversation.id, {
          title: '',
          messages: [],
        })
        .catch((err) => console.error('[useAgentChatHistory] 새 대화 저장 실패:', err));
    }

    return newConversation;
  }, [projectId]);

  // [Flow: Step 1 (대화 ID 수신) -> Step 2 (현재 대화로 설정)]
  const selectConversation = useCallback((id: string) => {
    setCurrentId(id);
  }, []);

  // [Flow: Step 1 (ID + 메시지 목록) -> Step 2 (로컬 상태에는 원본 messages 저장)
  //       -> Step 3 (DB에는 도구 결과를 요약한 compact messages 저장) -> Step 4 (용량 최적화)]
  // 로컬 상태는 원본을 유지하여 현재 세션에서 도구 상세 결과를 볼 수 있고,
  // DB에는 요약본을 저장하여 저장 용량을 절약한다.
  // 복원 시(다른 기기/새로고침)에는 요약된 도구 결과만 표시되지만,
  // 도구 이름/상태/핵심 필드는 유지되므로 대화 맥락 파악에 충분하다.
  const saveConversation = useCallback(
    (id: string, messages: UIMessage[]) => {
      if (!projectId) return;

      const title = makeConversationTitle(messages);
      setConversations((prev) => {
        const next = prev.map((conversation) => {
          if (conversation.id !== id) return conversation;
          return {
            ...conversation,
            title: conversation.title || title,
            messages,
            updatedAt: Date.now(),
          };
        });
        // updatedAt 기준 내림차순 정렬 (가장 최근 대화가 상단)
        const sorted = [...next].sort((a, b) => b.updatedAt - a.updatedAt);
        return sorted;
      });

      // [Flow: DB에는 도구 input/output을 요약한 messages 저장 — 용량 최적화]
      const compactedMessages = compactMessagesForStorage(messages);
      api
        .saveChatConversation(projectId, id, { title, messages: compactedMessages })
        .catch((err) => console.error('[useAgentChatHistory] 대화 저장 실패:', err));
    },
    [projectId],
  );

  // [Flow: Step 1 (대화 ID) -> Step 2 (DB에서 삭제) -> Step 3 (목록에서 제거)
  //       -> Step 4 (현재 대화가 삭제된 경우 다른 대화 선택)]
  const deleteConversation = useCallback(
    (id: string) => {
      if (!projectId) return;

      // DB에서 삭제
      api
        .deleteChatConversation(projectId, id)
        .catch((err) => console.error('[useAgentChatHistory] 대화 삭제 실패:', err));

      loadedIdsRef.current.delete(id);
      setConversations((prev) => {
        const next = prev.filter((conversation) => conversation.id !== id);
        return next;
      });

      setCurrentId((prev) => {
        if (prev !== id) return prev;
        // 현재 대화가 삭제된 경우 — useEffect가 currentId 변경을 감지하여
        // 남은 대화 중 첫 번째를 선택하거나 null로 설정
        return null;
      });
    },
    [projectId],
  );

  // [Flow: currentId가 null이고 대화가 있는 경우 — 첫 번째 대화 자동 선택]
  useEffect(() => {
    if (currentId === null && conversations.length > 0) {
      setCurrentId(conversations[0].id);
    }
  }, [currentId, conversations]);

  const currentConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === currentId) || null,
    [conversations, currentId],
  );

  // [Flow: Step 1 (대화 ID) -> Step 2 (ref에서 로드 여부 확인) -> Step 3 (결과 반환)]
  const isMessageLoaded = useCallback((id: string) => loadedIdsRef.current.has(id), []);

  return {
    conversations,
    currentConversation,
    currentId,
    isLoadingList,
    isLoadingMessages,
    createConversation,
    selectConversation,
    saveConversation,
    deleteConversation,
    isMessageLoaded,
  };
}
