// [Flow: Step 1 (browserless 서버 연결) -> Step 2 (스크린샷/PDF/텍스트 추출 도구 생성)
//       -> Step 3 (도구 객체 반환)]
// browserless 원격 브라우저 도구. a1 의 기존 browserless 서버를 공유하여
// 각 sandbox VM 에 Chrome 을 설치하지 않아 메모리를 절약한다.
import { tool } from 'ai';
import { z } from 'zod';

// browserless 서버 URL (a1, 기존 구동 중)
const BROWSERLESS_URL =
  process.env.BROWSERLESS_URL || 'http://192.168.1.50:20047';

// browserless API 토큰 (인증이 활성화된 경우)
const BROWSERLESS_TOKEN = process.env.BROWSERLESS_TOKEN || '';

/**
 * [Flow: Step 1 (URL + 옵션 수신) -> Step 2 (browserless /screenshot API 호출)
 *       -> Step 3 (PNG 바이너리 반환)]
 *
 * browserless 서버에 스크린샷 요청을 보낸다.
 *
 * @param url 캡처할 웹페이지 URL
 * @param fullPage 전체 페이지 캡처 여부
 * @returns PNG 이미지 base64 문자열
 */
async function takeScreenshot(
  url: string,
  fullPage: boolean = true,
): Promise<string> {
  const apiUrl = `${BROWSERLESS_URL}/screenshot`;
  const params = new URLSearchParams();
  if (BROWSERLESS_TOKEN) params.set('token', BROWSERLESS_TOKEN);

  const response = await fetch(`${apiUrl}?${params}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      url,
      options: { fullPage, type: 'png' },
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`browserless screenshot failed: ${response.status} ${text}`);
  }

  // browserless 는 PNG 바이너리를 직접 반환
  const buffer = await response.arrayBuffer();
  return Buffer.from(buffer).toString('base64');
}

/**
 * [Flow: Step 1 (URL 수신) -> Step 2 (browserless /pdf API 호출)
 *       -> Step 3 (PDF 바이너리 반환)]
 *
 * browserless 서버에 PDF 변환 요청을 보낸다.
 *
 * @param url PDF 로 변환할 웹페이지 URL
 * @returns PDF base64 문자열
 */
async function convertToPdf(url: string): Promise<string> {
  const apiUrl = `${BROWSERLESS_URL}/pdf`;
  const params = new URLSearchParams();
  if (BROWSERLESS_TOKEN) params.set('token', BROWSERLESS_TOKEN);

  const response = await fetch(`${apiUrl}?${params}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      url,
      options: { format: 'A4', printBackground: true },
    }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`browserless PDF failed: ${response.status} ${text}`);
  }

  const buffer = await response.arrayBuffer();
  return Buffer.from(buffer).toString('base64');
}

/**
 * [Flow: Step 1 (URL 수신) -> Step 2 (browserless /content API 호출)
 *       -> Step 3 (텍스트 반환)]
 *
 * browserless 서버에 페이지 텍스트 추출 요청을 보낸다.
 *
 * @param url 텍스트를 추출할 웹페이지 URL
 * @returns 페이지 텍스트
 */
async function extractText(url: string): Promise<string> {
  const apiUrl = `${BROWSERLESS_URL}/content`;
  const params = new URLSearchParams();
  if (BROWSERLESS_TOKEN) params.set('token', BROWSERLESS_TOKEN);

  const response = await fetch(`${apiUrl}?${params}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`browserless content failed: ${response.status} ${text}`);
  }

  // browserless /content 는 JSON 으로 페이지 콘텐츠 반환
  const data = (await response.json()) as { text?: string; content?: string };
  return data.text || data.content || JSON.stringify(data);
}

/**
 * [Flow: Step 1 (browserless 도구들 정의) -> Step 2 (도구 객체 반환)]
 *
 * browserless 원격 브라우저 도구 맵을 생성한다.
 * 각 sandbox VM 에 Chrome 을 설치하지 않고 a1 의 browserless 서버를 공유한다.
 *
 * @returns browserless 도구 맵
 */
export function createBrowserlessTools() {
  // ========================================
  // 도구 1: 웹페이지 스크린샷
  // ========================================
  const browseWeb = tool({
    description:
      '웹페이지를 캡처하여 스크린샷을 반환한다. 원격 browserless 서버를 사용하므로 ' +
      'sandbox VM 에 Chrome 이 설치되어 있지 않아도 된다. ' +
      '반환값은 base64 인코딩된 PNG 이미지다.',
    inputSchema: z.object({
      url: z.string().url().describe('캡처할 웹페이지 URL'),
      fullPage: z
        .boolean()
        .default(true)
        .describe('전체 페이지 캡처 여부 (기본: true)'),
    }),
    execute: async ({ url, fullPage }) => {
      try {
        const base64 = await takeScreenshot(url, fullPage);
        return {
          status: 'ok',
          url,
          image_base64: base64,
          image_size: base64.length,
        };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return { status: 'error', url, error: msg };
      }
    },
  });

  // ========================================
  // 도구 2: 웹페이지 PDF 변환
  // ========================================
  const convertWebToPdf = tool({
    description:
      '웹페이지를 PDF 로 변환한다. 원격 browserless 서버를 사용한다. ' +
      '반환값은 base64 인코딩된 PDF 다.',
    inputSchema: z.object({
      url: z.string().url().describe('PDF 로 변환할 웹페이지 URL'),
    }),
    execute: async ({ url }) => {
      try {
        const base64 = await convertToPdf(url);
        return {
          status: 'ok',
          url,
          pdf_base64: base64,
          pdf_size: base64.length,
        };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return { status: 'error', url, error: msg };
      }
    },
  });

  // ========================================
  // 도구 3: 웹페이지 텍스트 추출
  // ========================================
  const extractWebText = tool({
    description:
      '웹페이지의 텍스트 콘텐츠를 추출한다. 원격 browserless 서버를 사용하여 ' +
      'JavaScript 렌더링이 필요한 동적 페이지도 처리할 수 있다.',
    inputSchema: z.object({
      url: z.string().url().describe('텍스트를 추출할 웹페이지 URL'),
    }),
    execute: async ({ url }) => {
      try {
        const rawText = await extractText(url);
        // [Flow: 출력 크기 제한 — 텍스트를 3000자로 잘라서 토큰 소비 절약]
        const truncated = rawText.length > 3000
          ? rawText.slice(0, 3000) + '\n...[truncated]'
          : rawText;
        return {
          status: 'ok',
          url,
          text: truncated,
          text_length: rawText.length,
        };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return { status: 'error', url, error: msg };
      }
    },
  });

  return {
    browse_web: browseWeb,
    convert_web_to_pdf: convertWebToPdf,
    extract_web_text: extractWebText,
  };
}
