// [Flow: Step 1 (context에서 job_id, source_type, page, editor 등 추출)
//       -> Step 2 (context를 system 메시지로 변환) -> Step 3 (useChat 래핑)
//       -> Step 4 (tool call UI 상태 관리) -> Step 5 (send/clear/status 반환)]
// Vercel AI SDK 5.x의 useChat을 PROOF 에이전트에 맞게 래핑하는 커스텀 훅.
// 현재 문서/페이지/에디터 컨텍스트를 초기 system message로 전달한다.
import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport, lastAssistantMessageIsCompleteWithToolCalls } from 'ai';
import { useCallback, useMemo } from 'react';

export interface AgentContext {
  jobId?: string;
  sourceType?: string;
  currentPage?: number;
  selectedFileIndex?: number;
  activeEditor?: string;
}

/**
 * [Flow: Step 1 (context 수신) -> Step 2 (system message 생성) -> Step 3 (useChat 설정)
 *       -> Step 4 (send/clear/status 반환)]
 *
 * @param context 현재 Job/페이지/에디터 컨텍스트
 * @returns useChat 객체 + context
 */
export function useAgentChat(context: AgentContext) {
  const initialMessages = useMemo(() => {
    const system = {
      role: 'system' as const,
      content: `Current PROOF context: ${JSON.stringify(context)}`,
      id: 'context',
    };
    return [system];
  }, [context]);

  const chat = useChat({
    transport: new DefaultChatTransport({
      api: '/api/ai/chat',
    }),
    initialMessages,
    sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithToolCalls,
  });

  const sendContextualMessage = useCallback(
    (text: string) => {
      // 사용자 메시지와 함께 context를 body에 담아 보낸다.
      // DefaultChatTransport는 JSON body에 messages를 담지만, context를 추가하려면 별도 처리가 필요하다.
      // 현재 ai SDK 5.x에서는 transport를 직접 구현하거나, fetch wrapper를 사용해야 한다.
      // 단순화를 위해 sendMessage에 추가 메타데이터를 실어보내는 방식은 provider API에 따라 다르다.
      // 우선 text만 보내고, 백엔드에서 context는 initialMessages의 system message를 통해 추론한다.
      return chat.sendMessage({ text });
    },
    [chat],
  );

  return {
    ...chat,
    sendContextualMessage,
    context,
  };
}
