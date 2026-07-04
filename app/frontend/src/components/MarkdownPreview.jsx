// [Flow: Step 1 (마크다운을 HTML로 파싱) -> Step 2 (페이지 마커로 섹션 분할) -> Step 3 (content-visibility로 가상화) -> Step 4 (scrollToPage 제공)]
import { forwardRef, memo, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { marked } from "marked";

const PAGE_MARKER_RE = /<!--\s*페이지\s*(\d+)\s*-->/gi;

/**
 * [Flow: Step 1 (마크다운을 페이지 마커 기준으로 분할) -> Step 2 (각 페이지 번호와 콘텐츠 추출) -> Step 3 (빈 페이지 제거)]
 * @param {string} markdown
 * @returns {Array<{pageNum: number, html: string}>}
 */
function splitMarkdownByPages(markdown) {
  if (!markdown) return [];
  const matches = Array.from(markdown.matchAll(PAGE_MARKER_RE));
  if (!matches.length) {
    return [{ pageNum: 1, html: marked.parse(markdown) }];
  }

  const pages = [];
  for (let i = 0; i < matches.length; i++) {
    const pageNum = parseInt(matches[i][1], 10);
    const start = matches[i].index + matches[i][0].length;
    const end = i + 1 < matches.length ? matches[i + 1].index : markdown.length;
    const content = markdown.slice(start, end).trim();
    if (!content) continue;
    pages.push({ pageNum, html: marked.parse(content) });
  }
  return pages;
}

/**
 * [Flow: Step 1 (markdown prop 수신) -> Step 2 (페이지별 HTML로 분할) -> Step 3 (가상화된 컨테이너에 렌더링) -> Step 4 (scrollToPage API 제공)]
 * @param {object} props
 * @param {string} props.markdown
 */
const MarkdownPreview = memo(forwardRef(function MarkdownPreview({ markdown }, ref) {
  const containerRef = useRef(null);
  const sectionRefs = useRef({});
  const [visiblePages, setVisiblePages] = useState(new Set());

  const pages = useMemo(() => splitMarkdownByPages(markdown), [markdown]);

  /**
   * [Flow: Step 1 (IntersectionObserver 설정) -> Step 2 (보이는 페이지 번호 추적) -> Step 3 (초기 가시 페이지 설정)]
   */
  useEffect(() => {
    const container = containerRef.current;
    if (!container || pages.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        setVisiblePages((prev) => {
          const next = new Set(prev);
          entries.forEach((entry) => {
            const pageNum = Number(entry.target.dataset.page);
            if (entry.isIntersecting) {
              next.add(pageNum);
            } else {
              next.delete(pageNum);
            }
          });
          return next;
        });
      },
      { root: container, rootMargin: "200px", threshold: 0 }
    );

    const sections = container.querySelectorAll("[data-page-section]");
    sections.forEach((section) => observer.observe(section));

    return () => observer.disconnect();
  }, [pages]);

  /**
   * [Flow: Step 1 (페이지 번호로 해당 섹션 탐색) -> Step 2 (섹션이 있으면 컨테이너 스크롤) -> Step 3 (섹션 상단을 컨테이너 상단에 맞춤)]
   * @param {number} pageNum
   */
  const scrollToPage = (pageNum) => {
    const container = containerRef.current;
    const section = sectionRefs.current[pageNum];
    if (!container || !section) return;
    const top = section.offsetTop - container.offsetTop;
    container.scrollTo({ top, behavior: "smooth" });
  };

  useImperativeHandle(ref, () => ({ scrollToPage }), []);

  if (!markdown) {
    return (
      <div className="flex-1 flex items-center justify-center text-on-surface-variant text-sm">
        No content
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto p-6 custom-scrollbar bg-white"
      data-oid="markdown-preview"
    >
      <div className="prose max-w-none focus:outline-none">
        {pages.map(({ pageNum, html }) => {
          const isVisible = visiblePages.has(pageNum);
          return (
            <div
              key={pageNum}
              ref={(el) => {
                sectionRefs.current[pageNum] = el;
              }}
              data-page-section
              data-page={pageNum}
              className="markdown-page-section"
              style={{ contentVisibility: isVisible ? "visible" : "auto", containIntrinsicHeight: "auto 300px" }}
              dangerouslySetInnerHTML={{ __html: html }}
            />
          );
        })}
      </div>
    </div>
  );
}));

export default MarkdownPreview;
