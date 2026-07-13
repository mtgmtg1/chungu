// [Flow: Step 1 (TableOfContents 확장에서 anchors 배열 수신)
//       -> Step 2 (heading depth별 들여쓰기 + 활성 heading 하이라이트)
//       -> Step 3 (클릭 시 해당 heading으로 스크롤)]
//
// 우측 미니맵 TOC 사이드바. ProseMirror editor.view.dom 내에서
// heading id 속성을 가진 요소로 scrollIntoView 한다.
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { List, ChevronUp } from "lucide-react";

/**
 * [Flow: Step 1 (anchors 배열 순회) -> Step 2 (depth별 들여쓰기 + 활성 하이라이트) -> Step 3 (클릭 시 scrollIntoView)]
 *
 * @param {Object} props
 * @param {Array<{id:string;content:string;depth:number;isActive:boolean}>} props.anchors - TableOfContents onUpdate 데이터
 * @param {import('@tiptap/react').Editor|null} props.editor - 스크롤 대상 에디터
 * @param {boolean} props.open - 사이드바 펼침 여부
 * @param {Function} props.onToggle - 사이드바 펼침/접힘 토글 콜백
 */
export default function TocSidebar({ anchors, editor, open, onToggle }) {
  const { t } = useTranslation();
  const [hoveredId, setHoveredId] = useState(null);

  if (!open) {
    return (
      <div
        className="toc-sidebar-collapsed flex flex-col items-center py-2 border-l border-outline-variant bg-surface"
        data-oid="toc-collapsed"
      >
        <button
          type="button"
          onClick={onToggle}
          className="p-1.5 rounded-md hover:bg-surface-container-high text-on-surface-variant"
          aria-label={t("page:components.tocTitle")}
          data-oid="toc-expand-btn"
        >
          <List size={18} />
        </button>
      </div>
    );
  }

  /**
   * [Flow: Step 1 (heading id로 DOM 요소 탐색) -> Step 2 (scrollIntoView로 부드러운 스크롤)]
   *
   * @param {string} id - heading 노드의 id attribute
   */
  const handleJump = (id) => {
    if (!editor || !editor.view) return;
    const el = editor.view.dom.querySelector(`[data-toc-id="${id}"], #${CSS.escape(id)}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  return (
    <div
      className="toc-sidebar flex flex-col border-l border-outline-variant bg-surface"
      style={{ width: "220px", flexShrink: 0 }}
      data-oid="toc-sidebar"
    >
      <div
        className="flex items-center justify-between px-3 py-2 border-b border-outline-variant"
        data-oid="toc-header"
      >
        <span
          className="text-xs font-semibold text-on-surface-variant uppercase tracking-wide"
          data-oid="toc-title"
        >
          {t("page:components.tocTitle")}
        </span>
        <button
          type="button"
          onClick={onToggle}
          className="p-1 rounded-md hover:bg-surface-container-high text-on-surface-variant"
          aria-label={t("page:components.tocToggle")}
          data-oid="toc-collapse-btn"
        >
          <ChevronUp size={14} />
        </button>
      </div>

      <div
        className="flex-1 overflow-y-auto custom-scrollbar px-2 py-2"
        data-oid="toc-list"
      >
        {(!anchors || anchors.length === 0) ? (
          <p
            className="text-xs text-on-surface-variant px-2 py-4"
            data-oid="toc-empty"
          >
            {t("page:components.tocEmpty")}
          </p>
        ) : (
          <ul className="flex flex-col gap-0.5" data-oid="toc-items">
            {anchors.map((anchor) => (
              <li
                key={anchor.id}
                data-oid={`toc-item-${anchor.id}`}
              >
                <button
                  type="button"
                  onClick={() => handleJump(anchor.id)}
                  onMouseEnter={() => setHoveredId(anchor.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  className={`w-full text-left text-xs rounded px-2 py-1 transition-colors ${
                    anchor.isActive
                      ? "bg-primary-container/20 text-primary font-semibold"
                      : hoveredId === anchor.id
                        ? "bg-surface-container-high text-on-surface"
                        : "text-on-surface-variant hover:bg-surface-container-high"
                  }`}
                  style={{
                    paddingLeft: `${0.5 + (anchor.depth - 1) * 0.75}rem`,
                  }}
                  data-oid={`toc-link-${anchor.id}`}
                >
                  {anchor.content || `H${anchor.depth}`}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
