// [Flow: Step 1 (환경변수에서 LLM endpoint/model/api_key/thinking_budget 조회)
//       -> Step 2 (transformRequestBody로 최상위 thinking_token_budget + chat_template_kwargs.enable_thinking 주입)
//       -> Step 3 (provider 생성) -> Step 4 (model 반환)]
// Vercel AI SDK의 @ai-sdk/openai-compatible provider로 vLLM/llama.cpp 등 OpenAI 호환 endpoint에 연결한다.
// @ai-sdk/openai 는 OpenAI 전용(Responses API 등)이므로, OpenAI 호환 서버에는 본 패키지를 사용한다.
// Gemma-4 모델의 thinking 기능을 활성화하기 위해 두 가지 파라미터를 주입한다:
//   1. chat_template_kwargs.enable_thinking = true  (Gemma-4 chat template용 — thinking 모드 활성화)
//   2. thinking_token_budget = N                     (vLLM ChatCompletionRequest 최상위 필드 — 토큰 예산)
// 참고: vLLM 공식 문서(https://docs.vllm.ai/en/stable/features/reasoning_outputs)에 따르면
//   - Gemma 4는 기본적으로 reasoning이 비활성화되어 있으며 enable_thinking=true로 활성화해야 함
//   - thinking_token_budget는 chat_template_kwargs가 아닌 요청 바디 최상위 필드임
import { createOpenAICompatible } from '@ai-sdk/openai-compatible';

// [Flow: thinking budget — Gemma-4 모델의 사고 토큰 예산 (기본값 256, 환경변수로 오버라이드 가능)]
const DEFAULT_THINKING_BUDGET = 256;

/**
 * [Flow: Step 1 (요청 바디 수신) -> Step 2 (최상위에 thinking_token_budget 주입)
 *       -> Step 3 (chat_template_kwargs에 enable_thinking=true 주입) -> Step 4 (변환된 바디 반환)]
 *
 * withThinkingConfig — vLLM 요청 바디에 Gemma-4 thinking 활성화 파라미터를 주입한다.
 * Python 백엔드의 with_gemma4_kwargs(enable_thinking=False)와 반대 역할: AI 백엔드에서는 thinking을 활성화한다.
 *
 * vLLM ChatCompletionRequest 스키마 기준:
 *   - thinking_token_budget: int | None  (최상위 필드 — 토큰 예산 제어)
 *   - chat_template_kwargs: { enable_thinking: bool }  (Gemma-4 chat template용)
 *
 * @param body 원본 요청 바디 (OpenAI chat completions 형식)
 * @param thinkingBudget thinking 토큰 예산 (0 이하면 thinking 비활성화)
 * @returns thinking 파라미터가 주입된 요청 바디
 */
function withThinkingConfig(body: Record<string, any>, thinkingBudget: number): Record<string, any> {
  // [Flow: thinking_budget가 0 이하면 thinking 비활성화 — 원본 바디 그대로 반환]
  if (thinkingBudget <= 0) return body;
  return {
    ...body,
    // [Flow: 최상위 필드 — vLLM ChatCompletionRequest.thinking_token_budget]
    thinking_token_budget: thinkingBudget,
    // [Flow: chat template kwargs — Gemma-4의 enable_thinking 스위치]
    chat_template_kwargs: {
      ...(body.chat_template_kwargs || {}),
      enable_thinking: true,
    },
  };
}

/**
 * [Flow: Step 1 (LLM_ENDPOINT, LLM_MODEL, LLM_API_KEY, LLM_THINKING_BUDGET 읽기) -> Step 2 (base_url 정규화)
 *       -> Step 3 (transformRequestBody로 thinking 설정 주입) -> Step 4 (createOpenAICompatible provider 생성)
 *       -> Step 5 (모델 함수 반환)]
 *
 * 기존 Python FastAPI의 settings.default_llm_endpoint 와 동일한 endpoint를 사용한다.
 * 인증이 없는 로컬 vLLM/llama.cpp endpoint의 경우 api_key는 더미 값을 사용한다.
 * LLM_THINKING_BUDGET 환경변수로 thinking 토큰 예산을 조절할 수 있다 (기본값 512).
 *
 * @returns Vercel AI SDK model 호출 함수
 */
export function buildModel() {
  const endpoint = process.env.LLM_ENDPOINT || 'http://localhost:18080/v1';
  const modelName = process.env.LLM_MODEL || 'default';
  const apiKey = process.env.LLM_API_KEY || 'not-needed';
  const thinkingBudget = parseInt(process.env.LLM_THINKING_BUDGET || String(DEFAULT_THINKING_BUDGET), 10);

  // endpoint가 /v1 로 끝나지 않으면 자동으로 /v1 을 붙인다 (OpenAI 호환 API 규약).
  const baseURL = endpoint.endsWith('/v1')
    ? endpoint
    : `${endpoint.replace(/\/$/, '')}/v1`;

  const provider = createOpenAICompatible({
    name: 'proof-llm',
    baseURL,
    apiKey,
    // vLLM/llama.cpp는 usage 정보를 스트림에 포함시키지 않을 수 있으므로 안전하게 false 로 둔다.
    includeUsage: false,
    // [Flow: transformRequestBody — 모든 요청에 thinking_token_budget + enable_thinking 주입]
    transformRequestBody: (args: Record<string, any>) => withThinkingConfig(args, thinkingBudget),
  });

  // chatModel 은 /chat/completions 엔드포인트를 호출한다.
  return provider.chatModel(modelName);
}
