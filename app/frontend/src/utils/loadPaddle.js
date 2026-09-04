// [Flow: Step 1 (이미 로드됐으면 즉시 반환) -> Step 2 (진행 중인 로드가 있으면 그 Promise 재사용)
//       -> Step 3 (script 태그 주입 후 window.Paddle 확정 시 resolve)]
//
// Paddle SDK 는 결제 화면(PaymentPage / PricePage)에서만 필요하다. 예전에는 index.html 에
// 동기 <script> 로 박혀 있어서, 파서가 모든 방문자에 대해 cdn.paddle.com 왕복을 끝낼 때까지
// 앱 모듈 태그에 도달하지 못했다 — 결제를 열지 않는 사용자까지 크리티컬 패스 비용을 냈다.
//
// 동시에 정확성 문제도 있었다. 호출부가 `if (window.Paddle)` 로 감싸고 있었기 때문에,
// 스크립트가 늦게 도착하면 초기화나 체크아웃이 조용히 통째로 생략됐다. 여기서 Promise 로
// 도착을 기다리면 그 경합이 사라진다.

const PADDLE_SDK_URL = "https://cdn.paddle.com/paddle/v2/paddle.js";

let paddlePromise = null;

/**
 * Paddle SDK 를 필요한 시점에 한 번만 로드한다.
 *
 * @returns {Promise<object|null>} window.Paddle. 로드 실패 시 null (호출부는 checkout_url 폴백 사용).
 */
export function loadPaddle() {
  if (typeof window === "undefined") return Promise.resolve(null);
  if (window.Paddle) return Promise.resolve(window.Paddle);
  if (paddlePromise) return paddlePromise;

  paddlePromise = new Promise((resolve) => {
    const existing = document.querySelector(`script[src="${PADDLE_SDK_URL}"]`);
    const script = existing || document.createElement("script");
    const finish = () => resolve(window.Paddle || null);

    script.addEventListener("load", finish);
    script.addEventListener("error", () => {
      // 다음 시도에서 다시 받을 수 있도록 캐시를 비운다.
      paddlePromise = null;
      resolve(null);
    });

    if (!existing) {
      script.src = PADDLE_SDK_URL;
      script.async = true;
      document.head.appendChild(script);
    }
  });
  return paddlePromise;
}

/**
 * Paddle SDK 를 로드하고 초기화한다. 여러 번 호출해도 안전하다.
 *
 * @param {string} token Paddle client-side token.
 * @returns {Promise<object|null>} 초기화된 window.Paddle 또는 null.
 */
export async function initPaddle(token) {
  const paddle = await loadPaddle();
  if (!paddle) return null;
  try {
    paddle.Initialize({ token });
  } catch {
    // 중복 Initialize 는 무해하다 — 이미 초기화된 인스턴스를 그대로 쓴다.
  }
  return paddle;
}
