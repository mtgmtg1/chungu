// [Flow: Step 1 (sandboxId 수신) -> Step 2 (파일 목록 로드) -> Step 3 (트리 뷰 렌더링)
//       -> Step 4 (파일 클릭 시 내용 조회) -> Step 5 (새로고침 버튼으로 목록 갱신)]
// sandbox workspace 의 파일을 브라우징하는 UI 컴포넌트.
// 에이전트가 생성한 파일을 사용자가 직접 확인할 수 있다.
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronRight, ChevronDown, File, Folder, RefreshCw, Download } from "lucide-react";
import { api } from "../api.js";

/**
 * [Flow: Step 1 (파일 목록을 트리 구조로 변환) -> Step 2 (디렉토리별 펼침 상태 관리)
 *       -> Step 3 (재귀적으로 트리 노드 렌더링)]
 *
 * @param {Object} props
 * @param {string} props.sandboxId - sandbox ID
 * @param {string} props.initialPath - 초기 조회 경로 (기본: /workspace)
 * @returns {JSX.Element} 파일 브라우저 컴포넌트
 */
export default function SandboxBrowser({ sandboxId, initialPath = "/workspace" }) {
  const { t } = useTranslation();
  const [currentPath, setCurrentPath] = useState(initialPath);
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [expandedDirs, setExpandedDirs] = useState(new Set([initialPath]));
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent] = useState(null);
  const [fileLoading, setFileLoading] = useState(false);

  /**
   * [Flow: Step 1 (sandboxId, path 수신) -> Step 2 (API 호출) -> Step 3 (파일 목록 상태 업데이트)]
   *
   * @param {string} path - 조회할 디렉토리 경로
   */
  const loadFiles = useCallback(
    async (path) => {
      if (!sandboxId) return;
      setLoading(true);
      setError(null);
      try {
        const result = await api.listSandboxFiles(sandboxId, path);
        setFiles(result.files || []);
        setCurrentPath(path);
      } catch (err) {
        setError(err.message || t("page:sandbox.loadFailed"));
      } finally {
        setLoading(false);
      }
    },
    [sandboxId, t],
  );

  /**
   * [Flow: Step 1 (파일 경로 수신) -> Step 2 (API 호출) -> Step 3 (파일 내용 표시)]
   *
   * @param {Object} file - 파일 객체 (name, size, type)
   */
  const handleFileClick = useCallback(
    async (file) => {
      const fullPath = `${currentPath}/${file.name}`;
      setSelectedFile(fullPath);
      setFileLoading(true);
      setFileContent(null);
      try {
        const result = await api.readSandboxFile(sandboxId, fullPath);
        setFileContent(result.content);
      } catch (err) {
        setFileContent(`Error: ${err.message || t("page:sandbox.readFailed")}`);
      } finally {
        setFileLoading(false);
      }
    },
    [sandboxId, currentPath, t],
  );

  /**
   * [Flow: Step 1 (디렉토리 경로 수신) -> Step 2 (펼침 상태 토글) -> Step 3 (하위 파일 로드)]
   *
   * @param {Object} dir - 디렉토리 객체
   */
  const handleDirClick = useCallback(
    (dir) => {
      const fullPath = `${currentPath}/${dir.name}`;
      const newExpanded = new Set(expandedDirs);
      if (newExpanded.has(fullPath)) {
        newExpanded.delete(fullPath);
      } else {
        newExpanded.add(fullPath);
        loadFiles(fullPath);
      }
      setExpandedDirs(newExpanded);
    },
    [currentPath, expandedDirs, loadFiles],
  );

  // 초기 로드
  useEffect(() => {
    if (sandboxId) loadFiles(initialPath);
  }, [sandboxId, initialPath, loadFiles]);

  // 파일 크기를 읽기 쉬운 형태로 변환
  const formatSize = (bytes) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  // 파일이 텍스트인지 확인 (간단한 확장자 기반)
  const isTextFile = (filename) => {
    const textExts = [".txt", ".md", ".json", ".csv", ".py", ".js", ".ts", ".sh", ".yaml", ".yml", ".xml", ".html", ".css", ".log", ".sql"];
    return textExts.some((ext) => filename.toLowerCase().endsWith(ext));
  };

  return (
    <div className="flex flex-col h-full border rounded-lg overflow-hidden bg-white dark:bg-neutral-900">
      {/* 헤더 */}
      <div className="flex items-center justify-between px-3 py-2 border-b bg-neutral-50 dark:bg-neutral-800">
        <div className="flex items-center gap-2 text-sm font-medium">
          <Folder className="w-4 h-4" />
          <span className="truncate">{currentPath}</span>
        </div>
        <button
          onClick={() => loadFiles(currentPath)}
          disabled={loading}
          className="p-1 rounded hover:bg-neutral-200 dark:hover:bg-neutral-700 disabled:opacity-50"
          title={t("page:sandbox.refresh")}
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* 파일 목록 */}
      <div className="flex-1 overflow-auto p-2">
        {error && (
          <div className="text-sm text-red-500 p-2">{error}</div>
        )}
        {loading && files.length === 0 && (
          <div className="text-sm text-neutral-400 p-2">{t("page:sandbox.loading")}</div>
        )}
        {!loading && files.length === 0 && !error && (
          <div className="text-sm text-neutral-400 p-2">{t("page:sandbox.empty")}</div>
        )}
        <ul className="space-y-0.5">
          {files.map((file, idx) => {
            const isDir = file.type === "directory";
            const fullPath = `${currentPath}/${file.name}`;
            const isExpanded = expandedDirs.has(fullPath);
            return (
              <li key={idx}>
                <button
                  onClick={() => (isDir ? handleDirClick(file) : handleFileClick(file))}
                  className={`flex items-center gap-2 w-full px-2 py-1 rounded text-sm text-left hover:bg-neutral-100 dark:hover:bg-neutral-800 ${
                    selectedFile === fullPath ? "bg-blue-50 dark:bg-blue-900/30" : ""
                  }`}
                >
                  {isDir ? (
                    <>
                      {isExpanded ? (
                        <ChevronDown className="w-4 h-4 flex-shrink-0" />
                      ) : (
                        <ChevronRight className="w-4 h-4 flex-shrink-0" />
                      )}
                      <Folder className="w-4 h-4 flex-shrink-0 text-blue-500" />
                    </>
                  ) : (
                    <>
                      <span className="w-4 flex-shrink-0" />
                      <File className="w-4 h-4 flex-shrink-0 text-neutral-400" />
                    </>
                  )}
                  <span className="truncate flex-1">{file.name}</span>
                  {!isDir && <span className="text-xs text-neutral-400">{formatSize(file.size)}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      {/* 파일 내용 미리보기 */}
      {selectedFile && (
        <div className="border-t max-h-64 overflow-auto bg-neutral-50 dark:bg-neutral-950">
          <div className="flex items-center justify-between px-3 py-1.5 border-b bg-neutral-100 dark:bg-neutral-800">
            <span className="text-xs font-mono truncate">{selectedFile}</span>
            <button
              onClick={() => setSelectedFile(null)}
              className="text-xs text-neutral-500 hover:text-neutral-700"
            >
              ✕
            </button>
          </div>
          {fileLoading ? (
            <div className="p-3 text-sm text-neutral-400">{t("page:sandbox.loading")}</div>
          ) : (
            <pre className="p-3 text-xs font-mono whitespace-pre-wrap break-all">
              {fileContent || ""}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
