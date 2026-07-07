// [Flow: Step 1 (context에서 job_id, source_type, page, editor 등 추출)
//       -> Step 2 (context를 transport body로 전송) -> Step 3 (useChat 래핑)
//       -> Step 4 (tool call UI 상태 관리) -> Step 5 (send/clear/status 반환)]
// Vercel AI SDK 5.x(@ai-sdk/react@2.x)의 useChat을 PROOF 에이전트에 맞게 래핑하는 커스텀 훅.
// 현재 문서/페이지/에디터 컨텍스트를 매 요청의 body에 포함하여 전달한다.
// 주의: @ai-sdk/react 5.x 계열(useChat v2)은 input/setInput/append를 더 이상 제공하지 않으므로
// 입력값은 이 훅에서 직접 관리하고, 전송은 sendMessage({ text })로 수행한다.
import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import type { UIMessage } from 'ai';
import { useCallback, useMemo, useRef, useState } from 'react';
import { getToken } from '../api.js';

export interface AgentContext {
  jobId?: string;
  sourceType?: string;
  currentPage?: number;
  selectedFileIndex?: number;
  activeEditor?: string;
}

/**
 * [Flow: Step 1 (Supabase 세션 토큰 획득) -> Step 2 (JWT + dev API key 헤더 구성)]
 *
 * useChat의 DefaultChatTransport에 전달할 인증 헤더를 동적으로 생성한다.
 * AI 백엔드가 FastAPI 도구 호출 시 이 헤더를 전달하므로 인증이 필요하다.
 */
async function buildAuthHeaders(): Promise<Record<string, string>> {
  const token = await getToken();
  const h: Record<string, string> = {};
  if (token && token.startsWith('eyJ')) h['Authorization'] = `Bearer ${token}`;
  const devKey = import.meta.env.DEV
    ? (import.meta.env.VITE_DEV_API_KEY || 'chu_live_testkey12345')
    : '';
  if (devKey) h['X-Api-Key'] = devKey;
  return h;
}

export interface UseAgentChatOptions {
  chatId?: string;
  initialMessages?: UIMessage[];
}

/**
 * [Flow: Step 1 (context + 옵션 수신) -> Step 2 (context ref 보관) -> Step 3 (useChat 설정)
 *       -> Step 4 (send/clear/status/regenerate 반환)]
 *
 * context를 초기 system message 대신 transport body로 전송한다.
 * 이렇게 하면 context가 나중에 로드되어도(preview 로드 후 sourceType 확정 등)
 * 매 전송 시점의 최신 context가 백엔드에 전달된다.
 *
 * 대화 이력 복원을 위해 chatId와 initialMessages를 받아 useChat에 전달한다.
 * chatId가 변경되면 상위 컴포넌트에서 key prop으로 remount하여 새로운 대화를 시작해야 한다.
 *
 * @param context 현재 Job/페이지/에디터 컨텍스트
 * @param options 대화 ID 및 초기 메시지
 * @returns useChat 객체 + context
 */
export function useAgentChat(context: AgentContext, options: UseAgentChatOptions = {}) {
  const { chatId, initialMessages } = options;
  const [input, setInput] = useState('');

  // 최신 context를 ref로 보관하여 transport body 함수가 항상 최신 값을 읽도록 한다.
  // (useMemo deps에 context를 넣으면 transport가 재생성되어 채팅이 리셋되므로 ref 사용)
  const contextRef = useRef(context);
  contextRef.current = context;

  // transport를 매 렌더마다 새로 생성하면 참조가 계속 바뀌어 이를 참조하는 콜백들이
  // 불필요하게 재생성되고, 그 콜백에 의존하는 하위 useEffect가 스트리밍 토큰마다
  // 반복 실행되는 원인이 되므로 useMemo로 한 번만 생성한다.
  // body 함수는 매 요청마다 호출되므로 contextRef.current를 읽어 최신 context를 전송한다.
  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: '/api/ai/chat',
        credentials: 'include',
        headers: buildAuthHeaders,
        body: () => ({ context: contextRef.current }),
      }),
    [],
  );

  const chat = useChat({
    id: chatId || 'default',
    messages: initialMessages,
    transport,
    // 도구 실행은 AI 백엔드의 streamText(stopWhen: stepCountIs(5))가 한 번의 스트림 안에서
    // 전부 처리하므로 클라이언트가 별도로 재요청할 필요가 없다. sendAutomaticallyWhen을
    // 설정하지 않아 불필요한 재전송/루프 가능성을 원천 차단한다.
  });

  // chat 객체는 useChat이 매 렌더마다 새로 만드는 plain object이므로, 이를 그대로
  // useCallback deps에 넣으면 스트리밍 토큰이 올 때마다 sendContextualMessage가 재생성된다.
  // ref로 최신 chat을 보관해 안정적인 함수 참조를 유지한다.
  const chatRef = useRef(chat);
  chatRef.current = chat;

  const sendContextualMessage = useCallback((text: string) => {
    // context는 transport의 body 함수를 통해 매 요청마다 전송된다.
    return chatRef.current.sendMessage({ text });
  }, []);

  return {
    ...chat,
    input,
    setInput,
    sendContextualMessage,
    context,
  };
}
