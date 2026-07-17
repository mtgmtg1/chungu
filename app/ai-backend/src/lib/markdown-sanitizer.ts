// [Flow: Step 1 (data:image base64 정규식 정의) -> Step 2 (HTML/markdown/raw data URI 매칭)
//       -> Step 3 (placeholder로 치환) -> Step 4 (정제된 마크다운 반환)]
// 마크다운에서 data:image base64 인라인 이미지를 제거해 LLM 프롬프트 토큰 폭증을 방지한다.

const HTML_IMG_BASE64_RE = /<img[^>]*src=(["'])(data:image\/[^;\s]+;base64,[A-Za-z0-9+/=]+)\1[^>]*>/gi;
const MD_IMG_BASE64_RE = /!\[([^\]]*)\]\((data:image\/[^;\s]+;base64,[A-Za-z0-9+/=]+)\)/gi;
const BASE64_DATA_URI_RE = /data:image\/[^;\s]+;base64,[A-Za-z0-9+/=]+/gi;

export function sanitizeMarkdownForLLM(markdown: string, placeholder = '[image]'): string {
  if (!markdown) {
    return markdown;
  }

  let text = markdown.replace(HTML_IMG_BASE64_RE, placeholder);
  text = text.replace(MD_IMG_BASE64_RE, (_match, alt) => (alt ? `![${alt}](${placeholder})` : placeholder));
  text = text.replace(BASE64_DATA_URI_RE, placeholder);
  return text;
}
