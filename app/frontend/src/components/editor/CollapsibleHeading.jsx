// [Flow: Step 1 (Heading 확장 정의 — collapsed attribute 추가)
//       -> Step 2 (ReactNodeViewRenderer로 토글 버튼 + 본문 렌더링)
//       -> Step 3 (ProseMirror plugin으로 view.update 후 형제 노드 숨김 적용)
//       -> Step 4 (마크다운 라운드트립에는 collapsed 미저장 — view-only state)]
//
// 노션 스타일 "제목이 아래 본문을 토글" 기능을 제공하는 커스텀 Heading 확장.
// heading 노드에 collapsed boolean attribute를 추가하고, collapsed 시
// 같거나 상위 레벨의 다음 헤딩이 나올 때까지의 형제 블록 DOM을 숨긴다.
// doc 구조는 변경하지 않고 view 레이어에서만 숨김 처리하므로
// marked/turndown 마크다운 라운드트립에 영향을 주지 않는다.
import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer, NodeViewWrapper, NodeViewContent } from "@tiptap/react";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { ChevronRight } from "lucide-react";

const COLLAPSIBLE_HEADING_KEY = new PluginKey("collapsibleHeading");

/**
 * [Flow: DOM 요소의 태그명으로부터 헤딩 레벨 추출]
 *
 * @param {HTMLElement} el
 * @returns {number|null} 헤딩 레벨(1~6)이면 숫자, 아니면 null
 */
export function getHeadingLevel(el) {
  if (!el) return null;
  const tag = el.tagName.toLowerCase();
  const match = tag.match(/^h([1-6])$/);
  return match ? parseInt(match[1], 10) : null;
}

/**
 * [Flow: Step 1 (collapsed heading DOM 탐색) -> Step 2 (nextElementSibling 순회) -> Step 3 (같거나 상위 레벨 헤딩 전까지 display:none 적용)]
 *
 * collapsed 상태의 heading DOM 요소를 받아, 그 이후 형제 블록들을 숨긴다.
 * 같거나 상위 레벨(숫자가 같거나 작은) 헤딩이 나오면 숨김을 중단한다.
 *
 * @param {HTMLElement} headingEl - collapsed=true인 heading의 DOM 요소
 * @param {number} level - 해당 헤딩의 레벨 (1~6)
 */
export function hideFollowingSiblings(headingEl, level) {
  if (!headingEl) return;
  let sibling = headingEl.nextElementSibling;
  while (sibling) {
    const siblingLevel = getHeadingLevel(sibling);
    if (siblingLevel !== null && siblingLevel <= level) break;
    sibling.style.display = "none";
    sibling = sibling.nextElementSibling;
  }
}

/**
 * [Flow: Step 1 (collapsed heading DOM 탐색) -> Step 2 (nextElementSibling 순회) -> Step 3 (같거나 상위 레벨 헤딩 전까지 display 복원)]
 *
 * 펼쳐진 heading의 이후 형제 블록들을 다시 표시한다.
 *
 * @param {HTMLElement} headingEl - collapsed=false가 된 heading의 DOM 요소
 * @param {number} level - 해당 헤딩의 레벨 (1~6)
 */
export function showFollowingSiblings(headingEl, level) {
  if (!headingEl) return;
  let sibling = headingEl.nextElementSibling;
  while (sibling) {
    const siblingLevel = getHeadingLevel(sibling);
    if (siblingLevel !== null && siblingLevel <= level) break;
    sibling.style.display = "";
    sibling = sibling.nextElementSibling;
  }
}

/**
 * [Flow: Step 1 (editor.view.dom 내 모든 heading 요소 탐색) -> Step 2 (collapsed 상태에 따라 형제 숨김/표시 적용)]
 *
 * ProseMirror view가 업데이트된 직후 호출되어, 모든 collapsed heading의
 * 형제 노드 숨김 상태를 DOM에 재적용한다. re-render 시 DOM이 재구성되면
 * 숨김이 풀리는 것을 보정한다.
 *
 * @param {import('@tiptap/react').Editor} editor
 */
export function applyCollapseStateToDom(editor) {
  if (!editor || !editor.view) return;
  const root = editor.view.dom;
  // [Flow: 모든 헤딩 요소를 순회하며 collapsed attribute 확인]
  root.querySelectorAll("h1,h2,h3,h4,h5,h6").forEach((headingEl) => {
    const level = getHeadingLevel(headingEl);
    if (level === null) return;
    const collapsed = headingEl.getAttribute("data-collapsed") === "true";
    if (collapsed) {
      hideFollowingSiblings(headingEl, level);
    } else {
      showFollowingSiblings(headingEl, level);
    }
  });
}

/**
 * [Flow: Step 1 (Heading 확장 정의) -> Step 2 (collapsed attribute 추가) -> Step 3 (NodeView로 토글 버튼 렌더링) -> Step 4 (plugin으로 DOM 숨김 관리)]
 *
 * 노션 스타일 토글 헤딩 확장. StarterKit의 Heading을 대체한다.
 * StarterKit.configure({ heading: false }) 후 이 확장을 추가해야 한다.
 */
export const CollapsibleHeading = Node.create({
  name: "heading",

  addOptions() {
    return {
      levels: [1, 2, 3, 4, 5, 6],
      HTMLAttributes: {},
    };
  },

  content: "inline*",

  group: "block",

  defining: true,

  addAttributes() {
    return {
      level: {
        default: 1,
        rendered: false,
      },
      // [Flow: collapsed는 view-only state — data-collapsed 속성으로 HTML에 노출,
      //       turndown은 heading 태그의 텍스트만 변환하므로 마크다운에 미저장]
      collapsed: {
        default: false,
        parseHTML: (el) => el.getAttribute("data-collapsed") === "true",
        renderHTML: (attrs) =>
          attrs.collapsed ? { "data-collapsed": "true" } : {},
      },
    };
  },

  parseHTML() {
    return this.options.levels.map((level) => ({
      tag: `h${level}`,
      attrs: { level },
    }));
  },

  renderHTML({ node, HTMLAttributes }) {
    const hasLevel = this.options.levels.includes(node.attrs.level);
    const level = hasLevel ? node.attrs.level : this.options.levels[0];
    return [
      `h${level}`,
      mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, {
        "data-collapsed": node.attrs.collapsed ? "true" : undefined,
      }),
      0,
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(({ node, updateAttributes }) => {
      const level = node.attrs.level;
      const collapsed = node.attrs.collapsed;

      /**
       * [Flow: Step 1 (토글 버튼 클릭) -> Step 2 (collapsed attribute 반전 트랜잭션) -> Step 3 (plugin이 DOM 숨김 적용)]
       */
      const handleToggle = (e) => {
        e.preventDefault();
        e.stopPropagation();
        updateAttributes({ collapsed: !collapsed });
      };

      return (
        <NodeViewWrapper
          as={`h${level}`}
          className="collapsible-heading-wrapper"
          data-collapsed={collapsed ? "true" : "false"}
          style={{ position: "relative", paddingLeft: "1.5rem" }}
        >
          <button
            type="button"
            contentEditable={false}
            onClick={handleToggle}
            className="collapsible-heading-toggle"
            aria-label={collapsed ? "펼치기" : "접기"}
            style={{
              position: "absolute",
              left: 0,
              top: "0.1rem",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: "1.25rem",
              height: "1.25rem",
              padding: 0,
              border: "none",
              background: "transparent",
              cursor: "pointer",
              transition: "transform 0.15s ease",
              transform: collapsed ? "rotate(0deg)" : "rotate(90deg)",
            }}
          >
            <ChevronRight size={16} />
          </button>
          <NodeViewContent as={`h${level}`} className="collapsible-heading-content" />
        </NodeViewWrapper>
      );
    });
  },

  addCommands() {
    return {
      setHeading:
        (attributes) =>
        ({ commands }) => {
          if (!this.options.levels.includes(attributes.level)) return false;
          return commands.setNode(this.name, attributes);
        },
      toggleHeading:
        (attributes) =>
        ({ commands }) => {
          if (!this.options.levels.includes(attributes.level)) return false;
          return commands.toggleNode(this.name, "paragraph", attributes);
        },
    };
  },

  addKeyboardShortcuts() {
    return this.options.levels.reduce(
      (acc, level) => ({
        ...acc,
        [`Mod-Alt-${level}`]: () => this.editor.commands.toggleHeading({ level }),
      }),
      {}
    );
  },

  addInputRules() {
    return this.options.levels.map((level) => {
      return {
        find: new RegExp(`^(#{${level}})\\s$`),
        type: this.name,
        getAttributes: { level },
      };
    });
  },

  addProseMirrorPlugins() {
    const editor = this.editor;
    return [
      new Plugin({
        key: COLLAPSIBLE_HEADING_KEY,
        view() {
          return {
            update: () => {
              // [Flow: ProseMirror view 업데이트 후 DOM 숨김 상태 재적용]
              requestAnimationFrame(() => applyCollapseStateToDom(editor));
            },
          };
        },
      }),
    ];
  },
});

export default CollapsibleHeading;
