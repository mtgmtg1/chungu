// [Flow: Step 1 (onComplete 콜백 수신) -> Step 2 (파일/폴더 드래그앤드롭 + input 선택) -> Step 3 (중복 제거 후 파일 목록 관리) -> Step 4 (제출 시 initJob + TUS 업로드 + createJob) -> Step 5 (완료 시 onComplete(jobId) 호출)]
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { FileUp, Loader2, X } from "lucide-react";
import { api } from "../api.js";
import { uploadFilesTUS } from "../tusUpload.js";
import { AnimatedRow } from "./AnimatedList.jsx";
import { useAuth } from "../AuthContext.jsx";

/**
 * 랜딩페이지와 동일한 업로드 플로우를 제공하는 재사용 가능한 위젯입니다.
 * 폴더 및 다중 파일 선택을 모두 지원하며, initJob/TUS/createJob 호출 후
 * 완료된 jobId를 onComplete 콜백으로 전달합니다.
 *
 * @param {object} props
 * @param {(jobId: string) => void} props.onComplete - 업로드 및 createJob/confirm 완료 시 호출
 * @param {string} [props.submitLabel] - 제출 버튼에 표시할 텍스트 (미지정 시 "변환 시작")
 * @param {string} [props.jobId] - 기존 Job에 파일을 추가하는 모드일 때 사용
 * @param {(progress: object) => void} [props.onProgress] - 업로드 진행률 변경 시 호출
 */
export default function UploadWidget({ onComplete, submitLabel, jobId, onProgress }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const nav = useNavigate();
  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [doclingRefinement, setDoclingRefinement] = useState(false);
  const [ediscoveryContext, setEdiscoveryContext] = useState("");
  const [uploadProgress, setUploadProgress] = useState({ current: 0, total: 0, percent: 0, fileName: "" });

  // [Flow: Step 1 (새 진행률 상태 설정) -> Step 2 (상위 컴포넌트에 동일한 상태 전달)]
  function updateProgress(next) {
    setUploadProgress(next);
    if (onProgress) onProgress(next);
  }

  // [Flow: Step 1 (기존 파일 집합 생성) -> Step 2 (새 파일들의 이름+크기 중복 검사) -> Step 3 (중복이 아닌 파일만 병합)]
  function addFiles(newFiles) {
    setFiles((prev) => {
      const existing = new Set(prev.map((f) => `${f.name}|${f.size}`));
      const merged = [...prev];
      for (const f of newFiles) {
        const key = `${f.name}|${f.size}`;
        if (!existing.has(key)) {
          existing.add(key);
          merged.push(f);
        }
      }
      return merged;
    });
  }

  // [Flow: Step 1 (제거할 인덱스 수신) -> Step 2 (해당 인덱스를 제외한 새 배열 반환)]
  function removeFile(index) {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  }

  // [Flow: Step 1 (DataTransferItem에서 entry 획득) -> Step 2 (파일이면 collected에 추가) -> Step 3 (폴더면 하위 entry를 재귀 탐색)]
  async function traverseEntry(entry, collected, basePath = "") {
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      if (!file) return;
      file.webkitRelativePath = basePath + file.name;
      collected.push(file);
      return;
    }
    if (!entry.isDirectory) return;
    const reader = entry.createReader();
    const entries = await new Promise((resolve) => reader.readEntries(resolve));
    for (const child of entries) {
      await traverseEntry(child, collected, basePath + entry.name + "/");
    }
  }

  // [Flow: Step 1 (dragover/drop 기본 동작 차단) -> Step 2 (항목이 있으면 entry 기반으로 수집, 없으면 files 기반) -> Step 3 (수집된 파일 목록을 addFiles로 등록)]
  async function handleDrop(e) {
    e.preventDefault();
    const collected = [];
    try {
      const items = Array.from(e.dataTransfer.items || []);
      if (items.length) {
        for (const item of items) {
          const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
          if (entry?.isDirectory) {
            await traverseEntry(entry, collected);
          } else {
            const file = item.getAsFile ? item.getAsFile() : null;
            if (file) collected.push(file);
          }
        }
      } else {
        const droppedFiles = Array.from(e.dataTransfer.files || []);
        collected.push(...droppedFiles);
      }
      if (collected.length) addFiles(collected);
    } catch (err) {
      console.error("Drag-and-drop failed:", err);
    }
  }

  // [Flow: Step 1 (로그인 여부 확인) -> Step 2 (파일 존재 여부 확인) -> Step 3 (initJob으로 임시 Job 및 Storage 경로 할당) -> Step 4 (TUS 청크 업로드) -> Step 5 (createJob로 분석 및 비용 계산) -> Step 6 (onComplete 호출)]
  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    if (!user) {
      nav("/login");
      return;
    }
    if (!files.length) return setError(t("page:upload.selectFile"));

    setSubmitting(true);
    try {
      const filesPayload = files.map((f) => ({
        name: f.name,
        size: f.size,
        relative_path: f.webkitRelativePath || f.name,
      }));

      const isAddMode = Boolean(jobId);
      const initRes = isAddMode
        ? await api.initAddFiles(jobId, { files: filesPayload })
        : await api.initJob({
            files: filesPayload,
            docling_refinement: doclingRefinement,
          });

      const uploadItems = files.map((f, i) => ({
        file: f,
        storagePath: initRes.upload_paths[i].storage_path,
      }));

      updateProgress({ current: 0, total: files.length, percent: 0, fileName: files[0]?.name || "" });

      await uploadFilesTUS(uploadItems, (fileIndex, pct) => {
        updateProgress({
          current: fileIndex,
          total: files.length,
          percent: pct,
          fileName: files[fileIndex]?.name || "",
        });
      });

      const createPayload = {
        files: initRes.upload_paths.map((p) => ({
          storage_path: p.storage_path,
          original_name: p.original,
          relative_path: p.relative_path,
        })),
        ediscovery_context: ediscoveryContext.trim(),
      };

      if (isAddMode) {
        console.log('[UploadWidget] confirmAddFiles 호출:', jobId, createPayload);
        try {
          await api.confirmAddFiles(jobId, createPayload);
          console.log('[UploadWidget] confirmAddFiles 성공:', jobId);
        } catch (err) {
          console.error('[UploadWidget] confirmAddFiles 실패:', err);
          throw err;
        }
        if (onComplete) onComplete(jobId);
      } else {
        const res = await api.createJob(initRes.job_id, createPayload);
        if (onComplete) onComplete(res.job_id);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setSubmitting(false);
      updateProgress({ current: 0, total: 0, percent: 0, fileName: "" });
    }
  }

  const ACCEPT_TYPES = ".pdf,.zip,.rar,.7z,.tar.gz,.png,.jpg,.jpeg,.gif,.webp,.mp3,.wav,.mp4,.avi,.mov,.mkv,.webm,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.html,.htm,.hwp,.hwpx";

  return (
    <form
      onSubmit={handleSubmit}
      onDrop={(e) => { e.preventDefault(); }}
      onDragOver={(e) => { e.preventDefault(); }}
      data-oid="upload-widget-form"
    >
      <div
        onDrop={handleDrop}
        onDragOver={(e) => { e.preventDefault(); }}
        onDragEnter={(e) => { e.preventDefault(); }}
        onDragLeave={(e) => { e.preventDefault(); }}
        className="group relative bg-surface border border-outline-variant/60 p-2 shadow-2xl shadow-primary/5 hover:shadow-primary/10 transition-all duration-500 block cursor-pointer"
        data-oid="upload-widget-dropzone"
      >
        <div className="border-2 border-dashed border-outline-variant/40 group-hover:border-primary/40 p-4 md:p-8 min-h-[200px] flex flex-col items-center justify-center transition-colors bg-surface-container-lowest" data-oid="upload-widget-inner">
          <div className="w-14 h-14 bg-primary-container/10 flex items-center justify-center mb-4 group-hover:scale-110 transition-transform duration-300" data-oid="upload-widget-icon-wrap">
            <FileUp className="text-primary" size={32} data-oid="upload-widget-icon" />
          </div>
          <h3 className="text-headline-sm font-medium text-on-surface mb-2" data-oid="upload-widget-title">
            {t("page:upload.dropText")}
          </h3>
          <p className="text-body-sm text-outline" data-oid="upload-widget-types">
            {t("page:upload.fileTypes")}
          </p>
          <div className="mt-4 md:mt-6 flex flex-col md:flex-row items-center gap-4 md:gap-3 w-full md:w-auto" data-oid="upload-widget-buttons">
            <label
              className="px-5 py-2.5 bg-primary text-on-primary font-headline-md hover:bg-primary-container transition-all shadow-md cursor-pointer w-full md:w-auto text-center"
              data-oid="upload-widget-select-files"
            >
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                accept={ACCEPT_TYPES}
                onChange={(e) => { addFiles(Array.from(e.target.files || [])); e.target.value = ""; }}
                data-oid="upload-widget-file-input"
              />
              {t("page:upload.selectFiles")}
            </label>
            <label
              className="px-5 py-2.5 border border-outline-variant text-on-surface font-headline-md hover:bg-surface-container transition-all cursor-pointer w-full md:w-auto text-center"
              data-oid="upload-widget-select-folder"
            >
              <input
                ref={folderInputRef}
                type="file"
                webkitdirectory=""
                directory=""
                multiple
                className="hidden"
                accept={ACCEPT_TYPES}
                onChange={(e) => { addFiles(Array.from(e.target.files || [])); e.target.value = ""; }}
                data-oid="upload-widget-folder-input"
              />
              {t("page:upload.selectFolder")}
            </label>
          </div>
        </div>
      </div>

      {/* [Flow: e-Discovery 컨텍스트 입력 — 사용자가 프로젝트 주요/중요 사항을 입력하면 분석 시 LLM 프롬프트에 포함] */}
      <div className="mt-4 bg-surface-container-lowest border border-outline-variant p-3" data-oid="upload-widget-context">
        <label htmlFor="ediscovery-context" className="block text-sm font-medium text-on-surface mb-1.5">
          {t("page:upload.ediscoveryContextLabel")}
        </label>
        <p className="text-xs text-on-surface-variant mb-2" data-oid="upload-widget-context-hint">
          {t("page:upload.ediscoveryContextHint")}
        </p>
        <textarea
          id="ediscovery-context"
          value={ediscoveryContext}
          onChange={(e) => setEdiscoveryContext(e.target.value)}
          placeholder={t("page:upload.ediscoveryContextPlaceholder")}
          rows={3}
          className="w-full text-sm text-on-surface bg-surface border border-outline-variant rounded-lg p-2.5 focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
          data-oid="upload-widget-context-input"
        />
      </div>

      {files.length > 0 && (
        <div className="mt-4 bg-white border border-outline-variant p-3 text-left" data-oid="upload-widget-file-list">
          <p className="text-sm font-medium text-on-surface mb-2" data-oid="upload-widget-list-title">
            {t("page:upload.selectedFiles")}
          </p>
          <ul className="text-sm text-on-surface-variant space-y-1" data-oid="upload-widget-list">
            {files.map((f, i) => (
              <AnimatedRow key={i} index={i}>
                <li className="flex items-center gap-2 min-w-0" data-oid={`upload-widget-file-${i}`}>
                  <span className="bg-surface-container px-2 py-0.5 truncate min-w-0" data-oid={`upload-widget-name-${i}`}>
                    {f.name}
                  </span>
                  {f.webkitRelativePath && (
                    <span className="text-outline text-xs truncate max-w-xs" data-oid={`upload-widget-path-${i}`}>
                      {f.webkitRelativePath}
                    </span>
                  )}
                  <span data-oid={`upload-widget-size-${i}`}>({(f.size / 1024 / 1024).toFixed(2)} MB)</span>
                  <button
                    type="button"
                    onClick={() => removeFile(i)}
                    className="ml-auto text-outline hover:text-red-500 transition-colors flex-shrink-0"
                    data-oid={`upload-widget-rm-${i}`}
                  >
                    <X size={16} />
                  </button>
                </li>
              </AnimatedRow>
            ))}
          </ul>
          {error && <p className="text-red-600 text-sm mt-3" data-oid="upload-widget-error">{error}</p>}
          {submitting && uploadProgress.total > 0 && (
            <div className="mt-3 mb-2" data-oid="upload-widget-progress">
              <div className="flex items-center justify-between text-xs text-on-surface-variant mb-1">
                <span className="truncate max-w-[200px]" data-oid="upload-widget-prog-file">
                  {uploadProgress.fileName}
                </span>
                <span data-oid="upload-widget-prog-count">
                  {uploadProgress.current + 1}/{uploadProgress.total} ({uploadProgress.percent}%)
                </span>
              </div>
              <div className="w-full bg-surface-container h-2 overflow-hidden" data-oid="upload-widget-prog-bg">
                <div
                  className="bg-primary h-full transition-all duration-300"
                  style={{ width: `${uploadProgress.percent}%` }}
                  data-oid="upload-widget-prog-fill"
                />
              </div>
            </div>
          )}
          <div className="flex gap-3 mt-4" data-oid="upload-widget-actions">
            <button
              type="button"
              onClick={() => setFiles([])}
              className="flex-1 border border-outline-variant rounded-lg py-2.5 text-sm font-medium hover:bg-surface-container transition-colors"
              data-oid="upload-widget-cancel"
            >
              {t("page:upload.cancel")}
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="flex-1 bg-primary text-on-primary rounded-lg py-2.5 font-medium hover:bg-primary-container transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              data-oid="upload-widget-submit"
            >
              {submitting ? (
                <>
                  <Loader2 className="animate-spin" size={18} data-oid="upload-widget-spinner" />{" "}
                  {t("page:upload.uploading")}
                </>
              ) : (
                submitLabel || t("page:upload.start")
              )}
            </button>
          </div>
        </div>
      )}
    </form>
  );
}
