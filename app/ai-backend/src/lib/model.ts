// [Flow: Step 1 (환경변수에서 LLM endpoint/model/api_key 조회) -> Step 2 (OpenAI-compatible provider 생성) -> Step 3 (model 함수 반환)]
// Vercel AI SDK의 @ai-sdk/openai-compatible provider로 vLLM/llama.cpp 등 OpenAI 호환 endpoint에 연결한다.
// @ai-sdk/openai 는 OpenAI 전용(Responses API 등)이므로, OpenAI 호환 서버에는 본 패키지를 사용한다.
import { createOpenAICompatible } from '@ai-sdk/openai-compatible';

/**
 * [Flow: Step 1 (LLM_ENDPOINT, LLM_MODEL, LLM_API_KEY 읽기) -> Step 2 (base_url 정규화)
 *       -> Step 3 (createOpenAICompatible provider 생성) -> Step 4 (모델 함수 반환)]
 *
 * 기존 Python FastAPI의 settings.default_llm_endpoint 와 동일한 endpoint를 사용한다.
 * 인증이 없는 로컬 vLLM/llama.cpp endpoint의 경우 api_key는 더미 값을 사용한다.
 *
 * @returns Vercel AI SDK model 호출 함수
 */
export function buildModel() {
  const endpoint = process.env.LLM_ENDPOINT || 'http://localhost:18080/v1';
  const modelName = process.env.LLM_MODEL || 'default';
  const apiKey = process.env.LLM_API_KEY || 'not-needed';

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
  });

  // chatModel 은 /chat/completions 엔드포인트를 호출한다.
  return provider.chatModel(modelName);
}
