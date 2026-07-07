// [Flow: Step 1 (Tiptap 에디터와 선택 영역, 전체 마크다운 수신)
//       -> Step 2 (선택 영역을 마크다운으로 직렬화)
//       -> Step 3 (useCompletion으로 /api/v1/ai/generate 스트리밍 호출)
//       -> Step 4 (완료 시 결과를 에디터에 적용) -> Step 5 (자동 저장 onChange 트리거)]
// 마크다운 에디터의 AI 텍스트 생성 메뉴. Vercel AI SDK의 useCompletion을 사용해
// FastAPI /api/v1/ai/generate 엔드포인트에서 스트리밍 토큰을 받아 에디터에 반영한다.
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { marked } from "marked";
import TurndownService from "turndown";
import { useCompletion } from "@ai-sdk/react";
import {
  ArrowDownWideNarrow,
  CheckCheck,
  Loader2,
  Sparkles,
  StepForward,
  Wand2,
  WrapText } from
"lucide-react";

const turndown = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
  emDelimiter: "_",
  strongDelimiter: "**"
});

/**
 * [Flow: Step 1 (에디터에서 선택 영역 추출) -> Step 2 (HTML → 마크다운 변환) -> Step 3 (반환)]
 */
function getSelectedMarkdown(editor) {
  if (!editor) return "";
  const { from, to } = editor.state.selection;
  if (from === to) return "";
  const slice = editor.state.doc.slice(from, to);
  const serializer = editor.view.domSerializer || editor.schema.serializer;
  const fragment = slice.content;
  const div = document.createElement("div");
  div.appendChild(serializer.serializeFragment(fragment));
  return turndown.turndown(div.innerHTML);
}

/**
 * [Flow: Step 1 (AI 결과 마크다운을 HTML로 변환) -> Step 2 (에디터 선택 영역 또는 커서 위치에 삽입)
 *       -> Step 3 (onChange 트리거로 자동 저장)]
 */
function applyResultToEditor(editor, markdown, option) {
  if (!editor || !markdown) return;
  const html = marked.parse(markdown || "");
  const { from, to } = editor.state.selection;
  if (option === "continue") {
    editor.chain().focus().insertContentAt(to, html).run();
  } else {
    editor.chain().focus().insertContentAt({ from, to }, html).run();
  }
}

export default function AiMenu({ editor, editable = true, fullMarkdown = "" }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [showCustomInput, setShowCustomInput] = useState(false);
  const [error, setError] = useState("");
  const menuRef = useRef(null);
  const customInputRef = useRef(null);
  const pendingOptionRef = useRef(null);

  const { completion, complete, isLoading, stop } = useCompletion({
    api: "/api/v1/ai/generate",
    onResponse: () => setError(""),
    onError: (err) => {
      setError(err.message || "AI error");
    },
    onFinish: (_prompt, completionText) => {
      // [Flow: Step 1 (스트리밍 완료) -> Step 2 (결과를 에디터에 적용) -> Step 3 (메뉴 닫기)]
      if (editor && completionText) {
        applyResultToEditor(editor, completionText, pendingOptionRef.current);
      }
      setOpen(false);
      setShowCustomInput(false);
      if (customInputRef.current) customInputRef.current.value = "";
    },
  });

  // [Flow: 메뉴 외부 클릭 시 드롭다운 닫기]
  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  // [Flow: Step 1 (선택 마크다운 + option/command 수집) -> Step 2 (useCompletion complete 호출)]
  const startCompletion = async (option, command) => {
    if (!editor || isLoading) return;
    let selectedMarkdown = getSelectedMarkdown(editor);
    if (!selectedMarkdown && option !== "continue") {
      selectedMarkdown = fullMarkdown;
    }
    if (!selectedMarkdown.trim() && option !== "continue") return;

    if (option === "continue") {
      const { from } = editor.state.selection;
      selectedMarkdown = editor.state.doc.textBetween(0, from, "\n");
      if (!selectedMarkdown.trim()) return;
    }

    pendingOptionRef.current = option;
    setError("");
    setShowCustomInput(false);
    try {
      await complete({ prompt: selectedMarkdown, option, command });
    } catch (err) {
      setError(err.message || "AI error");
    }
  };

  const handleCommand = (option) => startCompletion(option, null);
  const handleCustom = () => {
    const prompt = customInputRef.current?.value?.trim() || "";
    if (!prompt) return;
    startCompletion("zap", prompt);
  };

  if (!editor || !editable) return null;

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={isLoading}
        className={`p-1.5 rounded-md transition-colors flex items-center gap-1 ${
          open ? "bg-primary text-white" : "hover:bg-surface-container-high text-on-surface"
        } disabled:opacity-40`}
        data-oid="ai-menu-toggle">
        {isLoading ? <Loader2 size={18} className="animate-spin" /> : <Sparkles size={18} />}
        <span className="text-sm">AI</span>
      </button>

      {open && (
        <div
          className="absolute top-full left-0 mt-1 w-56 bg-white rounded-lg shadow-lg border border-outline-variant p-2 z-50 flex flex-col gap-1"
          data-oid="ai-menu-dropdown">
          {isLoading ? (
            <div className="flex flex-col gap-2 px-3 py-2 text-sm text-on-surface">
              <div className="flex items-center gap-2">
                <Loader2 className="animate-spin" size={16} />
                {t("page:components.ai.thinking")}
              </div>
              {completion && (
                <div className="text-xs text-on-surface-variant max-h-32 overflow-y-auto whitespace-pre-wrap">
                  {completion}
                </div>
              )}
              <button
                type="button"
                onClick={stop}
                className="text-xs text-error hover:underline">
                {t("common:actions.cancel")}
              </button>
            </div>
          ) : (
            <>
              <AiItem icon={Wand2} label={t("page:components.ai.improve")} onClick={() => handleCommand("improve")} />
              <AiItem icon={CheckCheck} label={t("page:components.ai.fix")} onClick={() => handleCommand("fix")} />
              <AiItem icon={ArrowDownWideNarrow} label={t("page:components.ai.shorter")} onClick={() => handleCommand("shorter")} />
              <AiItem icon={WrapText} label={t("page:components.ai.longer")} onClick={() => handleCommand("longer")} />
              <AiItem icon={StepForward} label={t("page:components.ai.continue")} onClick={() => handleCommand("continue")} />
              <div className="h-px bg-outline-variant my-1" />
              <AiItem
                icon={Sparkles}
                label={t("page:components.ai.custom")}
                onClick={() => setShowCustomInput((v) => !v)} />

              {showCustomInput && (
                <div className="flex items-center gap-1 px-2">
                  <input
                    type="text"
                    ref={customInputRef}
                    defaultValue=""
                    placeholder={t("page:components.ai.customPlaceholder")}
                    className="flex-1 px-2 py-1 text-sm border border-outline-variant rounded focus:outline-none focus:border-primary bg-white"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleCustom();
                    }}
                    data-oid="ai-custom-input" />

                  <button
                    type="button"
                    onClick={handleCustom}
                    className="p-1 text-primary disabled:opacity-40"
                    data-oid="ai-custom-submit">
                    <Sparkles size={16} />
                  </button>
                </div>
              )}
            </>
          )}
          {error && (
            <div className="px-3 py-2 text-xs text-error" data-oid="ai-menu-error">
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AiItem({ icon: Icon, label, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-2 px-3 py-2 text-sm text-on-surface hover:bg-surface-container-high rounded-md transition-colors"
      data-oid="ai-menu-item">
      <Icon size={16} />
      {label}
    </button>
  );
}
