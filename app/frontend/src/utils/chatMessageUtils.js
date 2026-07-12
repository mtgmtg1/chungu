// [Flow: Step 1 (UIMessage[] 수신) -> Step 2 (각 메시지의 parts 순회)
//       -> Step 3 (도구 part의 input/output이 임계값 초과면 요약으로 교체)
//       -> Step 4 (요약된 메시지 배열 반환)]
// 에이전트 채팅 대화 이력을 DB에 저장할 때 도구 결과(input/output)를 요약하여
// 저장 용량을 최적화하는 유틸리티.
// 도구 이름, state, text part 등 사용자에게 표시되는 정보는 그대로 유지하고,
// 용량이 큰 도구 input/output JSON만 핵심 필드 + 크기 정보로 압축한다.

// [Flow: 도구 input/output이 이 값(문자 수)을 초과하면 요약으로 대체]
const TOOL_VALUE_THRESHOLD_CHARS = 500;

// [Flow: 요약 시 추출할 핵심 필드 — 도구 결과의 메타데이터성 정보]
const SUMMARY_FIELDS = [
  'ok', 'status', 'error', 'message', 'msg',
  'count', 'length', 'total', 'size',
  'page', 'page_no', 'pageIndex', 'pages',
  'summary', 'result', 'id', 'job_id',
  'requires_approval', 'approved',
  'path', 'file', 'filename',
];

/**
 * [Flow: Step 1 (값의 JSON 문자열 길이 계산) -> Step 2 (임계값 초과면 true 반환)]
 *
 * @param {any} value - 도구 input 또는 output
 * @param {number} threshold - 임계값 (문자 수)
 * @returns {boolean} 임계값 초과 여부
 */
function isValueLarge(value, threshold = TOOL_VALUE_THRESHOLD_CHARS) {
  if (value === undefined || value === null) return false;
  try {
    return JSON.stringify(value).length > threshold;
  } catch {
    return String(value).length > threshold;
  }
}

/**
 * [Flow: Step 1 (객체에서 핵심 필드 추출) -> Step 2 (원본 크기 정보 추가) -> Step 3 (요약 객체 반환)]
 *
 * 객체의 모든 필드를 저장하는 대신 SUMMARY_FIELDS에 나열된 핵심 필드만 추출하여
 * 용량을 줄인다. 원본 크기 정보를 추가하여 디버깅 시 참고할 수 있도록 한다.
 *
 * @param {Object} obj - 요약할 객체
 * @returns {Object} 핵심 필드 + _summary 메타데이터
 */
function summarizeObject(obj) {
  const summary = {};
  for (const field of SUMMARY_FIELDS) {
    if (obj[field] !== undefined) {
      summary[field] = obj[field];
    }
  }
  // [Flow: 원본 크기 정보 추가 — 디버깅 시 참고용]
  try {
    summary._summary = {
      originalChars: JSON.stringify(obj).length,
      truncated: true,
    };
  } catch {
    summary._summary = { truncated: true };
  }
  return summary;
}

/**
 * [Flow: Step 1 (값의 타입 판별) -> Step 2 (임계값 미만이면 원본 그대로)
 *       -> Step 3 (문자열: 처음 N자 + 잘림 표시) -> Step 4 (객체/배열: 핵심 필드 추출)
 *       -> Step 5 (기타 타입: String() 변환 후 잘림)]
 *
 * 도구 input/output 값을 임계값에 따라 요약한다.
 * 작은 값은 그대로 유지하여 정확한 복원을 보장하고,
 * 큰 값만 요약하여 저장 용량을 절약한다.
 *
 * @param {any} value - 도구 input 또는 output
 * @returns {any} 원본 또는 요약된 값
 */
export function summarizeToolValue(value) {
  if (!isValueLarge(value)) return value;

  // [Flow: 문자열 — 처음 N자 + 잘림 표시]
  if (typeof value === 'string') {
    return `${value.slice(0, TOOL_VALUE_THRESHOLD_CHARS)}…[truncated, ${value.length} chars total]`;
  }

  // [Flow: 배열 — 첫 번째 요소 + 길이 정보]
  if (Array.isArray(value)) {
    return {
      _summary: {
        type: 'array',
        length: value.length,
        originalChars: JSON.stringify(value).length,
        truncated: true,
      },
      firstItem: value[0] ? summarizeToolValue(value[0]) : undefined,
    };
  }

  // [Flow: 객체 — 핵심 필드 추출]
  if (typeof value === 'object') {
    return summarizeObject(value);
  }

  // [Flow: 기타 타입 — String() 변환 후 잘림]
  const str = String(value);
  return `${str.slice(0, TOOL_VALUE_THRESHOLD_CHARS)}…[truncated, ${str.length} chars total]`;
}

/**
 * [Flow: Step 1 (UIMessage part 판별) -> Step 2 (도구 part면 input/output 요약 적용)
 *       -> Step 3 (text/reasoning part는 그대로 유지) -> Step 4 (요약된 part 반환)]
 *
 * 단일 UIMessage part의 도구 input/output을 요약한다.
 * 도구 이름, state, errorText 등 사용자에게 표시되는 메타데이터는 유지한다.
 *
 * @param {Object} part - UIMessage part
 * @returns {Object} 요약된 part (원본이 작으면 그대로)
 */
function compactToolPart(part) {
  const type = part.type;
  const isToolPart = type === 'dynamic-tool' || (typeof type === 'string' && type.startsWith('tool-'));
  if (!isToolPart) return part;

  const compacted = { ...part };
  // [Flow: input이 크면 요약 — 도구 호출 파라미터가 큰 경우 (예: save_annotations)]
  if (part.input !== undefined) {
    compacted.input = summarizeToolValue(part.input);
  }
  // [Flow: output이 크면 요약 — 도구 실행 결과가 큰 경우 (예: get_elements, view_page)]
  if (part.output !== undefined) {
    compacted.output = summarizeToolValue(part.output);
  }
  return compacted;
}

/**
 * [Flow: Step 1 (UIMessage[] 순회) -> Step 2 (각 메시지의 parts를 compactToolPart로 변환)
 *       -> Step 3 (도구 결과가 요약된 메시지 배열 반환)]
 *
 * 에이전트 채팅 대화 이력을 DB에 저장하기 전에 도구 결과를 요약하여
 * 저장 용량을 최적화한다. 사용자 텍스트, 도구 이름, 도구 상태 등
 * 사용자에게 표시되는 정보는 그대로 유지된다.
 *
 * 주의: 요약된 메시지는 복원 후 도구 상세 결과를 볼 수 없다.
 * 도구 이름/상태/input 요약/output 요약은 유지되므로 대화 맥락 파악에는 충분하다.
 *
 * @param {Array} messages - UIMessage 배열
 * @returns {Array} 도구 결과가 요약된 UIMessage 배열
 */
export function compactMessagesForStorage(messages) {
  if (!Array.isArray(messages)) return messages;
  return messages.map((message) => {
    if (!message.parts) return message;
    return {
      ...message,
      parts: message.parts.map(compactToolPart),
    };
  });
}
