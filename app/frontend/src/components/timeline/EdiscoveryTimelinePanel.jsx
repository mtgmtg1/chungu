// [Flow: Step 1 (job.ediscovery_graphs/status 수신) -> Step 2 (노드 분류 + Chrono items 변환)
//       -> Step 3 (자료 미리보기 메타데이터 로드: sourceFiles + 페이지 정보)
//       -> Step 4 (중앙 상세 카드 + 하단 React Chrono HORIZONTAL_ALL 대시보드 렌더링)
//       -> Step 5 (Chrono 카드/타이틀 클릭 시 중앙 카드가 해당 노드 정보 + 원문으로 갱신)
//       -> Step 6 (쟁점 필터 토글 시 items 필터 갱신)
//       -> Step 7 (재분석 API 호출 + 폴링으로 진행상황 추적)]
// e-Discovery GraphRAG 결과를 중앙 상세 카드 + 하단 React Chrono 타임라인으로 시각화하는 패널.
// 상단: 쟁점 필터 + 메트릭, 중앙: 선택 노드의 미리보기 + 정보 + 원문, 하단: 전체 타임라인.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Chrono } from "react-chrono";
import { AlertTriangle, Loader2, RefreshCw, AlertCircle, Network } from "lucide-react";
import { api } from "../../api.js";
import IssueFilterBar from "../flow/IssueFilterBar.jsx";
import TimelinePreviewCard from "./TimelinePreviewCard.jsx";
import EdiscoveryDetailCard from "./EdiscoveryDetailCard.jsx";

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
 * node에 맞는 sourceFile을 찾는다. 없으면 PDF/문서를 우선으로 폴백한다.
 *
 * @param {Object} node - e-Discovery graph 노드
 * @param {Object} previewData - sourceFiles를 포함한 미리보기 메타데이터
 * @returns {Object|null} sourceFile 객체 또는 null
 */
function getNodeSourceFile(node, previewData) {
  if (!previewData?.sourceFiles?.length) return null;
  const page = getNodePage(node);
  const files = previewData.sourceFiles;
  return (
    files.find((f) => f.page_num === page) ||
    files.find((f) => ["pdf", "docx", "hwp"].includes(f.type)) ||
    files[0] ||
    null
  );
}

/**
 * buildChronoItem — 단일 e-Discovery 노드를 React Chrono TimelineItemModel로 변환한다.
 * PDF/이미지/비디오는 Chrono의 media 프로퍼티를, 그 외에는 timelineContent(미리보기 카드)를 사용한다.
 *
 * @param {Object} node - e-Discovery graph 노드
 * @param {Object} previewData - sourceFiles를 포함한 미리보기 메타데이터
 * @param {Function} t - i18n translate 함수
 * @returns {Object} React Chrono item 객체
 */
function buildChronoItem(node, previewData, t) {
  const data = node.data || {};
  const entity = data.entity || (node.type === "evidence" ? "third_party" : node.type);
  const label = data.label || node.id;
  const page = getNodePage(node);
  const title = data.date ? String(data.date) : `p.${page}`;
  const subtitleKey =
    SWIMLANE_LABEL_KEYS[entity] || `ediscoverySwimlane${entity.charAt(0).toUpperCase() + entity.slice(1)}`;
  const subtitle = t(`page:result.${subtitleKey}`);
  const summary = data.summary || label;

  const sourceFile = getNodeSourceFile(node, previewData);

  const item = {
    id: node.id,
    title,
    cardTitle: label,
    cardSubtitle: subtitle,
    cardDetailedText: summary,
    node,
  };

  // [Flow: 이미지/비디오는 React Chrono media 프로퍼티로 렌더링 -> PDF/오디오/텍스트는 timelineContent 사용]
  if (sourceFile?.type === "image") {
    item.media = {
      type: "IMAGE",
      name: sourceFile.name || label,
      source: { url: sourceFile.url || sourceFile.preview_url },
    };
  } else if (sourceFile?.type === "video") {
    item.media = {
      type: "VIDEO",
      name: sourceFile.name || label,
      source: { url: sourceFile.preview_url },
    };
  } else {
    item.timelineContent = <TimelinePreviewCard node={node} previewData={previewData} />;
  }

  return item;
}

/**
 * EdiscoveryTimelinePanel — e-Discovery 결과를 중앙 상세 카드 + 하단 React Chrono 대시보드로 렌더링.
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
  const [selectedIssues, setSelectedIssues] = useState(new Set());
  const [issueList, setIssueList] = useState([]);

  // 중앙 상세 카드 원문
  const [selectedPageText, setSelectedPageText] = useState("");
  const [selectedPageLoading, setSelectedPageLoading] = useState(false);

  // 메트릭 + 로딩 + 에러
  const [metrics, setMetrics] = useState({
    total_docs: 0,
    processed_chunks: 0,
    threshold: 0,
    anomalies_detected: 0,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // 원본 노드 (디밍 적용 전)
  const [rawNodes, setRawNodes] = useState([]);

  // 자료 미리보기 메타데이터 (sourceFiles 기반)
  const [previewData, setPreviewData] = useState(null);

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
   * [Flow: Step 1 (jobId, job.status 변경) -> Step 2 (완료된 job이면 GET /preview 1페이지 호출)
   *       -> Step 3 (sourceFiles를 page_num 기준 맵으로 저장)]
   */
  useEffect(() => {
    if (!jobId || job?.status !== "done") {
      setPreviewData(null);
      return;
    }

    let cancelled = false;
    const loadPreview = async () => {
      try {
        // 1페이지만 요청해도 서버가 source_files 전체를 반환하므로 최소한의 markdown만 불러온다.
        const data = await api.previewJob(jobId, 1, 1);
        if (cancelled) return;
        setPreviewData({
          sourceFiles: data.source_files || [],
          sourceUrl: data.source_url,
          sourceType: data.source_type,
          imageUrls: data.image_urls || [],
          lastPage: data.last_page,
        });
      } catch (err) {
        if (!cancelled) {
          console.warn("[EdiscoveryTimelinePanel] preview load failed:", err);
          setPreviewData({ sourceFiles: [] });
        }
      }
    };

    loadPreview();
    return () => {
      cancelled = true;
    };
  }, [jobId, job?.status]);

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
      const response = await api.extractEdiscoveryGraph(jobId, { auto: true }, { wait: false });
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
  }, [jobId, loading, startPolling]);

  /**
   * [Flow: Step 1 (쟁점 토글) -> Step 2 (선택 집합 갱신)]
   */
  const handleToggleIssue = useCallback((issue) => {
    setSelectedIssues((prev) => {
      const next = new Set(prev);
      if (next.has(issue)) next.delete(issue);
      else next.add(issue);
      return next;
    });
  }, []);

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
    return sorted.map((node) => buildChronoItem(node, previewData, t));
  }, [rawNodes, selectedIssues, previewData, t]);

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
        onNodeClick?.(node);
      }
    },
    [chronoItems, onNodeClick]
  );

  /**
   * [Flow: Step 1 (원본 PDF 보기 버튼) -> Step 2 (onNodeClick에 { data: { page } } 전달)]
   */
  const handleViewSource = useCallback(
    (page) => {
      onNodeClick?.({ data: { page } });
    },
    [onNodeClick]
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
   * [Flow: Step 1 (selectedNode/previewData 변경) -> Step 2 (sourceFile.result_markdown 우선 사용)
   *       -> Step 3 (result_markdown이 없으면 GET /preview?page=page&end_page=page로 원문 로드)
   *       -> Step 4 (로딩 상태 갱신 + selectedPageText 설정)]
   */
  useEffect(() => {
    if (!selectedNode || !previewData || !jobId) {
      setSelectedPageText("");
      setSelectedPageLoading(false);
      return;
    }

    let cancelled = false;
    const loadOriginalText = async () => {
      setSelectedPageLoading(true);
      setSelectedPageText("");

      const sourceFile = getNodeSourceFile(selectedNode, previewData);
      const rawText = sourceFile?.result_markdown;
      if (rawText && rawText.trim().length > 0) {
        if (!cancelled) setSelectedPageText(rawText);
        if (!cancelled) setSelectedPageLoading(false);
        return;
      }

      const page = getNodePage(selectedNode);
      try {
        const data = await api.previewJob(jobId, page, page);
        if (!cancelled) setSelectedPageText(data.markdown || "");
      } catch (err) {
        console.warn("[EdiscoveryTimelinePanel] original text load failed:", err);
        if (!cancelled) setSelectedPageText("");
      }
      if (!cancelled) setSelectedPageLoading(false);
    };

    loadOriginalText();
    return () => {
      cancelled = true;
    };
  }, [selectedNode, previewData, jobId]);

  return (
    <div className="h-full w-full flex flex-col relative" data-oid="ediscovery-courtroom">
      {/* ===== 상단 (판사석): 쟁점 필터 + 메트릭 + 재분석 ===== */}
      <div className="flex-shrink-0 flex items-center justify-between gap-3 px-3 py-2 border-b border-outline-variant bg-surface-container-lowest">
        {/* 쟁점 필터 */}
        {issueList.length > 0 && chronoItems.length > 0 && (
          <div className="flex-1 overflow-x-auto">
            <IssueFilterBar issues={issueList} selectedIssues={selectedIssues} onToggle={handleToggleIssue} />
          </div>
        )}
        {/* 메트릭 + 재분석 버튼 */}
        <div className="flex items-center gap-3 flex-shrink-0">
          <div className="hidden md:flex items-center gap-3 text-xs text-on-surface-variant">
            <span>
              {t("page:result.ediscoveryTotalDocs")}: <strong className="text-on-surface">{metrics.total_docs || 0}</strong>
            </span>
            <span>
              {t("page:result.ediscoveryProcessedChunks")}: <strong className="text-on-surface">{metrics.processed_chunks || 0}</strong>
            </span>
            {metrics.anomalies_detected ? (
              <span className="flex items-center gap-1">
                <AlertTriangle size={11} className="text-red-600" />
                <strong className="text-on-surface">{metrics.anomalies_detected}</strong>
              </span>
            ) : null}
          </div>
          <button
            onClick={handleAnalyze}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white text-xs font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
            data-oid="ediscovery-analyze-btn"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            {loading ? t("page:result.ediscoveryAnalyzing") : t("page:result.ediscoveryReanalyze")}
          </button>
        </div>
      </div>

      {/* ===== 중앙 — 선택 노드 상세 카드 (미리보기 + 정보 + 원문) ===== */}
      <div className="flex-1 min-h-0 p-3" data-oid="ediscovery-detail-card">
        <EdiscoveryDetailCard
          node={selectedNode}
          previewData={previewData}
          originalText={selectedPageText}
          originalLoading={selectedPageLoading}
          onViewSource={handleViewSource}
        />
      </div>

      {/* ===== 하단 — React Chrono Horizontal All Dashboard (고정 높이) ===== */}
      <div className="h-96 flex-shrink-0 relative border-t border-outline-variant bg-surface-container-lowest" data-oid="ediscovery-chrono-section">
        {/* 타임라인 헤더 라벨 */}
        {chronoItems.length > 0 && (
          <div className="absolute top-1 left-2 z-10 text-[10px] font-bold uppercase tracking-wide text-on-surface-variant bg-surface-container-lowest/80 px-2 py-0.5 rounded">
            {t("page:result.ediscoveryCourtroomTimeline")}
          </div>
        )}

        {/* React Chrono — Horizontal All Dashboard */}
        {chronoItems.length > 0 && (
          <div className="absolute inset-0 overflow-auto" data-oid="ediscovery-chrono">
            <Chrono
              key={previewData ? "chrono-loaded" : "chrono-loading"}
              items={chronoItems}
              mode="HORIZONTAL_ALL"
              showAllCardsHorizontal
              cardWidth={240}
              cardHeight={220}
              itemWidth={260}
              cardPositionHorizontal="TOP"
              mediaHeight={100}
              mediaSettings={{ align: "center", imageFit: "cover" }}
              timelinePointDimension={16}
              timelinePointShape="circle"
              activeItemIndex={activeItemIndex}
              focusActiveItemOnLoad
              onItemSelected={handleItemSelected}
              highlightCardsOnHover
              enableQuickJump
              enableLayoutSwitch
              useReadMore={false}
              theme={{
                primary: "#2563eb",
                secondary: "#f59e0b",
                cardBgColor: "#ffffff",
                cardTitleColor: "#111827",
                cardSubtitleColor: "#6b7280",
                cardDetailsColor: "#374151",
                titleColor: "#6b7280",
                titleColorActive: "#2563eb",
                textColor: "#1f2937",
                iconBackgroundColor: "#eff6ff",
                toolbarBgColor: "#f3f4f6",
                toolbarBtnBgColor: "#ffffff",
                toolbarTextColor: "#374151",
              }}
              fontSizes={{
                cardTitle: "0.75rem",
                cardSubtitle: "0.65rem",
                cardText: "0.7rem",
                title: "0.65rem",
              }}
            />
          </div>
        )}
      </div>

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
    </div>
  );
}
