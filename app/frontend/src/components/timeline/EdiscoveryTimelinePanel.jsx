// [Flow: Step 1 (job.ediscovery_graphs/status 수신) -> Step 2 (노드 분류 + Chrono items 변환)
//       -> Step 3 (자료 미리보기 메타데이터 로드: sourceFiles + 페이지 정보)
//       -> Step 4 (중앙 양측 주장/증거 카드 + 하단 React Chrono HORIZONTAL_ALL 대시보드 렌더링)
//       -> Step 5 (Chrono 카드/타이틀 클릭 시 SourcePanel 원문 페이지로 스크롤 연동)
//       -> Step 6 (양측 카드 클릭 시에도 SourcePanel 원문 페이지로 스크롤 연동)
//       -> Step 7 (재분석 버튼 클릭 시 컨텍스트 입력 팝업 노출)
//       -> Step 8 (재분석 API 호출 + 폴링으로 진행상황 추적)]
// e-Discovery GraphRAG 결과를 중앙 양측 주장/증거 카드 + 하단 React Chrono 타임라인으로 시각화하는 패널.
// 상단: 재분석 버튼만 배치. 중앙: CLIENT ARGUMENTS (PLAINTIFF) / OPPONENT REBUTTALS (DEFENDANT), 하단: 전체 타임라인.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, RefreshCw, AlertCircle, Network, X } from "lucide-react";
import { api } from "../../api.js";
import ResizableCourtroomCards from "./ResizableCourtroomCards.jsx";
import EdiscoveryTimelineStrip from "./EdiscoveryTimelineStrip.jsx";
import { classifyNodesBySide } from "../../utils/ediscoveryTimelineUtils.js";

/** 하단 타임라인 최소/최대 높이 (px) */
const MIN_TIMELINE_HEIGHT = 160;
const MAX_TIMELINE_HEIGHT = 600;
const DEFAULT_TIMELINE_HEIGHT = 280;

/** entity 코드 → i18n 키 매핑. */
const SWIMLANE_LABEL_KEYS = {
  plaintiff: "ediscoverySwimlanePlaintiff",
  defendant: "ediscoverySwimlaneDefendant",
  third_party: "ediscoverySwimlaneThirdParty",
  issue: "ediscoverySwimlaneIssue",
};

/** 폴링 타임아웃 — 10분. */
const POLL_TIMEOUT_MS = 600000;

/**
 * applyIssueDimmingToNodes — 원본 그래프 노드에 대해 쟁점 필터 디밍을 적용한다.
 * issue 노드는 자신의 label이, 그 외 노드는 data.issue 필드가 선택 집합에 없으면 dimmed.
 *
 * @param {Array<Object>} nodes - ediscovery_graphs.nodes (swimlane 포함)
 * @param {Set<string>} selectedIssues - 선택된 쟁점 라벨 집합
 * @returns {Array<Object>} dimmed 플래그가 추가된 새 nodes 배열
 */
function applyIssueDimmingToNodes(nodes, selectedIssues) {
  if (!selectedIssues || selectedIssues.size === 0) {
    return nodes.map((n) => ({ ...n, data: { ...n.data, dimmed: false } }));
  }
  return nodes.map((n) => {
    if (n.type === "swimlane") return n;
    const isIssue = n.type === "issue";
    const key = isIssue ? (n.data?.label || n.data?.issue || "") : (n.data?.issue || "");
    return { ...n, data: { ...n.data, dimmed: !selectedIssues.has(key) } };
  });
}

/**
 * sortByDateOrPage — 노드를 날짜(우선) 또는 페이지(차선) 순서로 정렬한다.
 *
 * @param {Array<Object>} nodes - e-Discovery graph 노드
 * @returns {Array<Object>} 정렬된 노드 배열
 */
function sortByDateOrPage(nodes) {
  return [...nodes].sort((a, b) => {
    const aDate = a.data?.date ? new Date(a.data.date).getTime() : NaN;
    const bDate = b.data?.date ? new Date(b.data.date).getTime() : NaN;
    if (!Number.isNaN(aDate) && !Number.isNaN(bDate) && aDate !== bDate) {
      return aDate - bDate;
    }
    const aPage = typeof a.data?.page === "number" ? a.data.page : Infinity;
    const bPage = typeof b.data?.page === "number" ? b.data.page : Infinity;
    if (aPage !== bPage) return aPage - bPage;
    return (a.id || "").localeCompare(b.id || "");
  });
}

/**
 * 노드가 가리키는 페이지 번호를 반환한다. 숫자가 아니면 1을 기본값으로 사용한다.
 *
 * @param {Object} node - e-Discovery graph 노드
 * @returns {number} 1-based 페이지 번호
 */
function getNodePage(node) {
  const page = node?.data?.page;
  return typeof page === "number" && page > 0 ? page : 1;
}

/**
 * buildChronoItem — 단일 e-Discovery 노드를 React Chrono TimelineItemModel로 변환한다.
 * 타임라인 카드에는 요약 텍스트만 노출하고, 원문은 클릭 시 왼쪽 SourcePanel에서 확인한다.
 *
 * @param {Object} node - e-Discovery graph 노드
 * @param {Object} _previewData - 하위 호환용 (미사용)
 * @param {Function} t - i18n translate 함수
 * @returns {Object} React Chrono item 객체
 */
export function buildChronoItem(node, _previewData, t) {
  const data = node.data || {};
  const entity = data.entity || (node.type === "evidence" ? "third_party" : node.type);
  const label = data.label || node.id;
  const page = getNodePage(node);
  const title = data.date ? String(data.date) : `p.${page}`;
  const subtitleKey =
    SWIMLANE_LABEL_KEYS[entity] || `ediscoverySwimlane${entity.charAt(0).toUpperCase() + entity.slice(1)}`;
  const subtitle = t(`page:result.${subtitleKey}`);
  // 카드에는 원문 대신 1~2문 요약만 표시; 원문은 클릭 시 왼쪽 SourcePanel에서 확인한다.
  const summary = data.summary || label;

  return {
    id: node.id,
    title,
    cardTitle: label,
    cardSubtitle: subtitle,
    cardDetailedText: summary,
    node,
  };
}

/**
 * EdiscoveryTimelinePanel — e-Discovery 결과를 중앙 양측 주장/증거 카드 + 하단 React Chrono 대시보드로 렌더링.
 *
 * @param {Object} props
 * @param {string} props.jobId - 현재 Job ID
 * @param {Object} props.job - Job 객체 (ediscovery_* 필드 포함)
 * @param {Function} [props.onNodeClick] - 노드/아이템 클릭 시 호출될 콜백 (node) => void
 */
export default function EdiscoveryTimelinePanel({ jobId, job, onNodeClick }) {
  const { t } = useTranslation();

  // React Chrono 상호작용 상태
  const [selectedNode, setSelectedNode] = useState(null);
  const [connectionPopupNode, setConnectionPopupNode] = useState(null);
  const [selectedIssues, setSelectedIssues] = useState(new Set());
  const [issueList, setIssueList] = useState([]);
  const [reanalyzeOpen, setReanalyzeOpen] = useState(false);

  // 메트릭 + 로딩 + 에러
  const [metrics, setMetrics] = useState({
    total_docs: 0,
    processed_chunks: 0,
    threshold: 0,
    anomalies_detected: 0,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // e-Discovery 분석 컨텍스트 — 첫 업로드 시 입력한 값을 기본값으로 사용
  const [context, setContext] = useState(job?.ediscovery_context || "");

  /**
   * [Flow: Step 1 (job.ediscovery_context 변경 감지) -> Step 2 (분석 컨텍스트 기본값 동기화)]
   */
  useEffect(() => {
    setContext(job?.ediscovery_context || "");
  }, [job?.ediscovery_context]);

  // 원본 노드 (디밍 적용 전)
  const [rawNodes, setRawNodes] = useState([]);

  // 중앙 상세 카드와 하단 타임라인 사이의 수직 리사이저 상태
  const [timelineHeight, setTimelineHeight] = useState(DEFAULT_TIMELINE_HEIGHT);
  const resizeStartRef = useRef({ y: 0, height: DEFAULT_TIMELINE_HEIGHT });

  const pollRef = useRef(null);
  const pollStartRef = useRef(0);

  /**
   * [Flow: Step 1 (job.ediscovery_graphs 변경 감지) -> Step 2 (rawNodes + issueList 저장)
   *       -> Step 3 (metrics 갱신) -> Step 4 (previewData는 별도 effect에서 로드)]
   */
  useEffect(() => {
    const graph = job?.ediscovery_graphs;
    if (!graph?.nodes?.length) {
      setRawNodes([]);
      setIssueList([]);
      setSelectedIssues(new Set());
      setSelectedNode(null);
      setConnectionPopupNode(null);
      setReanalyzeOpen(false);
      return;
    }

    setRawNodes(graph.nodes);

    const issues = [
      ...new Set(
        graph.nodes
          .filter((n) => n.type === "issue")
          .map((n) => n.data?.label || n.data?.issue)
          .filter(Boolean)
      ),
    ];

    setIssueList(issues);
    setSelectedIssues(new Set(issues));
    setMetrics(job?.ediscovery_metrics || { total_docs: 0, processed_chunks: 0, threshold: 0, anomalies_detected: 0 });
  }, [job?.ediscovery_graphs, job?.ediscovery_metrics]);

  /**
   * [Flow: Step 1 (job.ediscovery_status 변경) -> Step 2 (done이면 metrics 갱신)
   *       -> Step 3 (processing이면 폴링 시작)]
   */
  useEffect(() => {
    if (job?.ediscovery_status === "done" && job?.ediscovery_graphs?.nodes?.length > 0) {
      setMetrics(job.ediscovery_metrics || { total_docs: 0, processed_chunks: 0, threshold: 0, anomalies_detected: 0 });
    } else if (job?.ediscovery_status === "processing") {
      startPolling();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.ediscovery_status, job?.ediscovery_graphs, job?.ediscovery_metrics, jobId]);

  // 언마운트 시 폴링 정리
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  /**
   * [Flow: Step 1 (GET /ediscovery 상태 조회) -> Step 2 (done이면 metrics 갱신 + 폴링 중지)
   *       -> Step 3 (error이면 오류 표시 + 폴링 중지) -> Step 4 (빈 상태이면 폴링 중지)
   *       -> Step 5 (processing이면 계속 폴링, 타임아웃 초과 시 중단)]
   */
  const startPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    setLoading(true);
    pollStartRef.current = Date.now();

    pollRef.current = setInterval(async () => {
      if (Date.now() - pollStartRef.current > POLL_TIMEOUT_MS) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        setError(t("page:result.ediscoveryTimeout"));
        setLoading(false);
        return;
      }

      try {
        const status = await api.getEdiscovery(jobId);
        if (status.ediscovery_status === "done") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setMetrics(status.ediscovery_metrics || { total_docs: 0, processed_chunks: 0, threshold: 0, anomalies_detected: 0 });
          setLoading(false);
        } else if (status.ediscovery_status === "error") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setError(status.ediscovery_error || t("page:errors.networkError"));
          setLoading(false);
        } else if (!status.ediscovery_status) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setLoading(false);
        }
      } catch (err) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      }
    }, 2000);
  }, [jobId, t]);

  /**
   * [Flow: Step 1 (재분석 버튼 클릭) -> Step 2 (POST /ediscovery/extract) -> Step 3 (processing이면 폴링 시작)]
   */
  const handleAnalyze = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    setError("");
    try {
      const response = await api.extractEdiscoveryGraph(
        jobId,
        { auto: true, context: context.trim() },
        { wait: false },
      );
      if (response.status === "processing") {
        startPolling();
      } else if (response.graph_data) {
        setMetrics(response.ediscovery_metrics || { total_docs: 0, processed_chunks: 0, threshold: 0, anomalies_detected: 0 });
        setLoading(false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  }, [jobId, loading, startPolling, context]);

  /**
   * [Flow: Step 1 (수직 리사이즈 핸들에서 pointer 이벤트 시작)
   *       -> Step 2 (pointer move 시 타임라인 높이 갱신) -> Step 3 (pointer up 시 전역 리스너 제거)]
   */
  const handleTimelineResizeMove = useCallback((e) => {
    const delta = resizeStartRef.current.y - e.clientY;
    const next = Math.max(MIN_TIMELINE_HEIGHT, Math.min(MAX_TIMELINE_HEIGHT, resizeStartRef.current.height + delta));
    setTimelineHeight(next);
  }, []);

  const handleTimelineResizeUp = useCallback(() => {
    window.removeEventListener("pointermove", handleTimelineResizeMove);
    window.removeEventListener("pointerup", handleTimelineResizeUp);
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  }, [handleTimelineResizeMove]);

  const handleTimelineResizeDown = useCallback((e) => {
    e.preventDefault();
    resizeStartRef.current = { y: e.clientY, height: timelineHeight };
    window.addEventListener("pointermove", handleTimelineResizeMove);
    window.addEventListener("pointerup", handleTimelineResizeUp);
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";
  }, [timelineHeight, handleTimelineResizeMove, handleTimelineResizeUp]);

  /**
   * [Flow: Step 1 (rawNodes + selectedIssues로 dimmedNodes 생성)
   *       -> Step 2 (dimmed=false인 노드만 필터) -> Step 3 (날짜/페이지 정렬)
   *       -> Step 4 (React Chrono items로 변환)]
   */
  const chronoItems = useMemo(() => {
    if (!rawNodes.length) return [];
    const dimmedNodes = applyIssueDimmingToNodes(rawNodes, selectedIssues);
    const visibleNodes = dimmedNodes.filter((n) => n.type !== "swimlane" && !n.data?.dimmed);
    const sorted = sortByDateOrPage(visibleNodes);
    return sorted.map((node) => buildChronoItem(node, null, t));
  }, [rawNodes, selectedIssues, t]);

  /**
   * [Flow: Step 1 (selectedNode 기준으로 chronoItems 내 인덱스 계산)]
   */
  const activeItemIndex = useMemo(() => {
    if (!selectedNode || !chronoItems.length) return 0;
    const idx = chronoItems.findIndex((item) => item.node.id === selectedNode.id);
    return idx >= 0 ? idx : 0;
  }, [selectedNode, chronoItems]);

  /**
   * [Flow: Step 1 (Chrono 아이템 선택) -> Step 2 (해당 노드로 selectedNode 갱신) -> Step 3 (SourcePanel 스크롤 연동)]
   */
  const handleItemSelected = useCallback(
    (selected) => {
      const node = chronoItems[selected.index]?.node;
      if (node) {
        setSelectedNode(node);
        setConnectionPopupNode(node);
        onNodeClick?.(node);
      }
    },
    [chronoItems, onNodeClick]
  );

  const isEmpty = !loading && chronoItems.length === 0 && !error && job?.ediscovery_status === "done";

  /**
   * [Flow: Step 1 (chronoItems 변경) -> Step 2 (selectedNode가 items에 없으면 첫 항목으로 초기화)
   *       -> Step 3 (selectedNode가 null이면서 items가 있으면 첫 항목 선택)]
   */
  useEffect(() => {
    if (chronoItems.length === 0) {
      setSelectedNode(null);
      return;
    }
    const exists = selectedNode && chronoItems.some((item) => item.node.id === selectedNode.id);
    if (!exists) {
      setSelectedNode(chronoItems[0].node);
    }
  }, [chronoItems]);

  /**
   * [Flow: Step 1 (rawNodes 기반) -> Step 2 (classifyNodesBySide로 양측 주장/증거 분류)
   *       -> Step 3 (디밍 플래그 적용 후 중앙 양측 카드에 전달)]
   */
  const classifiedSides = useMemo(() => {
    const dimmedNodes = applyIssueDimmingToNodes(rawNodes, selectedIssues);
    return classifyNodesBySide(dimmedNodes);
  }, [rawNodes, selectedIssues]);

  const handleCardClick = useCallback(
    (node) => {
      setSelectedNode(node);
      setConnectionPopupNode(node);
      onNodeClick?.(node);
    },
    [onNodeClick]
  );

  return (
    <div className="h-full w-full flex flex-col relative" data-oid="ediscovery-courtroom">
      {/* ===== 상단 (판사석): 재분석 버튼만 배치 ===== */}
      <div className="flex-shrink-0 flex items-center justify-end gap-3 px-3 py-2 border-b border-outline-variant bg-surface-container-lowest">
        <button
          onClick={() => setReanalyzeOpen(true)}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white text-xs font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
          data-oid="ediscovery-analyze-btn"
        >
          {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          {loading ? t("page:result.ediscoveryAnalyzing") : t("page:result.ediscoveryReanalyze")}
        </button>
      </div>

      {/* ===== 중앙 — 양측 주장/증거 카드 (끝부분 드래그로 너비 조절, 원문은 왼쪽 SourcePanel에서 제공) ===== */}
      <div className="flex-1 min-h-0 p-3" data-oid="ediscovery-courtroom-cards">
        <ResizableCourtroomCards classifiedSides={classifiedSides} onNodeClick={handleCardClick} />
      </div>

      {/* ===== 하단 — 타임라인 스트립 (별도 컴포넌트로 분리해 디버깅/재사용 가능) ===== */}
      <EdiscoveryTimelineStrip
        items={chronoItems}
        activeItemIndex={activeItemIndex}
        onItemSelected={handleItemSelected}
        timelineHeight={timelineHeight}
        onResizePointerDown={handleTimelineResizeDown}
        title={t("page:result.ediscoveryCourtroomTimeline")}
      />

      {/* 로딩 오버레이 */}
      {loading && (
        <div className="absolute inset-0 z-40 bg-surface/80 flex flex-col items-center justify-center gap-3" data-oid="ediscovery-loading">
          <Loader2 size={28} className="animate-spin text-primary" />
          <p className="text-sm text-on-surface-variant">{t("page:result.ediscoveryAnalyzing")}</p>
        </div>
      )}

      {/* 에러 메시지 */}
      {error && (
        <div
          className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 bg-error-container border border-error text-on-error-container px-4 py-3 rounded-lg shadow-md flex items-start gap-2 max-w-[90%]"
          data-oid="ediscovery-error"
        >
          <AlertCircle size={18} className="flex-shrink-0 mt-0.5" />
          <div className="text-sm">
            <p className="font-medium">{t("page:result.ediscoveryError")}</p>
            <p className="text-xs opacity-90">{error}</p>
          </div>
          <button onClick={handleAnalyze} className="ml-2 p-1 hover:bg-error/10 rounded" title={t("page:result.retry")}>
            <RefreshCw size={14} />
          </button>
        </div>
      )}

      {/* 빈 상태 안내 */}
      {isEmpty && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center text-on-surface-variant gap-3" data-oid="ediscovery-empty">
          <Network size={40} className="text-primary/40" />
          <p className="text-sm text-center max-w-xs">{t("page:result.ediscoveryEmpty")}</p>
          <button
            onClick={handleAnalyze}
            className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity"
          >
            <RefreshCw size={16} />
            {t("page:result.ediscoveryReanalyze")}
          </button>
        </div>
      )}

      {/* 연결 근거 팝업 — 카드/타임라인 클릭 시 LLM이 설명한 원문 연결 이유 표시 */}
      {connectionPopupNode && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          onClick={() => setConnectionPopupNode(null)}
          data-oid="ediscovery-connection-popup"
        >
          <div
            className="bg-surface max-w-md w-full rounded-xl shadow-lg border border-outline-variant p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3 mb-3">
              <h3 className="text-sm font-bold text-on-surface">{connectionPopupNode.data?.label || connectionPopupNode.id}</h3>
              <button
                onClick={() => setConnectionPopupNode(null)}
                className="p-1 hover:bg-surface-container-high rounded text-on-surface-variant"
                aria-label={t("page:result.ediscoveryClose")}
              >
                <X size={16} />
              </button>
            </div>
            <div className="text-xs text-on-surface-variant mb-3 space-y-1">
              <p>
                {t("page:result.ediscoveryOriginalText")}: {connectionPopupNode.data?.source_file || "-"}
              </p>
              <p>
                {t("page:result.ediscoveryPage")}: {connectionPopupNode.data?.original_page || connectionPopupNode.data?.page || "-"}
              </p>
            </div>
            <div>
              <p className="text-[10px] font-medium uppercase tracking-wide text-on-surface-variant mb-1">
                {t("page:result.ediscoveryConnectionReason")}
              </p>
              <div className="bg-surface-container-lowest rounded-lg p-3 text-sm text-on-surface leading-relaxed max-h-60 overflow-y-auto">
                {connectionPopupNode.data?.connection_reason || t("page:result.ediscoveryConnectionReasonEmpty")}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 재분석 컨텍스트 입력 팝업 — 긴 텍스트로 분석 맥락을 입력받는다 */}
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
                onClick={() => {
                  setReanalyzeOpen(false);
                  handleAnalyze();
                }}
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
