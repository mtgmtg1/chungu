// [Flow: Step 1 (EDiscoveryViewer 마운트) -> Step 2 (preview API로 source_files 로드)
//       -> Step 3 (Timeline/Mapper 탭 전환)
//       -> Step 4 (Timeline 탭: EdiscoveryTimelinePanel 렌더링, 카드 클릭 시 미리보기 패널)
//       -> Step 5 (Mapper 탭: IssueTreeMapperPanel 렌더링)
//       -> Step 6 (헤더 재분석 버튼 클릭 → extract API → 폴링 → onJobRefresh)]
// e-Discovery GraphRAG 결과를 탭으로 전환하며 보여주는 뷰어.
// 상단에 재분석 버튼을 두고, Timeline 탭은 Chrono 기본 UI를 사용한다.

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { CalendarDays, Loader2, RefreshCw, X, FileText } from "lucide-react";
import EdiscoveryTimelinePanel from "./timeline/EdiscoveryTimelinePanel.jsx";
import EdiscoveryDetailCard from "./timeline/EdiscoveryDetailCard.jsx";
import IssueTreeMapperPanel from "./mapper/IssueTreeMapperPanel.jsx";
import { api } from "../api.js";

/** 폴링 타임아웃 — 10분. */
const POLL_TIMEOUT_MS = 600000;
/** 폴링 간격 — 2초. */
const POLL_INTERVAL_MS = 2000;

/**
 * 노드가 가리키는 페이지 번호를 반환한다.
 *
 * @param {Object} node - e-Discovery graph 노드
 * @returns {number} 1-based 페이지 번호
 */
function getNodePage(node) {
  const page = node?.data?.page;
  return typeof page === "number" && page > 0 ? page : 1;
}

/**
 * EDiscoveryViewer — e-Discovery GraphRAG 결과를 탭으로 전환하며 시각화.
 *
 * @param {Object} props
 * @param {string} props.jobId - Job ID
 * @param {Object} props.job - Job 객체 (ediscovery_* 필드 포함)
 * @param {Function} [props.onNodeClick] - 노드/아이템 클릭 시 호출될 콜백 (node) => void
 * @param {Function} [props.onJobRefresh] - job 데이터를 새로고침할 콜백 () => Promise<void>
 * @param {string} [props.defaultTab="timeline"] - 초기 활성 탭 ("timeline" | "mapper")
 */
export default function EDiscoveryViewer({ jobId, job, onNodeClick, onJobRefresh, defaultTab = "timeline" }) {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState(defaultTab); // "timeline" | "mapper"
  const legalProfile = job?.ediscovery_metrics?.legal_profile;

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [context, setContext] = useState(job?.ediscovery_context || "");
  const [reanalyzeOpen, setReanalyzeOpen] = useState(false);
  const [sourceFiles, setSourceFiles] = useState([]);
  const [previewNode, setPreviewNode] = useState(null);
  const [originalText, setOriginalText] = useState("");
  const [originalLoading, setOriginalLoading] = useState(false);

  const pollRef = useRef(null);
  const pollStartRef = useRef(0);

  /**
   * [Flow: Step 1 (job.ediscovery_context 변경 감지) -> Step 2 (분석 컨텍스트 기본값 동기화)]
   */
  useEffect(() => {
    setContext(job?.ediscovery_context || "");
  }, [job?.ediscovery_context]);

  /**
   * [Flow: Step 1 (jobId 마운트/변경) -> Step 2 (preview API로 source_files 로드)
   *       -> Step 3 (자식 컴포넌트에 전달)]
   */
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    async function loadSourceFiles() {
      try {
        const preview = await api.previewJob(jobId);
        if (cancelled) return;
        setSourceFiles(preview.source_files || []);
      } catch (err) {
        if (cancelled) return;
        setSourceFiles([]);
      }
    }
    loadSourceFiles();
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  /**
   * [Flow: Step 1 (폴링 중지 요청) -> Step 2 (interval 정리)]
   */
  const stopPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
  }, []);

  /**
   * [Flow: Step 1 (GET /ediscovery 상태 조회) -> Step 2 (done이면 onJobRefresh + 폴링 중지)
   *       -> Step 3 (error이면 오류 표시 + 폴링 중지) -> Step 4 (빈 상태이면 폴링 중지)
   *       -> Step 5 (processing이면 계속 폴링, 타임아웃 초과 시 중단)]
   */
  const startPolling = useCallback(() => {
    stopPolling();
    setLoading(true);
    pollStartRef.current = Date.now();

    pollRef.current = setInterval(async () => {
      if (Date.now() - pollStartRef.current > POLL_TIMEOUT_MS) {
        stopPolling();
        setError(t("page:result.ediscoveryTimeout"));
        setLoading(false);
        return;
      }

      try {
        const status = await api.getEdiscovery(jobId);
        await onJobRefresh?.();
        if (status.ediscovery_status === "done") {
          stopPolling();
          setLoading(false);
        } else if (status.ediscovery_status === "error") {
          stopPolling();
          setError(status.ediscovery_error || t("page:errors.networkError"));
          setLoading(false);
        } else if (!status.ediscovery_status) {
          stopPolling();
          setLoading(false);
        }
      } catch (err) {
        stopPolling();
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      }
    }, POLL_INTERVAL_MS);
  }, [jobId, t, onJobRefresh, stopPolling]);

  /**
   * [Flow: Step 1 (재분석 버튼 클릭) -> Step 2 (POST /ediscovery/extract)
   *       -> Step 3 (processing이면 폴링 시작, 완료되면 onJobRefresh)]
   */
  const handleAnalyze = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    setError("");
    setReanalyzeOpen(false);
    try {
      const response = await api.extractEdiscoveryGraph(
        jobId,
        { auto: true, context: context.trim() },
        { wait: false }
      );
      if (response.status === "processing") {
        startPolling();
      } else if (response.graph_data) {
        await onJobRefresh?.();
        setLoading(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  }, [jobId, loading, context, startPolling, onJobRefresh]);

  /**
   * [Flow: Step 1 (job.ediscovery_status가 processing이면) -> Step 2 (폴링 시작)]
   */
  useEffect(() => {
    if (job?.ediscovery_status === "processing") {
      startPolling();
    }
    return () => {
      stopPolling();
    };
  }, [job?.ediscovery_status, startPolling, stopPolling]);

  /**
   * [Flow: Step 1 (previewNode 변경) -> Step 2 (해당 페이지의 sourceFile result_markdown로 원문 설정)]
   */
  useEffect(() => {
    if (!previewNode) return;
    const page = getNodePage(previewNode);
    const sourceFile = sourceFiles.find((f) => f.page_num === page) || sourceFiles[0];
    if (!sourceFile?.result_markdown) {
      setOriginalText("");
      setOriginalLoading(false);
      return;
    }
    setOriginalLoading(true);
    setOriginalText("");
    setOriginalText(sourceFile.result_markdown);
    setOriginalLoading(false);
  }, [previewNode, sourceFiles]);

  /**
   * [Flow: Step 1 (Chrono 카드 클릭) -> Step 2 (previewNode 상태 설정)]
   */
  const handlePreview = useCallback((node) => {
    setPreviewNode(node);
  }, []);

  /**
   * [Flow: Step 1 (미리보기 패널 닫기) -> Step 2 (상태 초기화)]
   */
  const handleClosePreview = useCallback(() => {
    setPreviewNode(null);
    setOriginalText("");
    setOriginalLoading(false);
  }, []);

  return (
    <div className="h-full flex flex-col" data-oid="ediscovery-viewer">
      {/* 헤더 */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-outline-variant bg-surface-container-lowest">
        <CalendarDays size={16} className="text-primary" />
        <span className="text-sm font-medium text-on-surface">{t("page:result.ediscoveryView")}</span>
        <span className="text-xs text-on-surface-variant ml-2 hidden sm:inline">{t("page:result.ediscoveryHint")}</span>
        {/* LLM 자동 추출된 법률 분야/청구 원인 */}
        {legalProfile?.legal_domain && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary font-medium whitespace-nowrap hidden sm:inline">
            {legalProfile.legal_domain}
            {legalProfile.claim_type ? ` · ${legalProfile.claim_type}` : ""}
          </span>
        )}

        {/* 재분석 버튼 */}
        <button
          onClick={() => setReanalyzeOpen(true)}
          disabled={loading}
          className="ml-auto flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white text-xs font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
          data-oid="ediscovery-reanalyze-btn"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          {loading ? t("page:result.ediscoveryAnalyzing") : t("page:result.ediscoveryReanalyze")}
        </button>

        {/* 탭 전환 */}
        <div className="flex items-center gap-1 bg-surface-container-high rounded-lg p-0.5">
          <button
            onClick={() => setActiveTab("timeline")}
            className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
              activeTab === "timeline"
                ? "bg-surface text-on-surface shadow-sm"
                : "text-on-surface-variant hover:text-on-surface"
            }`}
            data-oid="ediscovery-tab-timeline"
          >
            <CalendarDays size={12} />
            {t("page:result.ediscoveryTabTimeline")}
          </button>
        </div>
      </div>

      {/* 캔버스 — 탭에 따라 Timeline 또는 Mapper 패널 렌더링 */}
      <div className="flex-1 min-h-0 relative">
        {activeTab === "timeline" ? (
          <EdiscoveryTimelinePanel
            jobId={jobId}
            job={job}
            sourceFiles={sourceFiles}
            onNodeClick={onNodeClick}
            onPreview={handlePreview}
          />
        ) : (
          <IssueTreeMapperPanel jobId={jobId} job={job} />
        )}
      </div>

      {/* 미리보기 패널 모달 */}
      {previewNode && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          onClick={handleClosePreview}
          data-oid="ediscovery-preview-modal"
        >
          <div
            className="bg-surface max-w-4xl w-full h-[80vh] rounded-xl shadow-lg border border-outline-variant flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex-shrink-0 flex items-center justify-between px-4 py-3 border-b border-outline-variant">
              <h3 className="text-sm font-bold text-on-surface flex items-center gap-2">
                <FileText size={16} />
                {previewNode.data?.label || previewNode.id}
              </h3>
              <button
                onClick={handleClosePreview}
                className="p-1 hover:bg-surface-container-high rounded text-on-surface-variant"
                aria-label={t("page:result.ediscoveryClose")}
              >
                <X size={16} />
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden">
              <EdiscoveryDetailCard
                node={previewNode}
                originalText={originalText}
                originalLoading={originalLoading}
              />
            </div>
          </div>
        </div>
      )}

      {/* 재분석 컨텍스트 입력 팝업 */}
      {reanalyzeOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          onClick={() => setReanalyzeOpen(false)}
          data-oid="ediscovery-reanalyze-popup"
        >
          <div
            className="bg-surface max-w-lg w-full rounded-xl shadow-lg border border-outline-variant p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3 mb-3">
              <h3 className="text-sm font-bold text-on-surface">{t("page:result.ediscoveryReanalyze")}</h3>
              <button
                onClick={() => setReanalyzeOpen(false)}
                className="p-1 hover:bg-surface-container-high rounded text-on-surface-variant"
                aria-label={t("page:result.ediscoveryClose")}
              >
                <X size={16} />
              </button>
            </div>
            <p className="text-xs text-on-surface-variant mb-2">{t("page:result.ediscoveryContextLabel")}</p>
            <textarea
              value={context}
              onChange={(e) => setContext(e.target.value)}
              placeholder={t("page:result.ediscoveryContextPlaceholder")}
              rows={8}
              disabled={loading}
              className="w-full text-sm text-on-surface bg-surface border border-outline-variant rounded-lg p-3 focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none min-h-[160px] disabled:opacity-50"
              data-oid="ediscovery-reanalyze-textarea"
            />
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => setReanalyzeOpen(false)}
                disabled={loading}
                className="px-3 py-1.5 text-xs font-medium text-on-surface-variant hover:bg-surface-container-high rounded-lg transition-colors disabled:opacity-50"
              >
                {t("page:result.ediscoveryClose")}
              </button>
              <button
                onClick={handleAnalyze}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white text-xs font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                {loading ? t("page:result.ediscoveryAnalyzing") : t("page:result.ediscoveryReanalyze")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
