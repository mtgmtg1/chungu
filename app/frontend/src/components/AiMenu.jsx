// [Flow: Step 1 (Tiptap 에디터와 선택 영역 수신) -> Step 2 (선택 영역을 마크다운으로 직렬화) -> Step 3 (useCompletion으로 스트리밍 AI 요청) -> Step 4 (완료 시 마크다운 응답을 HTML로 변환해 선택 영역 대체) -> Step 5 (자동 저장 onChange 트리거)]
import { useEffect, useRef, useState } from "react";
import { useCompletion } from "ai/react";
import { useTranslation } from "react-i18next";
import { marked } from "marked";
import TurndownService from "turndown";
import {
  ArrowDownWideNarrow,
  CheckCheck,
  Loader2,
  Sparkles,
  StepForward,
  Wand2,
  WrapText } from
"lucide-react";
import { api } from "../api.js";

const turndown = new TurndownService({
  headingStyle: "atx",
  codeBlockStyle: "fenced",
  emDelimiter: "_",
  strongDelimiter: "**"
});

/**
 * [Flow: Step 1 (Tiptap selection에서 content slice 추출) -> Step 2 (ProseMirror DOM serializer로 HTML 변환) -> Step 3 (turndown으로 마크다운 반환)]
 * @param {import("@tiptap/core").Editor} editor
 * @returns {string}
 */
function getSelectedMarkdown(editor) {
  if (!editor) return "";
  const { selection } = editor.state;
  if (selection.empty) return "";
  const slice = selection.content();
  const html = editor.view.domSerializer.serializeFragment(slice.content, { document });
  return turndown.turndown(html);
}

/**
 * [Flow: Step 1 (마크다운 응답을 HTML로 변환) -> Step 2 (현재 선택 영역을 HTML로 대체) -> Step 3 (에디터에 포커스 반환)]
 * @param {import("@tiptap/core").Editor} editor
 * @param {string} markdown
 */
function replaceSelectionWithMarkdown(editor, markdown) {
  if (!editor || !markdown) return;
  const html = marked.parse(markdown || "");
  const { from, to } = editor.state.selection;
  editor.chain().focus().insertContentAt({ from, to }, html).run();
}

export default function AiMenu({ editor }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [customPrompt, setCustomPrompt] = useState("");
  const [showCustomInput, setShowCustomInput] = useState(false);
  const menuRef = useRef(null);

  const { completion, complete, isLoading, error } = useCompletion({
    api: "/api/v1/ai/generate",
    fetch: api.aiGenerateStream,
    onFinish: (_prompt, completionText) => {
      replaceSelectionWithMarkdown(editor, completionText);
      setOpen(false);
      setShowCustomInput(false);
      setCustomPrompt("");
    },
    onError: (err) => {
      console.error("[AI] error:", err);
    }
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

  const hasSelection = editor && !editor.state.selection.empty;

  /**
   * [Flow: Step 1 (선택 마크다운 추출) -> Step 2 (continue는 커서 이전 텍스트 사용) -> Step 3 (useCompletion complete 호출)]
   * @param {string} option
   */
  const handleCommand = async (option) => {
    if (!editor || isLoading) return;
    let prompt = getSelectedMarkdown(editor);
    if (!prompt && option !== "continue") return;

    setShowCustomInput(false);

    if (option === "continue") {
      const { from } = editor.state.selection;
      prompt = editor.state.doc.textBetween(0, from, "\n");
      if (!prompt.trim()) return;
    }

    await complete(prompt, { body: { option } });
  };

  /**
   * [Flow: Step 1 (선택 마크다운 + 사용자 커스텀 명령 수집) -> Step 2 (useCompletion complete 호출)]
   */
  const handleCustom = async () => {
    if (!editor || isLoading || !customPrompt.trim()) return;
    const prompt = getSelectedMarkdown(editor);
    if (!prompt) return;
    await complete(prompt, { body: { option: "zap", command: customPrompt.trim() } });
  };

  if (!editor) return null;

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={!hasSelection || isLoading}
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
            <div className="flex items-center gap-2 px-3 py-2 text-sm text-on-surface">
              <Loader2 className="animate-spin" size={16} />
              {t("page:editor.ai.thinking")}
            </div>
          ) : (
            <>
              <AiItem icon={Wand2} label={t("page:editor.ai.improve")} onClick={() => handleCommand("improve")} />
              <AiItem icon={CheckCheck} label={t("page:editor.ai.fix")} onClick={() => handleCommand("fix")} />
              <AiItem icon={ArrowDownWideNarrow} label={t("page:editor.ai.shorter")} onClick={() => handleCommand("shorter")} />
              <AiItem icon={WrapText} label={t("page:editor.ai.longer")} onClick={() => handleCommand("longer")} />
              <AiItem icon={StepForward} label={t("page:editor.ai.continue")} onClick={() => handleCommand("continue")} />
              <div className="h-px bg-outline-variant my-1" />
              <AiItem
                icon={Sparkles}
                label={t("page:editor.ai.custom")}
                onClick={() => setShowCustomInput((v) => !v)} />

              {showCustomInput && (
                <div className="flex items-center gap-1 px-2">
                  <input
                    type="text"
                    value={customPrompt}
                    onChange={(e) => setCustomPrompt(e.target.value)}
                    placeholder={t("page:editor.ai.customPlaceholder")}
                    className="flex-1 px-2 py-1 text-sm border border-outline-variant rounded focus:outline-none focus:border-primary bg-white"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleCustom();
                    }}
                    data-oid="ai-custom-input" />

                  <button
                    type="button"
                    onClick={handleCustom}
                    disabled={!customPrompt.trim()}
                    className="p-1 text-primary disabled:opacity-40"
                    data-oid="ai-custom-submit">

                    <Sparkles size={16} />
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>);

}

function AiItem({ icon: Icon, label, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-2 w-full px-3 py-2 text-sm text-left hover:bg-surface-container-high rounded text-on-surface"
      data-oid="ai-menu-item">

      <Icon size={16} className="text-primary" />
      {label}
    </button>);

}
