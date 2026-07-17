#!/usr/bin/env python3
# [Flow: Step 1 (정규식 정의) -> Step 2 (HTML/markdown/raw data URI 매칭)
#       -> Step 3 (placeholder로 치환) -> Step 4 (정제된 마크다운 반환)]
"""마크다운에서 data:image base64 인라인 이미지를 제거해 LLM 프롬프트 토큰 폭증을 방지한다."""
import re


# HTML <img src="data:image/...;base64,..."> 또는 src='...'
_HTML_IMG_BASE64_RE = re.compile(
    r'<img[^>]*src=(["\'])(data:image/[^;\s]+;base64,[A-Za-z0-9+/=]+)\1[^>]*>',
    re.IGNORECASE,
)

# 마크다운 ![alt](data:image/...;base64,...)
_MD_IMG_BASE64_RE = re.compile(
    r'!\[([^\]]*)\]\((data:image/[^;\s]+;base64,[A-Za-z0-9+/=]+)\)',
    re.IGNORECASE,
)

# 태그 밖에 그대로 남아 있는 data URI (방어적)
_BASE64_DATA_URI_RE = re.compile(
    r'data:image/[^;\s]+;base64,[A-Za-z0-9+/=]+',
    re.IGNORECASE,
)


def sanitize_markdown_for_llm(markdown: str, placeholder: str = "[image]") -> str:
    """마크다운 내 data:image base64 인라인 이미지를 placeholder로 치환한다.

    Args:
        markdown: 정제할 마크다운 문자열
        placeholder: 이미지 대체 문자열

    Returns:
        base64 이미지가 placeholder로 치환된 마크다운
    """
    if not markdown:
        return markdown

    text = _HTML_IMG_BASE64_RE.sub(placeholder, markdown)
    text = _MD_IMG_BASE64_RE.sub(lambda m: f"![{m.group(1)}]({placeholder})" if m.group(1).strip() else placeholder, text)
    text = _BASE64_DATA_URI_RE.sub(placeholder, text)
    return text
