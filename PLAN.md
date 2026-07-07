# PROOF AI Agent 재구축 플랜

## 1. 목표

- 현재 LangGraph 기반 AI 주석/에디터 에이전트를 제거
- Vercel AI SDK 5.x 기반의 대화형 에이전트 채팅으로 교체
- 프론트엔드 + Node.js 백엔드 모두에서 ai SDK를 직접 사용
- 기존 Python FastAPI는 그대로 두고 병렬 운영
- 주요 도구: PDF 주석 조작(서버 사이드), 마크다운 에디터 조작, 엑셀 조작

---

## 2. 아키텍처

```text
┌─────────────────────────────────────────────────────────┐
│                     Frontend (React/Vite)               │
│  ┌─────────────────┐      ┌───────────────────────────┐ │
│  │ AgentInputBar   │  ->  │ AgentChatModal            │ │
│  │ (하단 중앙 입력) │      │ (useChat + @ai-sdk/react) │ │
│  └─────────────────┘      └───────────────────────────┘ │
│                              │ POST /api/ai/chat        │
└──────────────────────────────┼─────────────────────────┘
                               │
┌──────────────────────────────┼─────────────────────────┐
│  Node.js AI Backend          │                         │
│  (Express or Next.js)        │                         │
│  - streamText()              │                         │
│  - tools: annotations / md / xlsx                         │
│  - calls FastAPI for job data                            │
└──────────────────────────────┼─────────────────────────┘
                               │
┌──────────────────────────────┼─────────────────────────┐
│  Python FastAPI (기존)        │                         │
│  - /api/jobs/*               │                         │
│  - /api/auth/*               │                         │
│  - Storage / DB              │                         │
└─────────────────────────────────────────────────────────┘
```

---

## 3. 기술 스택

| 영역 | 기술 | 비고 |
|------|------|------|
| 프론트엔드 AI SDK | `ai@^5.0.0`, `@ai-sdk/react` | useChat + DefaultChatTransport |
| 프론트 UI | React, Tailwind, Lucide | 기존 디자인 시스템 유지 |
| Node.js AI 백엔드 | Express.js | ai SDK streamText/tool 직접 사용 |
| 모델 연결 | OpenAI-compatible provider | 기존 vLLM/llama.cpp endpoint 재사용 |
| Python 백엔드 | FastAPI (기존) | 데이터, Storage, 인증 유지 |
| 인증 | JWT / API Key | FastAPI와 동일한 검증 로직 공유 |

---

## 4. 파일 변경 계획

### 4.1 신규 파일

| 파일 | 설명 |
|------|------|
| `app/ai-backend/package.json` | ai SDK, Express, zod, 타입스크립트 의존성 |
| `app/ai-backend/tsconfig.json` | TypeScript 설정 |
| `app/ai-backend/src/server.ts` | Express 서버, `/api/ai/chat` 라우트 |
| `app/ai-backend/src/chat/route.ts` | `streamText` + tools + 스트리밍 응답 |
| `app/ai-backend/src/tools/annotations.ts` | PDF 주석 관련 도구 정의 |
| `app/ai-backend/src/tools/markdown.ts` | 마크다운 에디터 관련 도구 정의 |
| `app/ai-backend/src/tools/spreadsheet.ts` | 엑셀 조작 관련 도구 정의 |
| `app/ai-backend/src/lib/proof-api.ts` | FastAPI 호출 클라이언트 |
| `app/ai-backend/src/lib/model.ts` | OpenAI-compatible provider 설정 |
| `app/ai-backend/src/lib/auth.ts` | 인증 미들웨어 |
| `app/frontend/src/components/AgentInputBar.jsx` | 하단 중앙 플로팅 입력창 |
| `app/frontend/src/components/AgentChatModal.jsx` | 팝업 채팅창 |
| `app/frontend/src/components/AgentToolRenderer.jsx` | tool call 상태 렌더링 |
| `app/frontend/src/hooks/useAgentChat.ts` | useChat 래퍼 |

### 4.2 수정 파일

| 파일 | 변경 내용 |
|------|-----------|
| `app/frontend/package.json` | `ai`, `@ai-sdk/react` 추가/업그레이드 |
| `app/frontend/vite.config.js` | `/api/ai/*` → Node.js 백엔드 프록시 |
| `app/frontend/src/pages/JobResultPage.jsx` | AgentInputBar + AgentChatModal 추가 |
| `app/frontend/src/i18n/locales/ko/page.json` | 에이전트 채팅 번역 키 추가 |
| `app/frontend/src/i18n/locales/en/page.json` | 에이전트 채팅 번역 키 추가 |
| `app/frontend/src/i18n/locales/ja/page.json` | 에이전트 채팅 번역 키 추가 |
| `app/backend/api/v1/router.py` | `/agent` 라우트 제거 |
| `app/backend/celery_app.py` | `agent_run_task` 제거 |
| `app/backend/workers/tasks.py` | `agent_run_task` 제거 |

### 4.3 제거 파일

| 파일 | 이유 |
|------|------|
| `app/backend/api/v1/agent.py` | LangGraph API 제거 |
| `app/backend/core/agent_annotator.py` | LangGraph annotator 제거 |
| `app/backend/core/agent_editor.py` | LangGraph editor 제거 |
| `app/backend/core/agent_engine.py` | LangGraph engine 제거 |
| `app/backend/core/agent_llm.py` | LangChain LLM 팩토리 제거 |
| `app/frontend/src/components/AgentApprovalModal.jsx` | HITL 모달 제거 |
| `app/frontend/src/components/AgentStatusCard.jsx` | 상태 카드 제거 |
| `app/backend/tests/test_agent_graph.py` | LangGraph 테스트 제거 |

---

## 5. 프론트엔드 상세 설계

### 5.1 AgentInputBar

```jsx
// 화면 정중앙 하단
<div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40">
  <div className="flex items-center gap-2 px-4 py-2.5 rounded-full bg-surface shadow-lg border border-outline-variant">
    <Sparkles size={18} className="text-primary" />
    <input
      placeholder="AI에게 무엇을 도와드릴까요?"
      onFocus={() => setIsChatOpen(true)}
      className="w-64 sm:w-80 bg-transparent outline-none text-sm"
    />
    <button><Send size={16} /></button>
  </div>
</div>
```

- 포커스/클릭 시 `AgentChatModal` 열기
- `Enter` 입력 시 모달 열고 첫 메시지 전송

### 5.2 AgentChatModal

```jsx
import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';

const { messages, sendMessage, status, addToolOutput } = useChat({
  transport: new DefaultChatTransport({ api: '/api/ai/chat' }),
  sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithToolCalls,
});
```

- 메시지 리스트 렌더링
- tool call 상태 렌더링 (input/output/approval)
- interrupt/승인 UI
- 현재 context(job_id, source_type, page, editor)를 initial message에 포함

### 5.3 JobResultPage 통합

```jsx
// JobResultPage.jsx
<AgentInputBar onOpenChat={() => setChatOpen(true)} />
<AgentChatModal
  isOpen={chatOpen}
  onClose={() => setChatOpen(false)}
  context={{
    jobId,
    sourceType,
    currentPage,
    selectedFileIndex,
    activeEditor: previewMode,
  }}
/>
```

---

## 6. Node.js AI 백엔드 상세 설계

### 6.1 `/api/ai/chat` 엔드포인트

```ts
import {
  streamText,
  tool,
  convertToModelMessages,
  createUIMessageStreamResponse,
  toUIMessageStream,
  isStepCount,
} from 'ai';
import { z } from 'zod';

export async function POST(req: Request) {
  const { messages, context } = await req.json();
  const result = streamText({
    model: proofProvider(),
    system: buildSystemPrompt(context),
    messages: await convertToModelMessages(messages),
    tools: { ...annotationTools, ...markdownTools, ...spreadsheetTools },
    stopWhen: isStepCount(5),
  });
  return createUIMessageStreamResponse({
    stream: toUIMessageStream({ stream: result.stream }),
  });
}
```

### 6.2 PDF 주석 도구 (서버 사이드)

```ts
const annotationTools = {
  search_text: tool({
    description: 'PDF 텍스트 레이어에서 키워드나 정규식으로 검색',
    inputSchema: z.object({ query: z.string(), page_no: z.number().optional() }),
    execute: async ({ query, page_no }) => {
      const elements = await proofApi.searchText(context.jobId, query, page_no);
      return { matches: elements };
    },
  }),

  get_elements: tool({
    description: '페이지의 텍스트/표 요소 목록 반환',
    inputSchema: z.object({ page_no: z.number().optional() }),
    execute: async ({ page_no }) => proofApi.getElements(context.jobId, page_no),
  }),

  add_highlight: tool({
    description: '요소에 하이라이트 주석 추가',
    inputSchema: z.object({
      element_index: z.number(),
      comment: z.string(),
      color: z.enum(['red','yellow','green','blue','orange','purple','pink','gray']),
    }),
    execute: async ({ element_index, comment, color }) => {
      return annotationState.addHighlight(context, element_index, comment, color);
    },
  }),

  add_callout: tool({ ... }),
  remove_annotation: tool({ ... }),
  compare_elements: tool({ ... }),
  apply_annotations: tool({
    description: '현재까지의 주석을 Storage에 저장하고 뷰어에 반영',
    inputSchema: z.object({}),
    execute: async () => {
      const annotations = annotationState.buildEmbedpdfAnnotations(context);
      await proofApi.saveAnnotations(context.jobId, context.sourceIndex, annotations);
      return { saved: true, count: annotations.length };
    },
  }),
};
```

### 6.3 마크다운 에디터 도구

```ts
const markdownTools = {
  get_section: tool({ ... }),
  get_table: tool({ ... }),
  replace_selection: tool({ ... }),
  insert_at: tool({ ... }),
  apply_edits: tool({
    description: '편집 결과를 FastAPI에 저장',
    execute: async () => proofApi.saveMarkdown(context.jobId, context.pageNum, markdownState.final),
  }),
};
```

### 6.4 엑셀 조작 도구

```ts
const spreadsheetTools = {
  get_sheet: tool({ ... }),
  update_cell: tool({ ... }),
  add_row: tool({ ... }),
  delete_row: tool({ ... }),
  apply_changes: tool({
    description: '스프레드시트 변경을 FastAPI에 저장',
    execute: async () => proofApi.saveXlsx(context.jobId, xlsxState.blob),
  }),
};
```

### 6.5 FastAPI 연동

```ts
// app/ai-backend/src/lib/proof-api.ts
export const proofApi = {
  async getJob(jobId: string) { ... },
  async searchText(jobId: string, query: string, pageNo?: number) { ... },
  async getElements(jobId: string, pageNo?: number) { ... },
  async saveAnnotations(jobId: string, sourceIndex: number, annotations: any[]) { ... },
  async saveMarkdown(jobId: string, pageNum: number, markdown: string) { ... },
  async saveXlsx(jobId: string, blob: Blob) { ... },
};
```

- FastAPI의 `/api/jobs/*` 엔드포인트를 호출
- 인증: `X-Api-Key` 또는 `Authorization: Bearer` 헤더 그대로 전달

---

## 7. 데이터 흐름

### 7.1 PDF 주석 생성

1. 사용자가 "세금 10%인 항목을 하이라이트해줘" 입력
2. `sendMessage` -> `POST /api/ai/chat`
3. LLM이 `search_text({query: "10%"})` 호출
4. 서버가 FastAPI에서 텍스트 레이어 요소 검색
5. LLM이 `add_highlight(element_index=3, comment="세금 10%")` 호출
6. 서버가 임시 상태에 주석 추가
7. LLM이 `apply_annotations()` 호출
8. 서버가 `build_embedpdf_annotations()`로 JSON 생성
9. FastAPI `/api/jobs/{id}/user-annotations`로 저장
10. 프론트의 `job` 상태 갱신 -> `PdfViewer`에 새 annotationsJson 반영

### 7.2 마크다운 편집

1. 사용자가 "이 단락을 더 짧게" 입력
2. LLM이 `get_section(heading)` 또는 `replace_selection(old_text, new_text)` 호출
3. 서버가 임시 상태에 편집 기록
4. LLM이 `apply_edits()` 호출
5. FastAPI에 마크다운 저장
6. 프론트 에디터 내용 갱신

### 7.3 엑셀 편집

1. 사용자가 "A열 합계를 B1에 넣어줘" 입력
2. LLM이 `get_sheet(0)`, `update_cell(sheet_index=0, row=0, col=1, value="=SUM(A:A)")` 호출
3. LLM이 `apply_changes()` 호출
4. FastAPI에 XLSX 저장
5. Luckysheet 갱신

---

## 8. 검증 계획

### 8.1 단위/통합 테스트

- `app/ai-backend/tests/chat.test.ts`
  - `streamText` + tool call 흐름
  - `apply_annotations` 시 Storage 저장
  - `apply_edits` 시 FastAPI 호출

### 8.2 수동 검증

- [ ] Agent Input Bar가 화면 하단 중앙에 표시
- [ ] 클릭 시 Agent Chat Modal 열림
- [ ] PDF 주석 요청 -> 주석 생성 -> 뷰어 반영
- [ ] 마크다운 요청 -> 에디터 텍스트 변경
- [ ] 엑셀 요청 -> Luckysheet 셀 변경
- [ ] 기존 FastAPI 기능 회귀 테스트

---

## 9. 리스크 및 완화책

| 리스크 | 완화책 |
|--------|--------|
| ai SDK 5.x UIMessage 프로토콜 | `createUIMessageStreamResponse`를 직접 사용하여 표준 구현 |
| Node.js/FastAPI 인증 공유 | FastAPI의 인증 로직을 미들웨어로 재구현하거나, JWT 검증 공유 |
| PDF 주석 서버 지연 | Chat Modal에 처리 중 상태 표시, polling으로 job 상태 갱신 |
| 도구 인자 매핑 | `get_elements` 결과에 안정적 인덱스 부여, LLM이 인덱스로만 참조 |
| Luckysheet 상태 동기화 | `luckysheet.setcellvalue` API 사용, 저장 후 job reload |

---

## 10. 예상 작업 단계

1. Node.js AI 백엔드 보일러플레이트 생성
2. 프론트엔드 ai SDK 5.x 설치 및 vite 프록시 설정
3. AgentInputBar + AgentChatModal 기본 UI 구현
4. `/api/ai/chat` 기본 스트리밍 연결
5. PDF 주석 도구 구현
6. 마크다운 에디터 도구 구현
7. 엑셀 조작 도구 구현
8. 기존 LangGraph 코드 제거
9. 테스트 및 버그 수정
