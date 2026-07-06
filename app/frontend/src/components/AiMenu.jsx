// [Flow: Step 1 (Tiptap 에디터와 선택 영역, 전체 마크다운 수신)
//       -> Step 2 (선택 영역을 마크다운으로 직렬화)
//       -> Step 3 (Agent API로 멀티스텝 AI 실행 시작)
//       -> Step 4 (폴링으로 상태 확인, interrupted면 승인 모달 표시)
//       -> Step 5 (done이면 edits/final_markdown을 에디터에 적용) -> Step 6 (자동 저장 onChange 트리거)]
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { DOMSerializer } from "@tiptap/pm/model";
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
import AgentApprovalModal from "./AgentApprovalModal.jsx";

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
  const serializer = DOMSerializer.fromSchema(editor.schema);
  const html = serializer.serializeFragment(slice.content, { document });
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

/**
 * [Flow: Step 1 (AgentRun의 edits/final_markdown 확인) -> Step 2 (replace/insert edits를 순서대로 적용)
 *       -> Step 3 (에디터에 포커스 반환)]
 * @param {import("@tiptap/core").Editor} editor
 * @param {object} result
 * @param {string} selectedMarkdown
 */
function applyAgentResult(editor, result, selectedMarkdown) {
  if (!editor || !result) return;
  const finalMarkdown = result?.final_markdown;
  const edits = result?.edits || [];
  if (finalMarkdown && !edits.length) {
    replaceSelectionWithMarkdown(editor, finalMarkdown);
    return;
  }
  for (const edit of edits) {
    if (edit.type === "replace") {
      replaceSelectionWithMarkdown(editor, edit.content);
    } else if (edit.type === "insert") {
      const html = marked.parse(edit.content || "");
      if (edit.position === "end") {
        editor.chain().focus().insertContentAt(editor.state.doc.content.size, html).run();
      } else if (edit.position === "beginning") {
        editor.chain().focus().insertContentAt(0, html).run();
      } else {
        // cursor 또는 기본 위치: 현재 선택 영역 끝
        const { to } = editor.state.selection;
        editor.chain().focus().insertContentAt(to, html).run();
      }
    }
  }
}

export default function AiMenu({ editor, editable = true, fullMarkdown = "" }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [customPrompt, setCustomPrompt] = useState("");
  const [showCustomInput, setShowCustomInput] = useState(false);
  const [run, setRun] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const menuRef = useRef(null);
  const pollTimerRef = useRef(null);

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

  // [Flow: Step 1 (run 상태가 running/processing/interrupted면 2초 폴링) -> Step 2 (done이면 결과 적용) -> Step 3 (error면 메시지 표시)]
  useEffect(() => {
    if (!run || !["running", "processing", "interrupted"].includes(run.status)) {
      clearTimeout(pollTimerRef.current);
      return;
    }
    const poll = async () => {
      try {
        const status = await api.getAgentStatus(run.run_id);
        setRun(status);
        if (status.status === "done") {
          setIsLoading(false);
          applyAgentResult(editor, status.result, getSelectedMarkdown(editor));
          setOpen(false);
          setShowCustomInput(false);
          setCustomPrompt("");
        } else if (status.status === "error") {
          setIsLoading(false);
          setError(status.error || "AI error");
        } else {
          pollTimerRef.current = setTimeout(poll, 2000);
        }
      } catch (err) {
        console.error("[AI] poll error:", err);
        setIsLoading(false);
        setError(err.message);
      }
    };
    pollTimerRef.current = setTimeout(poll, 2000);
    return () => clearTimeout(pollTimerRef.current);
  }, [run, editor]);

  /**
   * [Flow: Step 1 (선택 마크다운 + option/command 수집) -> Step 2 (AgentRun 생성 API 호출) -> Step 3 (run 상태 설정 및 폴링 시작)]
   * @param {string} option
   */
  const startAgent = async (option, command) => {
    if (!editor || isLoading) return;
    let selectedMarkdown = getSelectedMarkdown(editor);
    if (!selectedMarkdown && option !== "continue") return;

    if (option === "continue") {
      const { from } = editor.state.selection;
      selectedMarkdown = editor.state.doc.textBetween(0, from, "\n");
      if (!selectedMarkdown.trim()) return;
    }

    setIsLoading(true);
    setError("");
    setShowCustomInput(false);
    try {
      const res = await api.runAgent({
        graphName: "editor",
        payload: {
          instruction: selectedMarkdown,
          option,
          command,
          full_markdown: fullMarkdown,
          selected_markdown: selectedMarkdown,
        },
      });
      setRun(res);
      if (res.status === "done") {
        applyAgentResult(editor, res.result, selectedMarkdown);
        setIsLoading(false);
        setOpen(false);
        setCustomPrompt("");
      } else if (res.status === "error") {
        setError(res.error || "AI error");
        setIsLoading(false);
      }
    } catch (err) {
      console.error("[AI] startAgent error:", err);
      setError(err.message);
      setIsLoading(false);
    }
  };

  const handleCommand = (option) => startAgent(option, null);
  const handleCustom = () => {
    if (!customPrompt.trim()) return;
    startAgent("zap", customPrompt.trim());
  };

  const handleApprove = async (value) => {
    if (!run) return;
    const resumeValue = value !== undefined && value !== null ? value : { approved: true };
    try {
      setIsLoading(true);
      const res = await api.resumeAgent(run.run_id, { resumeValue });
      setRun(res);
      if (res.status === "done") {
        applyAgentResult(editor, res.result, getSelectedMarkdown(editor));
        setIsLoading(false);
        setOpen(false);
        setShowCustomInput(false);
        setCustomPrompt("");
      } else if (res.status === "error") {
        setError(res.error || "AI error");
        setIsLoading(false);
      }
    } catch (err) {
      console.error("[AI] resume error:", err);
      setError(err.message);
      setIsLoading(false);
    }
  };

  const handleReject = async (value) => {
    const resumeValue = value !== undefined && value !== null ? value : { approved: false };
    await handleApprove({ approved: false, value: resumeValue });
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
            <div className="flex items-center gap-2 px-3 py-2 text-sm text-on-surface">
              <Loader2 className="animate-spin" size={16} />
              {t("page:components.ai.thinking")}
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
                    value={customPrompt}
                    onChange={(e) => setCustomPrompt(e.target.value)}
                    placeholder={t("page:components.ai.customPlaceholder")}
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
          {error && (
            <div className="px-3 py-2 text-xs text-error" data-oid="ai-menu-error">
              {error}
            </div>
          )}
        </div>
      )}

      {run?.pending_interrupt && (
        <AgentApprovalModal
          interrupt={run.pending_interrupt}
          onApprove={handleApprove}
          onReject={handleReject}
          onClose={() => setRun(null)} />
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
      <span>{label}</span>
    </button>
  );
}
