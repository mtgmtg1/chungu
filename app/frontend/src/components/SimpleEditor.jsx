// [Flow: Step 1 (Tiptap 에디터 초기화) -> Step 2 (마크다운 prop을 HTML로 로드, 페이지 마커 추가) -> Step 3 (풍부한 툴바 렌더링) -> Step 4 (scrollToPage API 제공) -> Step 5 (사용자 편집 -> HTML -> 마크다운 반환)]
import { forwardRef, memo, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useEditor, EditorContent } from "@tiptap/react";
import { BubbleMenu } from "@tiptap/react/menus";
import { Node } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Table } from "@tiptap/extension-table";
import { TableRow } from "@tiptap/extension-table-row";
import { TableCell } from "@tiptap/extension-table-cell";
import { TableHeader } from "@tiptap/extension-table-header";
import Underline from "@tiptap/extension-underline";
import Highlight from "@tiptap/extension-highlight";
import TextAlign from "@tiptap/extension-text-align";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";
import Link from "@tiptap/extension-link";
import Image from "@tiptap/extension-image";
import Placeholder from "@tiptap/extension-placeholder";
import { TableOfContents } from "@tiptap/extension-table-of-contents";
import { marked } from "marked";
import TurndownService from "turndown";
import {
  Bold,
  Italic,
  Underline as UnderlineIcon,
  Strikethrough,
  Highlighter,
  AlignLeft,
  AlignCenter,
  AlignRight,
  AlignJustify,
  List,
  ListOrdered,
  ListTodo,
  Link as LinkIcon,
  Image as ImageIcon,
  Table as TableIcon,
  Undo,
  Redo,
  Heading1,
  Heading2,
  Heading3,
  Heading4 } from
"lucide-react";
import AiMenu from "./AiMenu.jsx";
import TocSidebar from "./editor/TocSidebar.jsx";


const turndown = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
  emDelimiter: "_",
  strongDelimiter: "**"
});

const PAGE_MARKER_RE = /<!--\s*페이지\s*(\d+)\s*-->/gi;

/**
 * [Flow: Step 1 (마크다운 HTML에서 페이지 주석 검색) -> Step 2 (각 주석을 data-page 속성을 가진 div로 교체) -> Step 3 (Tiptap이 스크롤 타겟으로 사용할 수 있는 HTML 반환)]
 * @param {string} markdownHtml
 * @returns {string}
 */
function injectPageMarkers(markdownHtml) {
  if (!markdownHtml) return markdownHtml;
  return markdownHtml.replace(
    PAGE_MARKER_RE,
    (_, pageNum) => `<div data-page-marker="${pageNum}" class="page-marker" style="height:1px;"></div>`
  );
}

/**
 * [Flow: Tiptap이 div[data-page-marker] 요소를 보존하도록 하는 커스텀 블록 노드]
 * ProseMirror 기본 스키마에 없는 div 요소가 setContent 시 제거되는 것을 방지.
 */
const PageMarkerNode = Node.create({
  name: "pageMarker",
  group: "block",
  atom: true,
  selectable: false,
  addAttributes() {
    return {
      pageNum: { default: null },
    };
  },
  parseHTML() {
    return [
      {
        tag: "div[data-page-marker]",
        getAttrs: (el) => ({ pageNum: el.getAttribute("data-page-marker") }),
      },
    ];
  },
  renderHTML({ node }) {
    return ["div", { "data-page-marker": node.attrs.pageNum, class: "page-marker", style: "height:1px;" }];
  },
});

turndown.addRule("pageMarker", {
  filter: (node) =>
    node.nodeName === "DIV" && node.getAttribute("data-page-marker"),
  replacement: (_content, node) =>
    `<!-- 페이지 ${node.getAttribute("data-page-marker")} -->`,
});

turndown.addRule("table", {
  filter: "table",
  replacement: function (content, node) {
    const rows = Array.from(node.querySelectorAll("tr"));
    if (!rows.length) return "";
    const lines = [];
    rows.forEach((row, idx) => {
      const cells = Array.from(row.querySelectorAll("th, td")).map((cell) =>
      cell.textContent.trim().replace(/\|/g, "\\|")
      );
      lines.push("| " + cells.join(" | ") + " |");
      if (idx === 0) {
        lines.push("| " + cells.map(() => "---").join(" | ") + " |");
      }
    });
    return "\n\n" + lines.join("\n") + "\n\n";
  }
});

function ToolbarButton({ onClick, active, disabled, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`p-1.5 rounded-md transition-colors ${
      active ?
      "bg-primary text-white" :
      "hover:bg-surface-container-high text-on-surface"} disabled:opacity-40`
      }
      data-oid="x3atm-5">

      {children}
    </button>);

}

function ToolbarDivider() {
  return (
    <div className="w-px h-5 bg-outline-variant mx-1" data-oid="lxjp-4z"></div>);

}

const SimpleEditor = memo(forwardRef(function SimpleEditor(
{ markdown, editable = true, onPageChange, onChange },
ref)
{
  const { t } = useTranslation();
  const [headingOpen, setHeadingOpen] = useState(false);
  const [tocOpen, setTocOpen] = useState(true);
  const [anchors, setAnchors] = useState([]);
  const containerRef = useRef(null);
  const observedPageRef = useRef(null);
  const onChangeRef = useRef(onChange);
  const onChangeTimerRef = useRef(null);
  const lastMarkdownRef = useRef(markdown);

  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  const editor = useEditor({
    extensions: [
    StarterKit,
    TableOfContents.configure({
      onUpdate: (content) => setAnchors(content),
    }),
    PageMarkerNode,
    Table.configure({ resizable: true }),
    TableRow,
    TableHeader,
    TableCell,
    Underline,
    Highlight,
    TextAlign.configure({ types: ["heading", "paragraph"] }),
    TaskList,
    TaskItem.configure({ nested: true }),
    Link.configure({ openOnClick: false, autolink: true }),
    Image.configure({ inline: true, allowBase64: true }),
    Placeholder.configure({
      placeholder: t("page:components.editorPlaceholder")
    })],


    content: injectPageMarkers(marked.parse(markdown || "")),
    editable
  });

  // [Flow: Step 1 (markdown prop 변경 감지) -> Step 2 (lastMarkdownRef와 비교하여 실제 변경인지 판별)
  //       -> Step 3 (진행 중 debounce 타이머 취소로 에이전트 변경사항 덮어쓰기 방지)
  //       -> Step 4 (Tiptap setContent로 에디터 내용 동기화, emitUpdate:false로 update 이벤트 억제)]
  // 에이전트 도구(apply_edits)가 백엔드에 저장 후 부모가 markdown prop을 갱신해도
  // Tiptap 내용을 동기화하지 않으면 화면에 반영되지 않는 문제를 해결한다.
  useEffect(() => {
    if (!editor) return;
    if (lastMarkdownRef.current === markdown) return;
    // 진행 중인 사용자 편집 debounce 타이머 취소 — 로컬 편집이 에이전트 변경사항을 덮어쓰는 것을 방지
    clearTimeout(onChangeTimerRef.current);
    lastMarkdownRef.current = markdown;
    // emitUpdate: false — setContent가 update 이벤트를 발생시키지 않아 debounce 재발생 차단
    editor.commands.setContent(injectPageMarkers(marked.parse(markdown || "")), { emitUpdate: false });
  }, [editor, markdown]);

  // [Flow: Step 1 (사용자 입력으로 Tiptap 업데이트 이벤트 발생) -> Step 2 (1초 debounce 타이머 설정) -> Step 3 (타이머 완료 시 getMarkdown으로 변환) -> Step 4 (prop 마크다운과 다를 때만 onChange 콜백 호출)]
  useEffect(() => {
    if (!editor) return;
    const handleUpdate = () => {
      if (typeof onChangeRef.current !== "function") return;
      clearTimeout(onChangeTimerRef.current);
      onChangeTimerRef.current = setTimeout(() => {
        const updated = turndown.turndown(editor.getHTML());
        if (updated === lastMarkdownRef.current) return;
        lastMarkdownRef.current = updated;
        onChangeRef.current(updated);
      }, 1000);
    };
    editor.on("update", handleUpdate);
    return () => {
      editor.off("update", handleUpdate);
      clearTimeout(onChangeTimerRef.current);
    };
  }, [editor]);

  // [Flow: Step 1 (에디터 마운트 시 페이지 마커 탐색) -> Step 2 (IntersectionObserver로 뷰포트 진입 마커 감시) -> Step 3 (가장 위쪽 마커 페이지를 onPageChange 콜백에 전달)]
  useEffect(() => {
    observedPageRef.current = null;
    if (!editor || !onPageChange) return;

    const onPageChangeRef = { current: onPageChange };
    onPageChangeRef.current = onPageChange;

    let rafId;
    let observer = null;

    const setupObserver = () => {
      const container = containerRef.current?.querySelector(".overflow-y-auto");
      if (!container) return;

      const markers = container.querySelectorAll("[data-page-marker]");
      if (markers.length === 0) return;

      observer = new IntersectionObserver(
        (entries) => {
          const visible = entries
            .filter((entry) => entry.isIntersecting)
            .map((entry) => ({
              pageNum: Number(entry.target.getAttribute("data-page-marker")),
              top: entry.boundingClientRect.top
            }))
            .sort((a, b) => a.top - b.top);

          if (visible.length === 0) return;

          const topPage = visible[0].pageNum;
          if (topPage !== observedPageRef.current) {
            observedPageRef.current = topPage;
            onPageChangeRef.current(topPage);
          }
        },
        { root: container, threshold: 0, rootMargin: "0px" }
      );

      markers.forEach((marker) => observer.observe(marker));
    };

    // DOM이 반영된 다음 paint에서 observer를 설정한다.
    rafId = requestAnimationFrame(() => {
      rafId = requestAnimationFrame(setupObserver);
    });

    return () => {
      cancelAnimationFrame(rafId);
      if (observer) observer.disconnect();
    };
  }, [editor, onPageChange]);

  useImperativeHandle(
    ref,
    () => ({
      getMarkdown: () => editor ? turndown.turndown(editor.getHTML()) : "",
      /**
       * [Flow: Step 1 (페이지 번호로 data-page-marker 요소 탐색) -> Step 2 (에디터 스크롤 컨테이너 찾기) -> Step 3 (해당 위치로 스무스 스크롤)]
       * @param {number} pageNum
       */
      scrollToPage: (pageNum) => {
        if (!containerRef.current) return;
        const marker = containerRef.current.querySelector(`[data-page-marker="${pageNum}"]`);
        if (!marker) return;
        const scrollContainer = containerRef.current.querySelector(".overflow-y-auto") || containerRef.current;
        const top = marker.offsetTop - scrollContainer.offsetTop;
        scrollContainer.scrollTo({ top, behavior: "smooth" });
      }
    }),
    [editor]
  );

  if (!editor) return null;

  const toggleLink = () => {
    if (editor.isActive("link")) {
      editor.chain().focus().unsetLink().run();
      return;
    }
    const url = window.prompt(t("page:components.linkUrl"), "https://");
    if (url) editor.chain().focus().setLink({ href: url }).run();
  };

  const addImage = () => {
    const url = window.prompt(t("page:components.imageUrl"), "https://");
    if (url) editor.chain().focus().setImage({ src: url }).run();
  };

  const addTable = () => {
    editor.
    chain().
    focus().
    insertTable({ rows: 3, cols: 3, withHeaderRow: true }).
    run();
  };

  const headingIcon = editor.isActive("heading", { level: 1 }) ?
  Heading1 :
  editor.isActive("heading", { level: 2 }) ?
  Heading2 :
  editor.isActive("heading", { level: 3 }) ?
  Heading3 :
  Heading4;

  const HeadingIcon = headingIcon;

  return (
    <div ref={containerRef} className="flex flex-col h-full bg-white" data-oid="i28xau9">
      <div
        className="flex items-center gap-1 px-3 py-2 border-b border-outline-variant bg-surface flex-wrap"
        data-oid="44c5xqu">

        <ToolbarButton
          onClick={() => editor.chain().focus().undo().run()}
          disabled={!editor.can().undo()}
          data-oid="3cjvnmo">
          <Undo size={18} data-oid="x2kv.xh" />
        </ToolbarButton>
        <ToolbarButton
          onClick={() => editor.chain().focus().redo().run()}
          disabled={!editor.can().redo()}
          data-oid=":h.0vku">
          <Redo size={18} data-oid=".7dxqt_" />
        </ToolbarButton>
        <ToolbarDivider data-oid="hw-mdtw" />

        <div className="relative" data-oid="0wpl:-9">
          <ToolbarButton
            onClick={() => setHeadingOpen((v) => !v)}
            active={editor.isActive("heading")}
            data-oid="7d992de">
            <HeadingIcon size={18} data-oid="xuvv95x" />
          </ToolbarButton>
          {headingOpen &&
          <div
            className="absolute top-full left-0 mt-1 bg-white rounded-lg shadow-lg border border-outline-variant p-1 z-50 flex flex-col gap-0.5"
            data-oid="mylyfxl">

              {[1, 2, 3, 4].map((level) =>
            <button
              key={level}
              type="button"
              onClick={() => {
                editor.chain().focus().toggleHeading({ level }).run();
                setHeadingOpen(false);
              }}
              className={`px-3 py-1.5 rounded text-sm text-left hover:bg-surface-container-high ${
              editor.isActive("heading", { level }) ?
              "bg-primary-container/10 text-primary font-bold" :
              "text-on-surface"}`
              }
              data-oid="d-3z5sx">

                  {t("page:components.headingN", { level })}
                </button>
            )}
              <button
              type="button"
              onClick={() => {
                editor.chain().focus().setParagraph().run();
                setHeadingOpen(false);
              }}
              className="px-3 py-1.5 rounded text-sm text-left hover:bg-surface-container-high text-on-surface"
              data-oid="aw5:3ha">

                {t("page:components.paragraph")}
              </button>
            </div>
          }
        </div>
        <ToolbarDivider data-oid="pwj6-sh" />

        <ToolbarButton
          onClick={() => editor.chain().focus().toggleBold().run()}
          active={editor.isActive("bold")}
          data-oid=":a6xd9h">
          <Bold size={18} data-oid="wvk9x-o" />
        </ToolbarButton>
        <ToolbarButton
          onClick={() => editor.chain().focus().toggleItalic().run()}
          active={editor.isActive("italic")}
          data-oid="s2zecw5">
          <Italic size={18} data-oid="5rt7qq:" />
        </ToolbarButton>
        <ToolbarButton
          onClick={() => editor.chain().focus().toggleUnderline().run()}
          active={editor.isActive("underline")}
          data-oid="td5et.g">
          <UnderlineIcon size={18} data-oid="li:m9iu" />
        </ToolbarButton>
        <ToolbarButton
          onClick={() => editor.chain().focus().toggleStrike().run()}
          active={editor.isActive("strike")}
          data-oid="zml36x:">
          <Strikethrough size={18} data-oid="m:wguu2" />
        </ToolbarButton>
        <ToolbarButton
          onClick={() => editor.chain().focus().toggleHighlight().run()}
          active={editor.isActive("highlight")}
          data-oid="jeojw-m">
          <Highlighter size={18} data-oid="4up0fme" />
        </ToolbarButton>
        <ToolbarDivider data-oid="dk-tgwp" />

        <ToolbarButton
          onClick={() => editor.chain().focus().setTextAlign("left").run()}
          active={editor.isActive({ textAlign: "left" })}
          data-oid="toi.nlh">
          <AlignLeft size={18} data-oid="a57ewqz" />
        </ToolbarButton>
        <ToolbarButton
          onClick={() => editor.chain().focus().setTextAlign("center").run()}
          active={editor.isActive({ textAlign: "center" })}
          data-oid="u3:3bw3">
          <AlignCenter size={18} data-oid="4oqegh5" />
        </ToolbarButton>
        <ToolbarButton
          onClick={() => editor.chain().focus().setTextAlign("right").run()}
          active={editor.isActive({ textAlign: "right" })}
          data-oid="toiant1">
          <AlignRight size={18} data-oid="b13nn9a" />
        </ToolbarButton>
        <ToolbarButton
          onClick={() => editor.chain().focus().setTextAlign("justify").run()}
          active={editor.isActive({ textAlign: "justify" })}
          data-oid="xzayz42">
          <AlignJustify size={18} data-oid="k-6k0sh" />
        </ToolbarButton>
        <ToolbarDivider data-oid="0g.d7w_" />

        <ToolbarButton
          onClick={() => editor.chain().focus().toggleBulletList().run()}
          active={editor.isActive("bulletList")}
          data-oid="v0d3mu8">
          <List size={18} data-oid="6xwxur4" />
        </ToolbarButton>
        <ToolbarButton
          onClick={() => editor.chain().focus().toggleOrderedList().run()}
          active={editor.isActive("orderedList")}
          data-oid="h76nzt:">
          <ListOrdered size={18} data-oid="y0pjv15" />
        </ToolbarButton>
        <ToolbarButton
          onClick={() => editor.chain().focus().toggleTaskList().run()}
          active={editor.isActive("taskList")}
          data-oid="_dh0ip4">
          <ListTodo size={18} data-oid="ut6hju7" />
        </ToolbarButton>
        <ToolbarDivider data-oid="k3gd.63" />

        <AiMenu editor={editor} editable={editable} fullMarkdown={markdown} data-oid="ai-menu" />
        <ToolbarDivider data-oid="ai-divider" />

        <ToolbarButton
          onClick={toggleLink}
          active={editor.isActive("link")}
          data-oid="ls_yew0">
          <LinkIcon size={18} data-oid="3oixvfi" />
        </ToolbarButton>
        <ToolbarButton
          onClick={addImage}
          data-oid="8z-1uw0">
          <ImageIcon size={18} data-oid="dgmdr-8" />
        </ToolbarButton>
        <ToolbarButton
          onClick={addTable}
          active={editor.isActive("table")}
          data-oid="5ow0_b6">
          <TableIcon size={18} data-oid="k-unaiu" />
        </ToolbarButton>
      </div>
      <div className="flex-1 flex overflow-hidden" data-oid="editor-toc-layout">
        <div
          className="flex-1 overflow-y-auto p-6 custom-scrollbar"
          data-oid="qjrci2n">

          <EditorContent
            editor={editor}
            className="prose max-w-none focus:outline-none"
            data-oid="adafms.">

            {editor && (
              <BubbleMenu
                editor={editor}
                tippyOptions={{ duration: 100, placement: "top-start" }}
                className="flex items-center gap-1 px-2 py-1.5 bg-white rounded-lg shadow-lg border border-outline-variant z-50">

                <AiMenu editor={editor} editable={editable} fullMarkdown={markdown} />
              </BubbleMenu>
            )}
          </EditorContent>

        </div>
        <TocSidebar
          anchors={anchors}
          editor={editor}
          open={tocOpen}
          onToggle={() => setTocOpen((v) => !v)}
          data-oid="toc-sidebar-comp" />
      </div>
    </div>);

}));

export default SimpleEditor;