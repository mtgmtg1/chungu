// [Flow: Step 1 (압축 대상 텍스트 수신) -> Step 2 (임계값 확인) -> Step 3 (LLMLingua-2 서비스 호출)
//       -> Step 4 (동적 rate 로 압축된 텍스트 반환, 실패 시 원본 폴백)]
// LLMLingua-2 Python 마이크로서비스와 통신하는 Node.js 클라이언트.
// AI 백엔드의 prepareStep 콜백에서 도구 결과 JSON이 임계값을 초과할 때 호출된다.
// 동적 압축: Python 서비스가 텍스트 크기에 따라 rate 를 자동 선택한다 (논문 Appendix L).

// [Flow: LLMLingua-2 서비스 URL — 환경변수에서 읽기, 기본값은 로컬 개발용]
const LLMLINGUA_URL = process.env.LLMLINGUA_URL || 'http://localhost:8000';

// [Flow: 요청 타임아웃 — 30초 (압축 처리 시간 고려)]
const REQUEST_TIMEOUT_MS = 30000;

/**
 * [Flow: Step 1 (텍스트 길이 확인) -> Step 2 (임계값 초과 여부 판단) -> Step 3 (반환)]
 *
 * shouldCompress — 텍스트가 임계값을 초과하는지 확인한다.
 * 압축은 텍스트가 충분히 클 때만 수행하여 오버헤드를 피한다.
 *
 * @param text 검사할 텍스트
 * @param thresholdChars 임계값 (문자 수, 기본 4000)
 * @returns 압축 필요 여부
 */
export function shouldCompress(text: string, thresholdChars: number = 4000): boolean {
  if (!text || text.length === 0) return false;
  return text.length > thresholdChars;
}

/**
 * [Flow: Step 1 (텍스트 수신) -> Step 2 (LLMLingua-2 서비스 POST /compress 호출 with dynamic=true)
 *       -> Step 3 (Python 서비스가 동적 rate 선택) -> Step 4 (압축된 텍스트 반환)
 *       -> Step 5 (실패 시 원본 텍스트 폴백)]
 *
 * compressToolResults — 도구 결과 JSON 문자열을 LLMLingua-2 로 압축한다.
 * Python 마이크로서비스(LLMLINGUA_URL)에 POST /compress 요청을 보낸다.
 * dynamic=true 시 Python 서비스가 텍스트 크기에 따라 rate 를 자동 선택한다:
 *   4000~8000자 → rate=0.5 (2x), 8000~20000자 → rate=0.3 (3x), 20000자+ → rate=0.2 (5x)
 * 서비스가 응답하지 않거나 에러가 발생하면 원본 텍스트를 그대로 반환한다 (폴백).
 *
 * @param text 압축할 텍스트 (도구 결과 JSON 문자열)
 * @param dynamic 동적 rate 선택 사용 여부 (기본 true — Python 서비스가 크기 기반으로 선택)
 * @returns 압축된 텍스트 (실패 시 원본)
 */
export async function compressToolResults(
  text: string,
  dynamic: boolean = true,
): Promise<string> {
  if (!text || text.length === 0) return text;

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    const response = await fetch(`${LLMLINGUA_URL}/compress`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, dynamic }),
      signal: controller.signal,
    });

    clearTimeout(timeout);

    if (!response.ok) {
      console.error(
        `[llmlingua] compression service returned ${response.status}: ${await response.text()}`,
      );
      return text;
    }

    const data = (await response.json()) as {
      compressed: string;
      original_length: number;
      compressed_length: number;
      reduction_percent: number;
      applied_rate: number;
      elapsed_ms: number;
    };

    // [Flow: 동적 rate 로그 — Python 서비스가 선택한 rate 출력]
    console.log(
      `[llmlingua] dynamic rate=${data.applied_rate} ${data.original_length} -> ${data.compressed_length} chars (${data.reduction_percent}% reduction, ${data.elapsed_ms}ms)`,
    );

    return data.compressed;
  } catch (err) {
    // [Flow: 폴백 — 서비스 미가동/타임아웃/네트워크 오류 시 원본 반환]
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[llmlingua] compression failed, using original: ${msg}`);
    return text;
  }
}
