// [Flow: Step 1 (job.ediscovery_graphs/status + preview source_files 수신)
//       -> Step 2 (노드를 date 유무로 분리: date가 있으면 Chrono, 없으면 우측 패널)
//       -> Step 3 (React Chrono 3.x vertical 모드에 custom content(children) 주입)
//       -> Step 4 (카드 클릭으로 선택/포커스, 수정 버튼으로 편집/삭제, 상단 카드 추가 메뉴)
//       -> Step 5 (변경 시 1초 debounce 후 PUT /ediscovery/graph 자동 저장)]
// e-Discovery GraphRAG 결과를 중앙 수직 타임라인 + 우측 페이지 기반 노드 패널로 시각화.
// 기존 양측 주장/증거 카드, 하단 수평 스트립, 상단 재분석 버튼은 모두 제거하고 Chrono 기본 UI를 사용한다.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, AlertCircle, Network, FileText, Plus, Trash2, X, Check, Pencil } from "lucide-react";
import { Chrono } from "react-chrono";
import "react-chrono/dist/style.css";
import { api } from "../../api.js";

/** 폴링 타임아웃 — 10분. */
const POLL_TIMEOUT_MS = 600000;

/** entity 코드 → i18n 키 매핑. */
const SWIMLANE_LABEL_KEYS = {
  plaintiff: "ediscoverySwimlanePlaintiff",
  defendant: "ediscoverySwimlaneDefendant",
  third_party: "ediscoverySwimlaneThirdParty",
  issue: "ediscoverySwimlaneIssue",
};

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
 * page 번호에 맞는 sourceFile을 찾는다.
 * 정확히 일치하는 page_num이 없으면 PDF/문서 타입을 우선으로 폴백한다.
 *
 * @param {Object} node - e-Discovery graph 노드
 * @param {Array<Object>} sourceFiles - preview API에서 받은 source_files 배열
 * @returns {Object|null} sourceFile 객체 또는 null
 */
function findSourceFile(node, sourceFiles) {
  if (!sourceFiles?.length) return null;
  const page = getNodePage(node);
  const exact = sourceFiles.find((f) => f.page_num === page);
  if (exact) return exact;
  const docFallback = sourceFiles.find((f) => ["pdf", "docx", "hwp"].includes(f.type));
  if (docFallback) return docFallback;
  return sourceFiles[0] || null;
}

/**
 * 노드와 sourceFiles에 맞는 React Chrono media 객체를 생성한다.
 * 이미지/비디오는 직접 URL을 사용하고, PDF/오디오는 정적 썸네일을 사용한다.
 *
 * @param {Object} node - e-Discovery graph 노드
 * @param {Array<Object>} sourceFiles - preview API에서 받은 source_files 배열
 * @returns {Object|null} React Chrono media 객체 또는 null
 */
function buildMedia(node, sourceFiles) {
  const sourceFile = findSourceFile(node, sourceFiles);
  if (!sourceFile) return null;
  const { type, preview_url, url, name } = sourceFile;
  // HTTPS 사이트에서 HTTP 리소스를 로드하면 Mixed Content 에러가 발생하므로 scheme를 강제 변환한다.
  const mediaUrl = (preview_url || url || "").replace(/^http:/, "https:");
  if (!mediaUrl) return null;

  if (type === "image") {
    return { type: "IMAGE", source: { url: mediaUrl }, name: name || "image" };
  }
  if (type === "video") {
    return { type: "VIDEO", source: { url: mediaUrl, type: "mp4" }, name: name || "video" };
  }
  if (type === "pdf" || type === "docx" || type === "hwp") {
    return { type: "IMAGE", source: { url: "/assets/pdf-thumbnail.svg" }, name: name || "PDF" };
  }
  if (type === "audio") {
    return { type: "IMAGE", source: { url: "/assets/audio-thumbnail.svg" }, name: name || "audio" };
  }
  return null;
}

/**
 * 단일 e-Discovery 노드를 React Chrono TimelineItemModel로 변환한다.
 * Chrono 기본 카드 스타일을 사용하며, media prop이 있으면 포함한다.
 *
 * @param {Object} node - e-Discovery graph 노드
 * @param {Array<Object>} sourceFiles - preview API에서 받은 source_files 배열
 * @param {Function} t - i18n translate 함수
 * @returns {Object} React Chrono item 객체
 */
export function buildChronoItem(node, sourceFiles, t, isEditing = false) {
  const data = node.data || {};
  const label = data.label || node.id;
  const page = getNodePage(node);
  const title = data.date ? String(data.date) : `p.${page}`;

  const item = {
    id: node.id,
    title,
    // [Flow: cardTitle은 Chrono 내부 W(hash)에만 참여해서 내용/편집 상태 변경 시 remount를 유도.
    //        실제 시각적 표시는 CSS로 숨기고 아래 CardEditor custom content가 대체한다.]
    cardTitle: `${node.id}${isEditing ? ":edit" : ""}`,
    cardSubtitle: null,
    cardDetailedText: null,
    node,
  };

  const media = buildMedia(node, sourceFiles);
  if (media) item.media = media;
  return item;
}

/**
 * EdiscoveryTimelinePanel — e-Discovery 결과를 중앙 수직 타임라인 + 우측 페이지 패널로 렌더링.
 *
 * @param {Object} props
 * @param {string} props.jobId - 현재 Job ID
 * @param {Object} props.job - Job 객체 (ediscovery_* 필드 포함)
 * @param {Array<Object>} [props.sourceFiles] - 외부에서 이미 로드된 preview source_files. 미전달 시 내부에서 로드한다.
 * @param {Function} [props.onNodeClick] - 노드/아이템 클릭 시 호출될 콜백 (node) => void
 */
export default function EdiscoveryTimelinePanel({ jobId, job, sourceFiles: externalSourceFiles, onNodeClick }) {
  const { t } = useTranslation();

  const [metrics, setMetrics] = useState({
    total_docs: 0,
    total_chunks: 0,
    processed_chunks: 0,
    threshold: 0,
    anomalies_detected: 0,
    stage: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [context, setContext] = useState(job?.ediscovery_context || "");
  const [sourceFiles, setSourceFiles] = useState(externalSourceFiles || []);
  const [draftNodes, setDraftNodes] = useState([]);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [editingNodeId, setEditingNodeId] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  const pollRef = useRef(null);
  const pollStartRef = useRef(0);
  const saveTimeoutRef = useRef(null);
  const draftNodesRef = useRef(draftNodes);

  useEffect(() => {
    draftNodesRef.current = draftNodes;
  }, [draftNodes]);

  useEffect(() => {
    setContext(job?.ediscovery_context || "");
  }, [job?.ediscovery_context]);

  useEffect(() => {
    const graph = job?.ediscovery_graphs;
    const nodes = graph?.nodes || [];
    setDraftNodes(nodes);
    if (!nodes.length) {
      setMetrics({ total_docs: 0, total_chunks: 0, processed_chunks: 0, threshold: 0, anomalies_detected: 0, stage: "" });
      return;
    }
    setMetrics(job?.ediscovery_metrics || { total_docs: 0, total_chunks: 0, processed_chunks: 0, threshold: 0, anomalies_detected: 0, stage: "" });
  }, [job?.ediscovery_graphs, job?.ediscovery_metrics]);

  useEffect(() => {
    if (externalSourceFiles) {
      setSourceFiles(externalSourceFiles);
      return;
    }
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
  }, [externalSourceFiles, jobId]);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    };
  }, []);

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
          setMetrics(status.ediscovery_metrics || { total_docs: 0, total_chunks: 0, processed_chunks: 0, threshold: 0, anomalies_detected: 0, stage: "" });
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

  useEffect(() => {
    if (job?.ediscovery_status === "done" && job?.ediscovery_graphs?.nodes?.length > 0) {
      setMetrics(job.ediscovery_metrics || { total_docs: 0, total_chunks: 0, processed_chunks: 0, threshold: 0, anomalies_detected: 0, stage: "" });
      return;
    }
    if (job?.ediscovery_status === "processing") {
      startPolling();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.ediscovery_status, job?.ediscovery_graphs, job?.ediscovery_metrics, jobId]);

  /**
   * [Flow: Step 1 (metrics.processed_chunks / metrics.total_chunks) -> Step 2 (0~100%로 clamp)
   *       -> Step 3 (정수로 반올림)]
   */
  const extractionProgress = useMemo(() => {
    const total = typeof metrics.total_chunks === "number" ? metrics.total_chunks : 0;
    const processed = typeof metrics.processed_chunks === "number" ? metrics.processed_chunks : 0;
    if (total <= 0) return 0;
    return Math.min(100, Math.max(0, Math.round((processed / total) * 100)));
  }, [metrics.total_chunks, metrics.processed_chunks]);

  /**
   * [Flow: Step 1 (metrics.stage 확인) -> Step 2 (i18n 키 매핑) -> Step 3 (번역 반환)]
   */
  const stageLabel = useMemo(() => {
    const stageKeyMap = {
      preparing: "ediscoveryStagePreparing",
      extracting: "ediscoveryStageExtracting",
      analyzing: "ediscoveryStageAnalyzing",
      assembling: "ediscoveryStageAssembling",
    };
    const key = stageKeyMap[metrics.stage] || "ediscoveryStagePreparing";
    return t(`page:result.${key}`);
  }, [metrics.stage, t]);

  const handleSelectNode = useCallback((nodeId, shouldOpenPopup = true) => {
    setSelectedNodeId(nodeId);
    if (!shouldOpenPopup) return;
    // [Flow: Step 1 (선택한 nodeId로 최신 draftNodes에서 노드 조회)
    //       -> Step 2 (존재하면 상위 onNodeClick 콜백 호출)
    //       -> Step 3 (JobResultPage의 SourcePanel 스크롤/팝업 연동)]
    const node = draftNodesRef.current.find((n) => n.id === nodeId);
    if (node) onNodeClick?.(node);
  }, [onNodeClick]);

  const handleStartEdit = useCallback((nodeId) => {
    setEditingNodeId(nodeId);
    setSelectedNodeId(nodeId);
  }, []);

  const handleFinishEdit = useCallback(() => {
    setEditingNodeId(null);
  }, []);

  const handleUpdateNode = useCallback((nodeId, updates) => {
    setDraftNodes((prev) =>
      prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...updates } } : n))
    );
  }, []);

  const handleDeleteNode = useCallback((nodeId) => {
    setDraftNodes((prev) => prev.filter((n) => n.id !== nodeId));
    setSelectedNodeId((prev) => (prev === nodeId ? null : prev));
    setEditingNodeId((prev) => (prev === nodeId ? null : prev));
  }, []);

  const handleCreateNode = useCallback(() => {
    const newId = `manual-${Date.now()}`;
    const today = new Date().toISOString().split("T")[0];
    const newNode = {
      id: newId,
      type: "event",
      data: {
        label: t("page:result.ediscoveryNewCardLabel"),
        summary: "",
        date: today,
        page: 1,
        entity: "third_party",
        confidence: 0.8,
      },
    };
    setDraftNodes((prev) => [...prev, newNode]);
    setSelectedNodeId(newId);
    setEditingNodeId(newId);
  }, [t]);

  const saveGraph = useCallback(async () => {
    if (!jobId) return;
    setIsSaving(true);
    setSaveError("");
    try {
      const nodeIds = new Set(draftNodes.map((n) => n.id));
      const edges = (job?.ediscovery_graphs?.edges || []).filter(
        (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
      );
      await api.saveEdiscoveryGraph(jobId, { nodes: draftNodes, edges });
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSaving(false);
    }
  }, [jobId, draftNodes, job?.ediscovery_graphs?.edges]);

  useEffect(() => {
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    if (!jobId) return;
    saveTimeoutRef.current = setTimeout(() => {
      saveGraph();
    }, 1000);
    return () => {
      if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current);
    };
  }, [jobId, draftNodes, saveGraph]);

  const nonSwimlaneNodes = useMemo(() => {
    return draftNodes.filter((n) => n.type !== "swimlane");
  }, [draftNodes]);

  /**
   * [Flow: Step 1 (date가 있는 노드 필터링) -> Step 2 (날짜/페이지 정렬)
   *       -> Step 3 (React Chrono items로 변환, media prop 포함)]
   */
  const chronoItems = useMemo(() => {
    const datedNodes = nonSwimlaneNodes.filter((n) => n.data?.date);
    const sorted = [...datedNodes].sort((a, b) => {
      const aDate = a.data?.date ? new Date(a.data.date).getTime() : NaN;
      const bDate = b.data?.date ? new Date(b.data.date).getTime() : NaN;
      if (!Number.isNaN(aDate) && !Number.isNaN(bDate) && aDate !== bDate) return aDate - bDate;
      const aPage = typeof a.data?.page === "number" ? a.data.page : Infinity;
      const bPage = typeof b.data?.page === "number" ? b.data.page : Infinity;
      if (aPage !== bPage) return aPage - bPage;
      return (a.id || "").localeCompare(b.id || "");
    });
    return sorted.map((node) => buildChronoItem(node, sourceFiles, t, editingNodeId === node.id));
  }, [nonSwimlaneNodes, sourceFiles, t, editingNodeId]);

  /**
   * [Flow: Step 1 (date가 없는 노드 필터링) -> Step 2 (페이지순 정렬)
   *       -> Step 3 (React Chrono item 형태로 변환)]
   */
  const pageItems = useMemo(() => {
    const undatedNodes = nonSwimlaneNodes.filter((n) => !n.data?.date);
    const sorted = [...undatedNodes].sort((a, b) => {
      const aPage = typeof a.data?.page === "number" ? a.data.page : Infinity;
      const bPage = typeof b.data?.page === "number" ? b.data.page : Infinity;
      if (aPage !== bPage) return aPage - bPage;
      return (a.id || "").localeCompare(b.id || "");
    });
    return sorted.map((node) => buildChronoItem(node, sourceFiles, t, editingNodeId === node.id));
  }, [nonSwimlaneNodes, sourceFiles, t, editingNodeId]);

  const isEmpty = !loading && chronoItems.length === 0 && pageItems.length === 0 && !error && job?.ediscovery_status === "done";

  return (
    <div
      className="h-full w-full flex flex-col relative"
      data-oid="ediscovery-timeline-panel"
    >
      <div className="flex-shrink-0 px-3 py-2 border-b border-outline-variant bg-surface-container-low flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {isSaving && (
            <>
              <Loader2 size={14} className="animate-spin text-primary" />
              <span className="text-xs text-on-surface-variant">{t("page:result.ediscoverySaving")}</span>
            </>
          )}
          {saveError && <span className="text-xs text-error truncate">{saveError}</span>}
        </div>
        <button
          type="button"
          onClick={handleCreateNode}
          className="flex-shrink-0 flex items-center gap-1 px-2 py-1 bg-primary text-white text-xs font-medium rounded hover:opacity-90 transition-opacity"
        >
          <Plus size={14} />
          {t("page:result.ediscoveryAddCard")}
        </button>
      </div>
      <div className="flex-1 min-h-0 flex relative overflow-hidden">
        <div className="flex-1 min-h-0 ediscovery-chrono-container">
        {chronoItems.length > 0 && (
          <Chrono
            items={chronoItems}
            mode="vertical"
            allowDynamicUpdate
            layout={{
              cardWidth: 480,
              pointSize: 16,
              lineWidth: 2,
              timelineHeight: "100%",
              responsive: { enabled: true, breakpoint: 768 },
            }}
            content={{
              readMore: false,
              alignment: { horizontal: "left", vertical: "top" },
            }}
            display={{
              borderless: false,
              pointShape: "circle",
              scrollable: { scrollbar: true },
              toolbar: {
                enabled: true,
                position: "top",
                sticky: true,
                search: { enabled: true },
              },
            }}
            interaction={{
              keyboardNavigation: true,
              pointClick: false,
              autoScroll: true,
              focusOnLoad: false,
              disabled: true,
            }}
            media={{
              height: 200,
              align: "center",
              fit: "cover",
            }}
            theme={{
              primary: "#2563eb",
              secondary: "#f59e0b",
              cardBgColor: "#ffffff",
              cardTitleColor: "#111827",
              cardSubtitleColor: "#6b7280",
              cardDetailsColor: "#374151",
              titleColor: "#6b7280",
            }}
            style={{
              classNames: {
                card: "ediscovery-timeline-card",
                cardTitle: "ediscovery-timeline-card-title",
                cardSubTitle: "ediscovery-timeline-card-subtitle",
                cardText: "ediscovery-timeline-card-text",
                title: "ediscovery-timeline-title",
                timelinePoint: "ediscovery-timeline-point",
                timelineTrack: "ediscovery-timeline-track",
              },
            }}
          >
            {chronoItems.map((item) => (
              <CardEditor
                key={item.id}
                item={item}
                isEditing={editingNodeId === item.node.id}
                isSelected={false}
                onSelect={handleSelectNode}
                onStartEdit={handleStartEdit}
                onFinishEdit={handleFinishEdit}
                onUpdate={handleUpdateNode}
                onDelete={handleDeleteNode}
                t={t}
              />
            ))}
          </Chrono>
        )}
      </div>

      {/* date가 없는 노드 우측 패널 */}
      {pageItems.length > 0 && (
        <div className="w-80 flex-shrink-0 border-l border-outline-variant bg-surface-container-lowest h-full overflow-y-auto p-3 flex flex-col gap-3" data-oid="ediscovery-page-panel">
          <h3 className="text-sm font-medium text-on-surface flex items-center gap-2">
            <FileText size={16} />
            {t("page:result.pageBasedNodes")}
          </h3>
          <div className="flex flex-col gap-3">
            {pageItems.map((item) => (
              <CardEditor
                key={item.id}
                item={item}
                isEditing={editingNodeId === item.node.id}
                isSelected={selectedNodeId === item.node.id}
                onSelect={handleSelectNode}
                onStartEdit={handleStartEdit}
                onFinishEdit={handleFinishEdit}
                onUpdate={handleUpdateNode}
                onDelete={handleDeleteNode}
                t={t}
                variant="compact"
              />
            ))}
          </div>
        </div>
      )}
      </div>

      {/* 로딩 오버레이 + 진행률 */}
      {loading && (
        <div className="absolute inset-0 z-40 bg-surface/80 flex flex-col items-center justify-center gap-4 px-6" data-oid="ediscovery-loading">
          <Loader2 size={28} className="animate-spin text-primary" />
          <div className="w-full max-w-xs flex flex-col gap-2">
            <div className="flex items-center justify-between text-xs text-on-surface-variant">
              <span>{stageLabel}</span>
              <span>{extractionProgress}%</span>
            </div>
            <div className="w-full h-2 bg-surface-container-high rounded-full overflow-hidden">
              <div
                className="h-full bg-primary transition-all duration-300 ease-out"
                style={{ width: `${extractionProgress}%` }}
                data-oid="ediscovery-progress-bar"
              />
            </div>
            <p className="text-xs text-on-surface-variant text-center">
              {t("page:result.ediscoveryProgress", {
                processed: metrics.processed_chunks || 0,
                total: metrics.total_chunks || metrics.total_docs || 0,
              })}
            </p>
          </div>
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
        </div>
      )}

      {/* 빈 상태 안내 */}
      {isEmpty && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center text-on-surface-variant gap-3" data-oid="ediscovery-empty">
          <Network size={40} className="text-primary/40" />
          <p className="text-sm text-center max-w-xs leading-relaxed">{t("page:result.ediscoveryEmpty")}</p>
        </div>
      )}
    </div>
  );
}

/**
 * CardEditor — 타임라인 카드를 읽기/수정 모드로 전환하는 UI.
 *
 * [Flow: Step 1 (item.node.data로 로컬 draft 상태 초기화)
 *       -> Step 2 (편집 중에는 draft를 즉시 갱신하고 상위에 onUpdate 전달)
 *       -> Step 3 (편집 완료/취소 시 onFinishEdit/onDelete 콜백 호출)
 *       -> Step 4 (읽기 모드에서는 draft를 렌더링, 외부 데이터 변경 시 동기화)]
 *
 * @param {Object} props
 * @param {Object} props.item - React Chrono item 객체 (node 포함)
 * @param {boolean} props.isEditing - 현재 편집 중인지 여부 (부모가 제어)
 * @param {boolean} props.isSelected - 현재 선택(포커스) 상태
 * @param {Function} props.onSelect - 카드 클릭 시 선택 콜백 (nodeId, shouldOpenPopup) => void
 * @param {Function} props.onStartEdit - 편집 시작 콜백 (nodeId) => void
 * @param {Function} props.onFinishEdit - 편집 완료 콜백 () => void
 * @param {Function} props.onUpdate - 노드 data 수정 콜백 (nodeId, dataUpdates) => void
 * @param {Function} props.onDelete - 노드 삭제 콜백 (nodeId) => void
 * @param {Function} props.t - i18n translate 함수
 * @param {string} [props.variant="default"] - "default"(Chrono 카드) | "compact"(우측 패널 카드)
 */
function CardEditor({
  item,
  isEditing,
  isSelected,
  onSelect,
  onStartEdit,
  onFinishEdit,
  onUpdate,
  onDelete,
  t,
  variant = "default",
}) {
  const initialData = useMemo(() => ({ ...(item.node.data || {}) }), [item.node.id]);
  const [draft, setDraft] = useState(initialData);
  const lastSyncedDataRef = useRef(initialData);
  const isCompact = variant === "compact";

  const VALID_ENTITIES = ["plaintiff", "defendant", "third_party", "issue"];
  const rawEntity = draft.entity || (item.node.type === "evidence" ? "third_party" : item.node.type);
  const entity = VALID_ENTITIES.includes(rawEntity) ? rawEntity : "third_party";

  /**
   * [Flow: Step 1 (item.node.data가 실제로 변경되었는지 필드 비교)
   *       -> Step 2 (읽기 모드일 때만 로컬 draft 동기화)
   *       -> Step 3 (편집 중이면 사용자 입력 보존을 위해 동기화 중단)]
   */
  useEffect(() => {
    if (isEditing) return;
    const current = item.node.data || {};
    const last = lastSyncedDataRef.current;
    const changed =
      current.label !== last.label ||
      current.summary !== last.summary ||
      current.date !== last.date ||
      current.page !== last.page ||
      current.entity !== last.entity;
    if (!changed) return;
    lastSyncedDataRef.current = { ...current };
    setDraft({ ...current });
  }, [item, isEditing]);

  /**
   * [Flow: Step 1 (필드 변경) -> Step 2 (로컬 draft 갱신)
   *       -> Step 3 (상위 EdiscoveryTimelinePanel에 즉시 반영)]
   */
  const updateField = useCallback(
    (field, value) => {
      setDraft((prev) => {
        const next = { ...prev, [field]: value };
        onUpdate(item.node.id, { [field]: value });
        return next;
      });
    },
    [item.node.id, onUpdate]
  );

  const handleStartEdit = (e) => {
    e.stopPropagation();
    onStartEdit(item.node.id);
  };

  const handleDone = (e) => {
    e.stopPropagation();
    onFinishEdit();
  };

  const handleDelete = (e) => {
    e.stopPropagation();
    onDelete(item.node.id);
  };

  const ringClass = isSelected || isEditing ? "ring-2 ring-primary bg-primary/5 rounded-lg" : "hover:bg-surface-container-high rounded-lg";

  // [Flow: 편집 모드 -> label/summary/date/entity 입력 + 삭제/완료 버튼]
  if (isEditing) {
    return (
      <div
        className={`flex flex-col transition-all ${ringClass} ${isCompact ? "p-2 gap-2" : "min-h-[160px] p-1 gap-3"}`}
        onClick={(e) => {
          e.stopPropagation();
          onSelect?.(item.node.id, false);
        }}
        data-oid={`card-editor-edit-${item.node.id}`}
      >
        <div className="flex flex-col gap-2">
          <div className="flex items-start justify-between gap-1">
            <input
              autoFocus
              value={draft.label || ""}
              onChange={(e) => updateField("label", e.target.value)}
              className={`w-full font-medium text-on-surface bg-transparent border-b border-outline-variant focus:border-primary focus:outline-none px-1 py-0.5 ${
                isCompact ? "text-xs" : "text-sm"
              }`}
              placeholder={t("page:result.ediscoveryLabelPlaceholder")}
              onClick={(e) => e.stopPropagation()}
            />
            <button
              type="button"
              onClick={handleDelete}
              className="p-1 text-error hover:bg-error/10 rounded flex-shrink-0"
              title={t("page:result.ediscoveryDeleteCard")}
            >
              <Trash2 size={14} />
            </button>
          </div>
          <textarea
            value={draft.summary || ""}
            onChange={(e) => updateField("summary", e.target.value)}
            rows={isCompact ? 2 : 3}
            className={`w-full text-on-surface-variant bg-transparent border border-outline-variant rounded p-1.5 focus:border-primary focus:outline-none resize-none ${
              isCompact ? "text-xs" : "text-sm"
            }`}
            placeholder={t("page:result.ediscoverySummaryPlaceholder")}
            onClick={(e) => e.stopPropagation()}
          />
          <div className="flex flex-wrap gap-2">
            <input
              type="date"
              value={draft.date || ""}
              onChange={(e) => updateField("date", e.target.value)}
              className="text-xs bg-surface-container-high rounded px-2 py-1 border border-outline-variant focus:border-primary focus:outline-none"
              onClick={(e) => e.stopPropagation()}
            />
            <select
              value={entity}
              onChange={(e) => updateField("entity", e.target.value)}
              className="text-xs bg-surface-container-high rounded px-2 py-1 border border-outline-variant focus:border-primary focus:outline-none"
              onClick={(e) => e.stopPropagation()}
            >
              <option value="plaintiff">{t("page:result.ediscoverySwimlanePlaintiff")}</option>
              <option value="defendant">{t("page:result.ediscoverySwimlaneDefendant")}</option>
              <option value="third_party">{t("page:result.ediscoverySwimlaneThirdParty")}</option>
              <option value="issue">{t("page:result.ediscoverySwimlaneIssue")}</option>
            </select>
          </div>
        </div>
        <div className="flex justify-end pt-2">
          <button
            type="button"
            onClick={handleDone}
            className="flex items-center gap-1 text-xs font-medium text-primary hover:bg-primary/10 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary/50"
          >
            <Check size={14} />
            {t("common:status.done")}
          </button>
        </div>
      </div>
    );
  }

  // [Flow: 읽기 모드 -> label 노출 + summary/date/entity badge + 수정 버튼]
  return (
    <div
      className={`flex flex-col justify-between transition-all ${ringClass} ${
        isCompact ? "p-2 gap-2" : "min-h-[160px] p-1 gap-3"
      }`}
      onClick={() => onSelect(item.node.id, true)}
      data-oid={`card-editor-read-${item.node.id}`}
    >
      <div className="flex flex-col gap-2">
        <div className="flex items-start justify-between gap-1">
          <div
            className={`w-full font-medium text-on-surface px-1 py-0.5 ${
              isCompact ? "text-xs" : "text-sm"
            }`}
          >
            {draft.label || item.id}
          </div>
        </div>
        {!isCompact && draft.summary && (
          <div className={`text-on-surface-variant line-clamp-2 ${isCompact ? "text-xs" : "text-sm"}`}>
            {draft.summary}
          </div>
        )}
        {!isCompact && (
          <div className="flex flex-wrap gap-2 text-xs">
            {draft.date && (
              <span className="px-2 py-1 rounded bg-surface-container-high text-on-surface">
                {draft.date}
              </span>
            )}
            <span
              className={`px-2 py-1 rounded ${
                entity === "plaintiff"
                  ? "bg-blue-100 text-blue-800"
                  : entity === "defendant"
                  ? "bg-red-100 text-red-800"
                  : entity === "issue"
                  ? "bg-amber-100 text-amber-800"
                  : "bg-surface-container-high text-on-surface"
              }`}
            >
              {t(
                `page:result.${
                  SWIMLANE_LABEL_KEYS[entity] || `ediscoverySwimlane${entity.charAt(0).toUpperCase() + entity.slice(1)}`
                }`
              )}
            </span>
          </div>
        )}
      </div>
      <div className="flex justify-end pt-2">
        <button
          type="button"
          onClick={handleStartEdit}
          className="flex items-center gap-1 text-xs font-medium text-primary hover:bg-primary/10 rounded px-2 py-1 focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          <Pencil size={14} />
          {t("page:result.ediscoveryEditCard")}
        </button>
      </div>
    </div>
  );
}
