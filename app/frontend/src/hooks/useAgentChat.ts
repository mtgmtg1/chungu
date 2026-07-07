// [Flow: Step 1 (context에서 job_id, source_type, page, editor 등 추출)
//       -> Step 2 (context를 system 메시지로 변환) -> Step 3 (useChat 래핑)
//       -> Step 4 (tool call UI 상태 관리) -> Step 5 (send/clear/status 반환)]
// Vercel AI SDK 5.x(@ai-sdk/react@2.x)의 useChat을 PROOF 에이전트에 맞게 래핑하는 커스텀 훅.
// 현재 문서/페이지/에디터 컨텍스트를 초기 system message로 전달한다.
// 주의: @ai-sdk/react 5.x 계열(useChat v2)은 input/setInput/append를 더 이상 제공하지 않으므로
// 입력값은 이 훅에서 직접 관리하고, 전송은 sendMessage({ text })로 수행한다.
import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
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

/**
 * [Flow: Step 1 (context 수신) -> Step 2 (system message 생성) -> Step 3 (useChat 설정)
 *       -> Step 4 (send/clear/status 반환)]
 *
 * @param context 현재 Job/페이지/에디터 컨텍스트
 * @returns useChat 객체 + context
 */
export function useAgentChat(context: AgentContext) {
  const [input, setInput] = useState('');

  // 최초 마운트 시점의 context만 초기 system message로 사용한다.
  // (매 렌더마다 새로운 context 객체가 들어와도 이미 시작된 채팅의 messages 배열은
  //  useChat 내부 상태로 유지되며, 초기값 재계산으로 재구독되지 않는다.)
  const initialMessages = useMemo(
    () => [
      {
        id: 'context',
        role: 'system' as const,
        parts: [{ type: 'text' as const, text: `Current PROOF context: ${JSON.stringify(context)}` }],
      },
    ],
    [], // eslint-disable-line react-hooks/exhaustive-deps
  );

  // transport를 매 렌더마다 새로 생성하면 참조가 계속 바뀌어 이를 참조하는 콜백들이
  // 불필요하게 재생성되고, 그 콜백에 의존하는 하위 useEffect가 스트리밍 토큰마다
  // 반복 실행되는 원인이 되므로 useMemo로 한 번만 생성한다.
  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: '/api/ai/chat',
        credentials: 'include',
        headers: buildAuthHeaders,
      }),
    [],
  );

  const chat = useChat({
    transport,
    messages: initialMessages,
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
    // 우선 text만 보내고, 백엔드에서 context는 initialMessages의 system message를 통해 추론한다.
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
