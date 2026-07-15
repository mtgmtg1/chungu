// [Flow: Step 1 (job.ediscovery_graphs/status + preview source_files 수신)
//       -> Step 2 (노드를 date 유무로 분리: date가 있으면 Chrono, 없으면 우측 패널)
//       -> Step 3 (React Chrono 3.x vertical 모드에 custom content(children) 주입)
//       -> Step 4 (카드 하단 오른쪽 'read more' 버튼 클릭 시에만 미리보기/스크롤 연동)]
// e-Discovery GraphRAG 결과를 중앙 수직 타임라인 + 우측 페이지 기반 노드 패널로 시각화.
// 기존 양측 주장/증거 카드, 하단 수평 스트립, 상단 재분석 버튼은 모두 제거하고 Chrono 기본 UI를 사용한다.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, AlertCircle, Network, FileText } from "lucide-react";
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
export function buildChronoItem(node, sourceFiles, t) {
  const data = node.data || {};
  const entity = data.entity || (node.type === "evidence" ? "third_party" : node.type);
  const label = data.label || node.id;
  const page = getNodePage(node);
  const title = data.date ? String(data.date) : `p.${page}`;
  const subtitleKey =
    SWIMLANE_LABEL_KEYS[entity] || `ediscoverySwimlane${entity.charAt(0).toUpperCase() + entity.slice(1)}`;
  const subtitle = t(`page:result.${subtitleKey}`);
  const summary = data.summary || label;

  const item = {
    id: node.id,
    title,
    cardTitle: label,
    cardSubtitle: subtitle,
    cardDetailedText: summary,
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
 * @param {Function} [props.onPreview] - 노드/아이템 클릭 시 미리보기 패널을 띄우기 위한 콜백 (node) => void
 */
export default function EdiscoveryTimelinePanel({ jobId, job, sourceFiles: externalSourceFiles, onNodeClick, onPreview }) {
  const { t } = useTranslation();

  const [metrics, setMetrics] = useState({
    total_docs: 0,
    processed_chunks: 0,
    threshold: 0,
    anomalies_detected: 0,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [context, setContext] = useState(job?.ediscovery_context || "");
  const [rawNodes, setRawNodes] = useState([]);
  const [sourceFiles, setSourceFiles] = useState(externalSourceFiles || []);

  const pollRef = useRef(null);
  const pollStartRef = useRef(0);

  useEffect(() => {
    setContext(job?.ediscovery_context || "");
  }, [job?.ediscovery_context]);

  useEffect(() => {
    const graph = job?.ediscovery_graphs;
    if (!graph?.nodes?.length) {
      setRawNodes([]);
      setMetrics({ total_docs: 0, processed_chunks: 0, threshold: 0, anomalies_detected: 0 });
      return;
    }
    setRawNodes(graph.nodes);
    setMetrics(job?.ediscovery_metrics || { total_docs: 0, processed_chunks: 0, threshold: 0, anomalies_detected: 0 });
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

  useEffect(() => {
    if (job?.ediscovery_status === "done" && job?.ediscovery_graphs?.nodes?.length > 0) {
      setMetrics(job.ediscovery_metrics || { total_docs: 0, processed_chunks: 0, threshold: 0, anomalies_detected: 0 });
      return;
    }
    if (job?.ediscovery_status === "processing") {
      startPolling();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.ediscovery_status, job?.ediscovery_graphs, job?.ediscovery_metrics, jobId]);

  const handleNodePreview = useCallback((node) => {
    onPreview?.(node);
    onNodeClick?.(node);
  }, [onPreview, onNodeClick]);

  const nonSwimlaneNodes = useMemo(() => {
    return rawNodes.filter((n) => n.type !== "swimlane");
  }, [rawNodes]);

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
    return sorted.map((node) => buildChronoItem(node, sourceFiles, t));
  }, [nonSwimlaneNodes, sourceFiles, t]);

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
    return sorted.map((node) => buildChronoItem(node, sourceFiles, t));
  }, [nonSwimlaneNodes, sourceFiles, t]);

  const isEmpty = !loading && chronoItems.length === 0 && pageItems.length === 0 && !error && job?.ediscovery_status === "done";

  return (
    <div
      className="h-full w-full flex relative"
      data-oid="ediscovery-timeline-panel"
    >
      <div className="flex-1 min-h-0 ediscovery-chrono-container">
        {chronoItems.length > 0 ? (
          <Chrono
            items={chronoItems}
            mode="vertical"
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
            classNames={{
              card: "ediscovery-timeline-card",
              cardTitle: "ediscovery-timeline-card-title",
              cardSubTitle: "ediscovery-timeline-card-subtitle",
              cardText: "ediscovery-timeline-card-text",
              title: "ediscovery-timeline-title",
              timelinePoint: "ediscovery-timeline-point",
              timelineTrack: "ediscovery-timeline-track",
            }}
          >
            {chronoItems.map((item) => (
              <div key={item.id} className="relative flex flex-col gap-2 pb-8">
                <p className="text-sm text-on-surface-variant leading-relaxed">
                  {item.cardDetailedText}
                </p>
                <div className="absolute bottom-2 right-0">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleNodePreview(item.node);
                    }}
                    className="text-xs font-medium text-primary hover:underline focus:outline-none focus:ring-2 focus:ring-primary/50 rounded px-1 py-0.5"
                  >
                    {t("page:result.readMore")}
                  </button>
                </div>
              </div>
            ))}
          </Chrono>
        ) : (
          <div className="h-full w-full flex items-center justify-center text-on-surface-variant gap-2" data-oid="ediscovery-timeline-empty">
            {loading ? <Loader2 size={24} className="animate-spin text-primary" /> : <Network size={24} className="text-primary/40" />}
            <span className="text-sm">
              {loading ? t("page:result.ediscoveryAnalyzing") : t("page:result.ediscoveryEmpty")}
            </span>
          </div>
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
              <div
                key={item.id}
                className="bg-surface border border-outline-variant rounded-lg p-3 shadow-sm flex flex-col gap-2"
              >
                <div className="text-xs text-primary font-medium">{item.title}</div>
                <div className="text-sm font-medium text-on-surface">{item.cardTitle}</div>
                <div className="text-xs text-on-surface-variant">{item.cardSubtitle}</div>
                <p className="text-xs text-on-surface-variant line-clamp-3">{item.cardDetailedText}</p>
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={() => handleNodePreview(item.node)}
                    className="text-xs font-medium text-primary hover:underline focus:outline-none focus:ring-2 focus:ring-primary/50 rounded px-1 py-0.5"
                  >
                    {t("page:result.readMore")}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

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
        </div>
      )}

      {/* 빈 상태 안내 */}
      {isEmpty && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center text-on-surface-variant gap-3" data-oid="ediscovery-empty">
          <Network size={40} className="text-primary/40" />
          <p className="text-sm text-center max-w-xs">{t("page:result.ediscoveryEmpty")}</p>
        </div>
      )}
    </div>
  );
}
