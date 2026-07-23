// [Flow: Step 1 (dev bypass 자동 로그인) -> Step 2 (job 선택/로드) -> Step 3 (마크다운 에디터 + 에이전트 채팅)
//       -> Step 4 (각 단계별 상세 로그 캡처: API 호출/응답, Tiptap 내용, 상태 변화)
//       -> Step 5 (에이전트 도구로 마크다운 수정 후 반영 여부 진단)]
// 에이전트 도구로 마크다운 에디터 수정이 반영되지 않는 문제를 end-to-end로 재현하고
// 각 단계의 로그를 화면에 출력하여 원인을 진단하는 디버깅 전용 페이지.
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api.js";
import SimpleEditor from "../components/SimpleEditor.jsx";
import AgentChatModal from "../components/AgentChatModal.jsx";

// [Flow: 로그 엔트리 — 타임스탬프, 레벨, 카테고리, 메시지, 상세 데이터]
function makeLog(level, category, message, data) {
  return {
    time: new Date().toLocaleTimeString("ko-KR", { hour12: false }) + "." + String(Date.now() % 1000).padStart(3, "0"),
    level,
    category,
    message,
    data: data !== undefined ? data : null,
  };
}

// [Flow: Step 1 (dev/login 호출로 bypass 토큰 획득) -> Step 2 (localStorage 저장) -> Step 3 (성공/실패 로그)]
async function ensureDevLogin(addLog) {
  addLog("info", "auth", "dev bypass 로그인 시도");
  try {
    const resp = await fetch(`${window.location.origin}/api/dev/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!resp.ok) {
      const text = await resp.text();
      addLog("error", "auth", `dev login 실패: ${resp.status}`, text);
      return false;
    }
    const data = await resp.json();
    localStorage.setItem("dev_access_token", data.access_token);
    localStorage.setItem("dev_refresh_token", data.refresh_token);
    localStorage.setItem("dev_user", JSON.stringify(data.user));
    localStorage.setItem("dev_bypass_mode", "apikey");
    addLog("info", "auth", `dev login 성공: ${data.user?.email}`, { userId: data.user?.id });
    return true;
  } catch (e) {
    addLog("error", "auth", `dev login 예외: ${e.message}`);
    return false;
  }
}

export default function DebugMarkdownAgentPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [logs, setLogs] = useState([]);
  const [jobId, setJobId] = useState(searchParams.get("jobId") || "");
  const [job, setJob] = useState(null);
  const [markdown, setMarkdown] = useState("");
  const [fileMarkdowns, setFileMarkdowns] = useState([]);
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);
  const [sourceFiles, setSourceFiles] = useState([]);
  const [chatOpen, setChatOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [editorContent, setEditorContent] = useState("");
  const [tiptapContent, setTiptapContent] = useState("");
  const editorRef = useRef(null);
  const logEndRef = useRef(null);

  // [Flow: 로그 추가 함수 — 새 로그 엔트리를 상태에 추가]
  const addLog = useCallback((level, category, message, data) => {
    setLogs((prev) => [...prev, makeLog(level, category, message, data)]);
  }, []);

  // [Flow: 로그 패널 자동 스크롤]
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  // [Flow: Step 1 (페이지 마운트 시 dev bypass 로그인) -> Step 2 (URL에 jobId가 있으면 자동 로드)]
  useEffect(() => {
    (async () => {
      const ok = await ensureDevLogin(addLog);
      if (ok && searchParams.get("jobId")) {
        await loadJobData(searchParams.get("jobId"));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // [Flow: Step 1 (job 상태 조회) -> Step 2 (preview API로 마크다운 로드) -> Step 3 (fileMarkdowns/displayMarkdown 설정)
  //       -> Step 4 (Tiptap 내용 스냅샷 캡처)]
  async function loadJobData(id) {
    if (!id) return;
    setLoading(true);
    addLog("info", "load", `loadJobData 시작: ${id}`);
    try {
      addLog("info", "api", `GET /api/jobs/${id}`);
      const jobData = await api.getJob(id);
      setJob(jobData);
      addLog("info", "api", `GET /api/jobs/${id} 응답`, {
        status: jobData?.status,
        total_files: jobData?.total_files,
        result_edited_md_storage_path: jobData?.result_edited_md_storage_path ? "(있음)" : "(없음)",
        result_md_storage_path: jobData?.result_md_storage_path ? "(있음)" : "(없음)",
      });

      if (jobData?.status !== "done") {
        addLog("warn", "load", `job 상태가 done이 아님: ${jobData?.status}`);
        setLoading(false);
        return;
      }

      addLog("info", "api", `GET /api/jobs/${id}/preview?start_page=1&end_page=1`);
      const preview = await api.previewJob(id, 1, 1);
      addLog("info", "api", `preview 응답`, {
        markdown_length: preview.markdown?.length || 0,
        source_files_count: preview.source_files?.length || 0,
        markdown_preview: (preview.markdown || "").substring(0, 200),
      });

      setSourceFiles(preview.source_files || []);
      // [Flow: preview.markdown(=edited_md 포함)을 파일 마커로 분할하여 fileMarkdowns로 사용]
      // 이전에는 source_files[].result_markdown(원본)을 사용했으나, 에이전트 편집 내용이
      // 반영되지 않는 버그의 원인이 되었음. preview.markdown은 _get_markdown_content에서
      // edited_md를 우선 선택하므로 에이전트 편집 내용이 포함됨.
      const previewMd = preview.markdown || "";
      const fileParts = previewMd.split(/\n*<!-- Page \d+ -->\n*/).filter((s) => s.trim());
      const sourceCount = (preview.source_files || []).length;
      const fms = sourceCount > 1 && fileParts.length > 1
        ? fileParts
        : (preview.source_files || []).map((f) => f.result_markdown || "");
      setFileMarkdowns(fms);
      setSelectedFileIndex(0);

      const hasFileMarkdowns = fms.length > 1 && fms.some(Boolean);
      const selectedFileMarkdown = fms[0] || "";
      const displayMarkdown = hasFileMarkdowns && selectedFileMarkdown.trim()
        ? selectedFileMarkdown
        : previewMd;
      setMarkdown(displayMarkdown);
      addLog("info", "state", `displayMarkdown 설정`, {
        length: displayMarkdown.length,
        hasFileMarkdowns,
        fms_count: fms.length,
        preview: displayMarkdown.substring(0, 200),
      });
    } catch (e) {
      addLog("error", "load", `loadJobData 예외: ${e.message}`, e.stack);
    } finally {
      setLoading(false);
    }
  }

  // [Flow: Tiptap 내용 주기적 스냅샷 — 에디터 DOM과 getMarkdown() 비교]
  useEffect(() => {
    const interval = setInterval(() => {
      if (!editorRef.current) return;
      const md = editorRef.current.getMarkdown();
      setTiptapContent(md);
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  // [Flow: 마크다운 prop 변경 시 로그 — SimpleEditor에 전달되는 값 추적]
  const prevMarkdownRef = useRef(markdown);
  useEffect(() => {
    if (prevMarkdownRef.current !== markdown) {
      addLog("info", "prop", `markdown prop 변경 감지`, {
        prev_length: prevMarkdownRef.current.length,
        new_length: markdown.length,
        prev_preview: prevMarkdownRef.current.substring(0, 100),
        new_preview: markdown.substring(0, 100),
        changed: prevMarkdownRef.current !== markdown,
      });
      prevMarkdownRef.current = markdown;
    }
  }, [markdown, addLog]);

  const hasFileMarkdowns = fileMarkdowns.length > 1 && fileMarkdowns.some(Boolean);
  const selectedFileMarkdown = fileMarkdowns[selectedFileIndex] || "";
  const displayMarkdown = hasFileMarkdowns && selectedFileMarkdown.trim()
    ? selectedFileMarkdown
    : markdown;

  // [Flow: 에이전트 완료 콜백 — loadJobData 재호출로 preview 갱신 + Tiptap 내용 비교]
  const handleAgentComplete = useCallback(async () => {
    addLog("info", "agent", "onAgentComplete 호출됨 — loadJobData 재호출");
    await loadJobData(jobId);
    // [Flow: 1초 후 Tiptap 내용 스냅샷 — prop이 전달된 후 에디터에 반영되었는지 확인]
    setTimeout(() => {
      if (editorRef.current) {
        const md = editorRef.current.getMarkdown();
        addLog("info", "tiptap", `onAgentComplete 후 Tiptap getMarkdown()`, {
          length: md.length,
          preview: md.substring(0, 200),
          matches_displayMarkdown: md === displayMarkdown,
        });
      }
    }, 1000);
  }, [jobId, displayMarkdown, addLog]);

  // [Flow: 수동 Tiptap 내용 확인 버튼]
  const checkTiptapContent = useCallback(() => {
    if (!editorRef.current) {
      addLog("warn", "tiptap", "editorRef 없음");
      return;
    }
    const md = editorRef.current.getMarkdown();
    addLog("info", "tiptap", `수동 Tiptap getMarkdown()`, {
      length: md.length,
      preview: md.substring(0, 300),
      matches_displayMarkdown: md === displayMarkdown,
      displayMarkdown_preview: displayMarkdown.substring(0, 300),
    });
  }, [displayMarkdown, addLog]);

  // [Flow: 수동 preview 재로드 버튼]
  const reloadPreview = useCallback(async () => {
    addLog("info", "manual", "수동 preview 재로드");
    await loadJobData(jobId);
  }, [jobId, addLog]);

  // [Flow: 백엔드 저장 내용 직접 확인 — /api/jobs/{id}/preview 호출 후 마크다운 비교]
  const checkBackendMarkdown = useCallback(async () => {
    if (!jobId) return;
    addLog("info", "backend", `백엔드 마크다운 직접 확인: GET /api/jobs/${jobId}/preview`);
    try {
      const preview = await api.previewJob(jobId, 1, 1);
      const backendMd = preview.markdown || "";
      addLog("info", "backend", `백엔드 preview 마크다운`, {
        length: backendMd.length,
        preview: backendMd.substring(0, 300),
        matches_displayMarkdown: backendMd === displayMarkdown,
        matches_tiptap: editorRef.current ? backendMd === editorRef.current.getMarkdown() : "N/A",
      });
    } catch (e) {
      addLog("error", "backend", `백엔드 확인 예외: ${e.message}`);
    }
  }, [jobId, displayMarkdown, addLog]);

  // [Flow: 로그 초기화]
  const clearLogs = useCallback(() => setLogs([]), []);

  // [Flow: job 로드 버튼]
  const handleLoadJob = useCallback(async () => {
    if (jobId) {
      setSearchParams({ jobId });
      await loadJobData(jobId);
    }
  }, [jobId, setSearchParams]);

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* 헤더 — job ID 입력 및 컨트롤 */}
      <div className="bg-white border-b px-4 py-3 flex items-center gap-2 flex-wrap">
        <h1 className="text-lg font-bold text-gray-800">Debug: Markdown Agent 반영</h1>
        <input
          type="text"
          value={jobId}
          onChange={(e) => setJobId(e.target.value)}
          placeholder="job ID 입력"
          className="flex-1 min-w-[200px] px-3 py-1.5 border rounded text-sm"
        />
        <button
          onClick={handleLoadJob}
          disabled={!jobId || loading}
          className="px-3 py-1.5 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "로딩..." : "Job 로드"}
        </button>
        <button
          onClick={() => setChatOpen(true)}
          disabled={!job || job?.status !== "done"}
          className="px-3 py-1.5 bg-green-600 text-white rounded text-sm hover:bg-green-700 disabled:opacity-50"
        >
          에이전트 채팅 열기
        </button>
        <button
          onClick={checkTiptapContent}
          className="px-3 py-1.5 bg-purple-600 text-white rounded text-sm hover:bg-purple-700"
        >
          Tiptap 내용 확인
        </button>
        <button
          onClick={reloadPreview}
          className="px-3 py-1.5 bg-orange-600 text-white rounded text-sm hover:bg-orange-700"
        >
          Preview 재로드
        </button>
        <button
          onClick={checkBackendMarkdown}
          className="px-3 py-1.5 bg-teal-600 text-white rounded text-sm hover:bg-teal-700"
        >
          백엔드 MD 확인
        </button>
        <button
          onClick={clearLogs}
          className="px-3 py-1.5 bg-gray-500 text-white rounded text-sm hover:bg-gray-600"
        >
          로그 초기화
        </button>
      </div>

      {/* 메인 영역 — 에디터 + 로그 패널 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 좌측 — 마크다운 에디터 */}
        <div className="flex-1 border-r overflow-hidden flex flex-col">
          <div className="bg-gray-100 px-3 py-2 text-xs text-gray-600 border-b">
            <div>job: {job?.filename || "(없음)"} | status: {job?.status || "-"} | files: {sourceFiles.length}</div>
            <div>displayMarkdown 길이: {displayMarkdown.length} | Tiptap 길이: {tiptapContent.length}</div>
            <div className="mt-1">
              displayMarkdown === Tiptap: {displayMarkdown === tiptapContent ? "✅ 일치" : "❌ 불일치"}
            </div>
          </div>
          <div className="flex-1 overflow-hidden">
            {displayMarkdown ? (
              <SimpleEditor
                key={selectedFileIndex}
                ref={editorRef}
                markdown={displayMarkdown}
                editable
                onChange={(updated) => {
                  setEditorContent(updated);
                  addLog("debug", "onChange", `SimpleEditor onChange (debounce)`, {
                    length: updated.length,
                    preview: updated.substring(0, 100),
                  });
                }}
              />
            ) : (
              <div className="flex items-center justify-center h-full text-gray-400">
                Job을 로드하세요
              </div>
            )}
          </div>
        </div>

        {/* 우측 — 로그 패널 */}
        <div className="w-[480px] flex flex-col bg-gray-900 text-gray-100 font-mono text-xs overflow-hidden">
          <div className="px-3 py-2 bg-gray-800 border-b border-gray-700 flex items-center justify-between">
            <span className="font-bold">디버그 로그 ({logs.length})</span>
            <label className="flex items-center gap-1 text-xs">
              <input
                type="checkbox"
                checked={true}
                readOnly
                className="w-3 h-3"
              />
              자동 스크롤
            </label>
          </div>
          <div className="flex-1 overflow-y-auto px-2 py-1">
            {logs.length === 0 ? (
              <div className="text-gray-500 p-2">로그가 없습니다. Job을 로드하세요.</div>
            ) : (
              logs.map((log, i) => (
                <div
                  key={i}
                  className={`py-1 border-b border-gray-800 ${
                    log.level === "error" ? "text-red-400" :
                    log.level === "warn" ? "text-yellow-400" :
                    log.level === "debug" ? "text-gray-500" :
                    log.level === "info" ? "text-green-300" : "text-gray-300"
                  }`}
                >
                  <div className="flex gap-2">
                    <span className="text-gray-500">{log.time}</span>
                    <span className="text-blue-400">[{log.category}]</span>
                    <span>{log.message}</span>
                  </div>
                  {log.data && (
                    <pre className="mt-1 ml-4 text-gray-400 whitespace-pre-wrap break-all max-h-40 overflow-y-auto">
                      {typeof log.data === "string" ? log.data : JSON.stringify(log.data, null, 2)}
                    </pre>
                  )}
                </div>
              ))
            )}
            <div ref={logEndRef} />
          </div>
        </div>
      </div>

      {/* 에이전트 채팅 모달 */}
      <AgentChatModal
        isOpen={chatOpen}
        onClose={() => setChatOpen(false)}
        context={{
          jobId,
          sourceType: "pdf",
          currentPage: selectedFileIndex + 1,
          selectedFileIndex,
          activeEditor: "markdown",
        }}
        onAgentComplete={handleAgentComplete}
      />
    </div>
  );
}
