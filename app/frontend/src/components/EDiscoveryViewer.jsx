// [Flow: Step 1 (Job의 e-Discovery 상태/그래프 로드) -> Step 2 (슬라이더 파라미터 설정)
//       -> Step 3 (분석 버튼 클릭 시 FastAPI e-Discovery 추출 API 호출) -> Step 4 (응답 그래프를 elkjs로 자동 배치)
//       -> Step 5 (React Flow 렌더링 — 스윔레인 타임라인 + 모순 엣지) -> Step 6 (노드 클릭 시 점진적 탐색 오버레이 + SourcePanel PDF 스크롤)
//       -> Step 7 (쟁점 필터 토글 — 미선택 쟁점 노드 디밍)]
// 수천 장 법률 문서의 e-Discovery GraphRAG 결과를 React Flow로 시각화.
// 신규 스키마(swimlane + parentId + anomaly 엣지)와 구 스키마(평면)를 모두 렌더링.
// 노드 타입별 Tailwind 스타일, 상단 파라미터 슬라이더, 쟁점 필터, 점진적 탐색 패널을 제공.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  useNodesState,
  useEdgesState,
  useReactFlow,
  Handle,
  Position,
} from "@xyflow/react";
import { Network, Loader2, RefreshCw, AlertCircle, Play, X, Filter, FileText, ChevronRight, Puzzle } from "lucide-react";
import { calculateElkLayout, calculateElkSwimlaneLayout } from "../utils/elkLayout";
import AnomalyEdge from "./flow/AnomalyEdge.jsx";
import { api } from "../api.js";
import EvidenceMapperPanel from "./mapper/EvidenceMapperPanel.jsx";

/* ============================================================
 * 커스텀 노드 컴포넌트
 * ========================================================== */

/**
 * 디밍 클래스 헬퍼 — 쟁점 필터에서 미선택된 노드에 적용.
 * hidden 처리 대신 opacity-20 grayscale로 캔버스 배경에 희미하게 물러나게 한다.
 */
function dimClass(data) {
  return data?.dimmed ? "opacity-20 grayscale transition-opacity duration-300" : "transition-opacity duration-300";
}

/**
 * e-Discovery 스윔레인 노드 — 사건 주체(원고/피고/제3자/쟁점)의 최상위 컨테이너.
 * 넓은 배경 박스로 자식 노드들을 가로축(시간)으로 감싼다.
 * entity별 색상 코딩으로 주체를 직관적으로 구분.
 */
function SwimlaneNode({ data, selected }) {
  const entityColors = {
    plaintiff: "bg-blue-50 border-blue-400 text-blue-700",
    defendant: "bg-amber-50 border-amber-400 text-amber-700",
    third_party: "bg-purple-50 border-purple-400 text-purple-700",
    issue: "bg-red-50 border-red-400 text-red-700",
  };
  const colorClass = entityColors[data.entity] || "bg-surface-container-low border-outline-variant text-on-surface";
  return (
    <div
      className={`rounded-xl border-2 border-dashed ${colorClass} ${dimClass(data)} ${
        selected ? "ring-2 ring-primary/30" : ""
      }`}
      style={{ width: "100%", height: "100%" }}
    >
      <div className="flex items-center gap-2 px-4 py-2 border-b border-current/20">
        <span className="text-sm font-bold tracking-wide">{data.label}</span>
      </div>
    </div>
  );
}

/**
 * e-Discovery 이슈 노드 — 쟁점(issue)을 표현.
 * 빨간색 계열의 Tailwind 스타일로 시각적 구분.
 */
function IssueNode({ data, selected }) {
  return (
    <div
      className={`rounded-lg border-2 shadow-sm px-3 py-2 ${dimClass(data)} ${
        selected ? "ring-2 ring-red-400/40" : ""
      } bg-red-50 border-red-500 text-red-700`}
      style={{ width: "100%", height: "100%" }}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded bg-red-600 text-white">
          Issue
        </span>
      </div>
      <div className="text-sm font-semibold text-on-surface line-clamp-2">
        {data.label}
      </div>
      {data.page ? (
        <div className="text-[10px] text-on-surface-variant mt-1">P.{data.page}</div>
      ) : null}
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  );
}

/**
 * e-Discovery 증거 노드 — 증거(evidence)를 표현.
 * 녹색 계열의 Tailwind 스타일로 시각적 구분.
 */
function EvidenceNode({ data, selected }) {
  return (
    <div
      className={`rounded-lg border-2 shadow-sm px-3 py-2 ${dimClass(data)} ${
        selected ? "ring-2 ring-emerald-400/40" : ""
      } bg-emerald-50 border-emerald-500 text-emerald-700`}
      style={{ width: "100%", height: "100%" }}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded bg-emerald-600 text-white">
          Evidence
        </span>
      </div>
      <div className="text-sm font-semibold text-on-surface line-clamp-2">
        {data.label}
      </div>
      {data.page ? (
        <div className="text-[10px] text-on-surface-variant mt-1">P.{data.page}</div>
      ) : null}
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  );
}

/**
 * e-Discovery 원고 노드 — 원고(plaintiff)를 표현.
 * 파란색 계열의 Tailwind 스타일로 시각적 구분.
 */
function PlaintiffNode({ data, selected }) {
  return (
    <div
      className={`rounded-lg border-2 shadow-sm px-3 py-2 ${dimClass(data)} ${
        selected ? "ring-2 ring-blue-400/40" : ""
      } bg-blue-50 border-blue-500 text-blue-700`}
      style={{ width: "100%", height: "100%" }}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded bg-blue-600 text-white">
          Plaintiff
        </span>
      </div>
      <div className="text-sm font-semibold text-on-surface line-clamp-2">
        {data.label}
      </div>
      {data.page ? (
        <div className="text-[10px] text-on-surface-variant mt-1">P.{data.page}</div>
      ) : null}
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  );
}

/**
 * e-Discovery 피고 노드 — 피고(defendant)를 표현.
 * 주황색/노란색 계열의 Tailwind 스타일로 시각적 구분.
 */
function DefendantNode({ data, selected }) {
  return (
    <div
      className={`rounded-lg border-2 shadow-sm px-3 py-2 ${dimClass(data)} ${
        selected ? "ring-2 ring-amber-400/40" : ""
      } bg-amber-50 border-amber-500 text-amber-700`}
      style={{ width: "100%", height: "100%" }}
    >
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-600 text-white">
          Defendant
        </span>
      </div>
      <div className="text-sm font-semibold text-on-surface line-clamp-2">
        {data.label}
      </div>
      {data.page ? (
        <div className="text-[10px] text-on-surface-variant mt-1">P.{data.page}</div>
      ) : null}
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  );
}

const nodeTypes = {
  "eDiscovery-swimlane": SwimlaneNode,
  "eDiscovery-issue": IssueNode,
  "eDiscovery-evidence": EvidenceNode,
  "eDiscovery-plaintiff": PlaintiffNode,
  "eDiscovery-defendant": DefendantNode,
};

// 엣지 타입 매핑 — anomaly 엣지는 AnomalyEdge 커스텀 컴포넌트로 렌더링
const edgeTypes = {
  anomaly: AnomalyEdge,
};

/* ============================================================
 * 파라미터 슬라이더 컴포넌트
 * ========================================================== */

/**
 * SliderControl — 레이블 + 범위 + 숫자 표시가 있는 슬라이더 입력.
 * shadcn/ui를 사용하지 않고 Tailwind 기본 range 스타일로 구현.
 */
function SliderControl({ label, value, min, max, step, unit = "", onChange, disabled }) {
  return (
    <div className="flex flex-col gap-1 min-w-[140px] flex-1" data-oid="ediscovery-slider">
      <div className="flex items-center justify-between text-xs text-on-surface-variant">
        <span>{label}</span>
        <span className="font-medium text-on-surface">
          {value}
          {unit}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        disabled={disabled}
        className="w-full h-1.5 bg-surface-container-high rounded-lg appearance-none cursor-pointer accent-primary disabled:opacity-50"
      />
    </div>
  );
}

/* ============================================================
 * 쟁점 필터 바 + 점진적 탐색 오버레이
 * ========================================================== */

/**
 * IssueFilterBar — 그래프에서 추출한 고유 쟁점(issue) 라벨을 토글 칩으로 표시.
 * 선택되지 않은 쟁점의 노드는 hidden 대신 디밍(opacity-20 grayscale) 처리된다.
 * shadcn/ui 없이 Tailwind만으로 구현.
 *
 * @param {Object} props
 * @param {Array<string>} props.issues - 고유 쟁점 라벨 목록
 * @param {Set<string>} props.selectedIssues - 선택된 쟁점 집합
 * @param {Function} props.onToggle - 쟁점 토글 콜백 (issueLabel) => void
 */
function IssueFilterBar({ issues, selectedIssues, onToggle }) {
  const { t } = useTranslation();
  if (!issues.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-oid="ediscovery-issue-filter">
      <div className="flex items-center gap-1 text-xs text-on-surface-variant mr-1">
        <Filter size={12} />
        {t("page:result.ediscoveryIssueFilter")}
      </div>
      {issues.map((issue) => {
        const active = selectedIssues.has(issue);
        return (
          <button
            key={issue}
            onClick={() => onToggle(issue)}
            className={`px-2.5 py-1 rounded-full text-[11px] font-medium border transition-all ${
              active
                ? "bg-red-600 text-white border-red-600"
                : "bg-surface-container-low text-on-surface-variant border-outline-variant hover:border-red-400"
            }`}
          >
            {issue}
          </button>
        );
      })}
    </div>
  );
}

/**
 * DetailOverlayPanel — 노드 클릭 시 우측에서 부드럽게 등장하는 상세 정보 오버레이.
 * 노드의 label/summary/page/confidence를 표시하고 "원본 PDF 보기" 버튼으로
 * SourcePanel의 scrollToPage를 호출해 원본 PDF 페이지를 동기화한다.
 *
 * [Flow: Step 1 (노드 데이터 수신) -> Step 2 (우측 슬라이드인 패널 렌더링) -> Step 3 (원본 PDF 보기 버튼 → onScrollToPage)]
 *
 * @param {Object} props
 * @param {Object|null} props.node - 선택된 노드 (null이면 닫힘)
 * @param {Function} props.onClose - 패널 닫기 콜백
 * @param {Function} props.onScrollToPage - 원본 PDF 페이지 스크롤 콜백 (pageNum) => void
 */
function DetailOverlayPanel({ node, onClose, onScrollToPage }) {
  const { t } = useTranslation();
  if (!node) return null;
  const data = node.data || {};
  const page = data.page;
  return (
    <div
      className="absolute top-0 right-0 h-full w-[300px] md:w-[340px] z-30 bg-surface-container-lowest border-l border-outline-variant shadow-xl flex flex-col animate-stagger-enter"
      data-oid="ediscovery-detail-panel"
    >
      {/* 헤더 — 닫기 버튼 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant">
        <span className="text-sm font-semibold text-on-surface">{t("page:result.ediscoveryDetailTitle")}</span>
        <button
          onClick={onClose}
          className="p-1 rounded hover:bg-surface-container-high text-on-surface-variant"
          title={t("page:result.ediscoveryClose")}
        >
          <X size={16} />
        </button>
      </div>
      {/* 본문 — 노드 상세 정보 */}
      <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-3">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-wide text-on-surface-variant mb-1">
            {node.type?.replace("eDiscovery-", "")}
          </div>
          <div className="text-base font-semibold text-on-surface">{data.label}</div>
        </div>
        {data.summary && (
          <div>
            <div className="text-[10px] font-bold uppercase tracking-wide text-on-surface-variant mb-1">
              {t("page:result.ediscoverySummary")}
            </div>
            <div className="text-sm text-on-surface-variant leading-relaxed">{data.summary}</div>
          </div>
        )}
        <div className="flex flex-wrap gap-2 text-xs">
          {page && (
            <span className="px-2 py-1 rounded bg-surface-container-high text-on-surface">
              {t("page:result.ediscoveryPage")}: {page}
            </span>
          )}
          {data.confidence != null && (
            <span className="px-2 py-1 rounded bg-surface-container-high text-on-surface">
              {t("page:result.ediscoveryConfidence")}: {(data.confidence).toFixed(2)}
            </span>
          )}
          {data.date && (
            <span className="px-2 py-1 rounded bg-surface-container-high text-on-surface">
              {data.date}
            </span>
          )}
        </div>
      </div>
      {/* 푸터 — 원본 PDF 보기 버튼 */}
      {page && (
        <div className="px-4 py-3 border-t border-outline-variant">
          <button
            onClick={() => onScrollToPage(page)}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity"
          >
            <FileText size={16} />
            {t("page:result.ediscoveryViewSource")}
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

/* ============================================================
 * 메인 그래프 캔버스
 * ========================================================== */

/**
 * GraphCanvas — React Flow Provider 내부에서 동작하는 e-Discovery 뷰어.
 * 파라미터 패널, 분석 API 호출, elkjs 레이아웃, 노드 클릭 연동을 담당.
 *
 * @param {Object} props
 * @param {string} props.jobId - 현재 Job ID
 * @param {Object} props.job - Job 객체 (ediscovery_status, ediscovery_graphs, ediscovery_metrics 포함)
 * @param {Function} [props.onNodeClick] - 노드 클릭 콜백 (node) => void
 */
function GraphCanvas({ jobId, job, onNodeClick }) {
  const { t } = useTranslation();
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [metrics, setMetrics] = useState({ total_docs: 0, processed_chunks: 0, threshold: 0 });
  // 점진적 탐색 오버레이 — 클릭한 노드 상세 정보
  const [selectedNode, setSelectedNode] = useState(null);
  // 쟁점 필터 — 선택된 쟁점 라벨 집합 (비어 있으면 전체 표시)
  const [selectedIssues, setSelectedIssues] = useState(new Set());
  // 그래프에서 추출한 고유 쟁점 라벨 목록
  const [issueList, setIssueList] = useState([]);

  const totalPages = job?.total_pages || job?.total_files || 1;
  const cachedParams = job?.ediscovery_params || {};

  const [params, setParams] = useState({
    total_docs: Math.min(cachedParams.max_docs || totalPages, 5000),
    chunk_size: cachedParams.chunk_size || 512,
    threshold: cachedParams.threshold ?? 0.5,
  });

  const reactFlow = useReactFlow();

  // 노드 타입별 기본 크기 (elkjs 입력용) — swimlane은 별도 크기
  const nodeSizeByType = useMemo(
    () => ({
      swimlane: { width: 600, height: 180 },
      issue: { width: 260, height: 120 },
      evidence: { width: 220, height: 100 },
      plaintiff: { width: 240, height: 110 },
      defendant: { width: 240, height: 110 },
    }),
    []
  );

  /**
   * [Flow: Step 1 (graph_data 수신 + 신/구 스키마 판별) -> Step 2 (React Flow 노드/에지 변환)
   *       -> Step 3 (신규 스키마: swimlane 레이아웃 / 구 스키마: 평면 레이아웃) -> Step 4 (쟁점 목록 추출) -> Step 5 (state 갱신 + fitView)]
   */
  const buildGraph = useCallback(
    async (graphData) => {
      if (!graphData?.nodes?.length) {
        setNodes([]);
        setEdges([]);
        setIssueList([]);
        return;
      }
      setLoading(true);
      setError("");
      try {
        // 신규 스키마 판별 — parentId 보유 노드가 하나라도 있으면 swimlane 스키마
        const hasSwimlane = graphData.nodes.some(
          (n) => n.parentId || n.type === "swimlane"
        );

        const baseNodes = graphData.nodes.map((n) => {
          const size = nodeSizeByType[n.type] || nodeSizeByType.evidence;
          return {
            id: n.id,
            type: `eDiscovery-${n.type}`,
            // 신규 스키마: parentId 보존 (React Flow가 부모 기준 상대좌표로 해석)
            parentId: hasSwimlane ? n.parentId : undefined,
            data: { ...n.data, type: n.type, width: size.width, height: size.height },
          };
        });
        const baseEdges = graphData.edges.map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          type: e.type || "smoothstep",
          data: e.data,
        }));

        // 신규 스키마는 swimlane 레이아웃, 구 스키마는 평면 레이아웃
        const layouted = hasSwimlane
          ? await calculateElkSwimlaneLayout(baseNodes, baseEdges)
          : await calculateElkLayout(baseNodes, baseEdges);
        setNodes(layouted);
        setEdges(baseEdges);

        // 쟁점 목록 추출 — issue 타입 노드의 label (고유값)
        const issues = [
          ...new Set(
            graphData.nodes
              .filter((n) => n.type === "issue")
              .map((n) => n.data?.label || n.data?.issue)
              .filter(Boolean)
          ),
        ];
        setIssueList(issues);
        // 필터 초기화 — 모든 쟁점 선택 (전체 표시)
        setSelectedIssues(new Set(issues));

        setTimeout(() => reactFlow.fitView({ padding: 0.2, duration: 500 }), 80);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    },
    [nodeSizeByType, reactFlow, setEdges, setNodes]
  );

  /**
   * [Flow: Step 1 (선택된 쟁점 집합 기반 디밍 플래그 계산) -> Step 2 (노드 data.dimmed 갱신)]
   * 미선택 쟁점의 노드는 hidden 대신 opacity-20 grayscale 디밍.
   * swimlane 노드는 필터 대상에서 제외 (항상 표시).
   */
  const applyIssueFilter = useCallback(
    (issues) => {
      setNodes((prev) =>
        prev.map((node) => {
          // swimlane 노드는 디밍 제외
          if (node.type === "eDiscovery-swimlane") {
            return { ...node, data: { ...node.data, dimmed: false } };
          }
          // issue 노드는 자신의 label이 선택 집합에 있는지 확인
          if (node.type === "eDiscovery-issue") {
            const label = node.data?.label;
            const dimmed = label && !issues.has(label);
            return { ...node, data: { ...node.data, dimmed } };
          }
          // evidence/plaintiff/defendant 노드 — issue 필드(있는 경우) 기반 디밍
          const issue = node.data?.issue;
          if (issue && !issues.has(issue)) {
            return { ...node, data: { ...node.data, dimmed: true } };
          }
          return { ...node, data: { ...node.data, dimmed: false } };
        })
      );
    },
    [setNodes]
  );

  // 쟁점 필터 토글 핸들러
  const handleToggleIssue = useCallback(
    (issue) => {
      setSelectedIssues((prev) => {
        const next = new Set(prev);
        if (next.has(issue)) next.delete(issue);
        else next.add(issue);
        applyIssueFilter(next);
        return next;
      });
    },
    [applyIssueFilter]
  );

  // 노드 클릭 핸들러 — 점진적 탐색 오버레이 표시 + 외부 onNodeClick 콜백 호출
  const handleNodeClick = useCallback(
    (_, node) => {
      // swimlane 노드 클릭 시 오버레이 표시하지 않음
      if (node.type === "eDiscovery-swimlane") return;
      setSelectedNode(node);
      onNodeClick?.(node);
    },
    [onNodeClick]
  );

  // 원본 PDF 페이지 스크롤 — DetailOverlayPanel에서 호출
  const handleScrollToPage = useCallback(
    (pageNum) => {
      onNodeClick?.({ data: { page: pageNum } });
    },
    [onNodeClick]
  );

  // [Flow: Step 1 (Job prop의 e-Discovery 결과 확인) -> Step 2 (done 상태이면 그래프 빌드) -> Step 3 (processing 상태이면 폴링 재개)]
  useEffect(() => {
    if (job?.ediscovery_status === "done" && job?.ediscovery_graphs?.nodes?.length > 0) {
      setMetrics(job.ediscovery_metrics || { total_docs: 0, processed_chunks: 0, threshold: 0 });
      buildGraph(job.ediscovery_graphs);
    } else if (job?.ediscovery_status === "processing") {
      startPolling();
    } else {
      setNodes([]);
      setEdges([]);
    }
  }, [job?.ediscovery_status, job?.ediscovery_graphs, job?.ediscovery_metrics, buildGraph, setEdges, setNodes, startPolling]);

  const pollRef = useRef(null);

  // [Flow: Step 1 (폴링 클리어업) -> Step 2 (언마운트 시 남은 interval 제거)]
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  /**
   * [Flow: Step 1 (GET /ediscovery 상태 조회) -> Step 2 (done이면 metrics/그래프 갱신 + 폴링 중지)
   *       -> Step 3 (error이면 오류 표시 + 폴링 중지) -> Step 4 (processing이면 계속 폴링)]
   */
  const startPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    setLoading(true);
    pollRef.current = setInterval(async () => {
      try {
        const status = await api.getEdiscovery(jobId);
        if (status.ediscovery_status === "done") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setMetrics(status.ediscovery_metrics || { total_docs: 0, processed_chunks: 0, threshold: 0 });
          await buildGraph(status.graph_data);
          setLoading(false);
        } else if (status.ediscovery_status === "error") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          const msg = status.ediscovery_error || t("page:errors.networkError");
          setError(msg);
          setLoading(false);
        }
      } catch (err) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg || t("page:errors.networkError"));
        setLoading(false);
      }
    }, 2000);
  }, [buildGraph, jobId, t]);

  /**
   * [Flow: Step 1 (현재 파라미터 수집) -> Step 2 (FastAPI /ediscovery/extract POST with wait=false)
   *       -> Step 3 (processing이면 폴링 시작) -> Step 4 (즉시 완료된 경우 그래프 바로 렌더)]
   */
  const handleAnalyze = useCallback(async () => {
    if (loading) return;
    setLoading(true);
    setError("");
    try {
      const response = await api.extractEdiscoveryGraph(
        jobId,
        {
          total_docs: params.total_docs,
          chunk_size: params.chunk_size,
          threshold: params.threshold,
        },
        { wait: false }
      );
      if (response.status === "processing") {
        startPolling();
      } else if (response.graph_data) {
        setMetrics(response.ediscovery_metrics || { total_docs: 0, processed_chunks: 0, threshold: 0 });
        await buildGraph(response.graph_data);
        setLoading(false);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg || t("page:errors.networkError"));
      setLoading(false);
    }
  }, [buildGraph, jobId, loading, params, startPolling, t]);

  const bgVariantEnum = BackgroundVariant.Lines;

  return (
    <>
      {/* 파라미터 + 메트릭 + 분석 버튼 패널 */}
      <Panel position="top-left" className="!m-2">
        <div className="flex flex-col gap-2 bg-surface-container-lowest rounded-lg shadow-md border border-outline-variant p-3 max-w-[calc(100vw-1rem)] w-[360px] md:w-[480px]">
          <div className="flex items-center gap-2 text-sm font-medium text-on-surface">
            <Network size={16} className="text-primary" />
            {t("page:result.ediscoveryParams")}
          </div>
          <div className="flex flex-col md:flex-row gap-3">
            <SliderControl
              label={t("page:result.ediscoveryDocScale")}
              value={params.total_docs}
              min={1}
              max={Math.max(1, Math.min(totalPages, 5000))}
              step={1}
              onChange={(v) => setParams((p) => ({ ...p, total_docs: v }))}
              disabled={loading}
            />
            <SliderControl
              label={t("page:result.ediscoveryChunkSize")}
              value={params.chunk_size}
              min={256}
              max={4096}
              step={128}
              onChange={(v) => setParams((p) => ({ ...p, chunk_size: v }))}
              disabled={loading}
            />
            <SliderControl
              label={t("page:result.ediscoveryThreshold")}
              value={params.threshold}
              min={0}
              max={1}
              step={0.05}
              onChange={(v) => setParams((p) => ({ ...p, threshold: v }))}
              disabled={loading}
            />
          </div>
          <div className="flex items-center justify-between gap-2 pt-1 border-t border-outline-variant/50">
            <div className="flex items-center gap-3 text-xs text-on-surface-variant">
              <span>{t("page:result.ediscoveryTotalDocs")}: <strong className="text-on-surface">{metrics.total_docs || 0}</strong></span>
              <span>{t("page:result.ediscoveryProcessedChunks")}: <strong className="text-on-surface">{metrics.processed_chunks || 0}</strong></span>
              <span>{t("page:result.ediscoveryThresholdLabel")}: <strong className="text-on-surface">{(metrics.threshold ?? 0).toFixed(2)}</strong></span>
            </div>
            <button
              onClick={handleAnalyze}
              disabled={loading}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white text-xs font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
              data-oid="ediscovery-analyze-btn"
            >
              {loading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              {loading ? t("page:result.ediscoveryAnalyzing") : t("page:result.ediscoveryAnalyze")}
            </button>
          </div>
        </div>
      </Panel>

      {/* 로딩 오버레이 */}
      {loading && (
        <div className="absolute inset-0 z-20 bg-surface/80 flex flex-col items-center justify-center gap-3" data-oid="ediscovery-loading">
          <Loader2 size={28} className="animate-spin text-primary" />
          <p className="text-sm text-on-surface-variant">{t("page:result.ediscoveryAnalyzing")}</p>
        </div>
      )}

      {/* 에러 메시지 */}
      {error && (
        <div className="absolute top-[180px] left-1/2 -translate-x-1/2 z-20 bg-error-container border border-error text-on-error-container px-4 py-3 rounded-lg shadow-md flex items-start gap-2 max-w-[90%]" data-oid="ediscovery-error">
          <AlertCircle size={18} className="flex-shrink-0 mt-0.5" />
          <div className="text-sm">
            <p className="font-medium">{t("page:result.ediscoveryError")}</p>
            <p className="text-xs opacity-90">{error}</p>
          </div>
          <button
            onClick={handleAnalyze}
            className="ml-2 p-1 hover:bg-error/10 rounded"
            title={t("page:result.retry")}
          >
            <RefreshCw size={14} />
          </button>
        </div>
      )}

      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={handleNodeClick}
        fitView
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ type: "smoothstep" }}
        nodesDraggable
        panOnDrag
        data-oid="ediscovery-canvas"
      >
        <Background variant={bgVariantEnum} gap={16} size={1} />
        <Controls position="bottom-left" className="!flex" />
        <MiniMap
          className="hidden md:block"
          nodeColor={(n) => {
            if (n.type === "eDiscovery-swimlane") return "#6366f1";
            if (n.type === "eDiscovery-issue") return "#ef4444";
            if (n.type === "eDiscovery-evidence") return "#10b981";
            if (n.type === "eDiscovery-plaintiff") return "#3b82f6";
            if (n.type === "eDiscovery-defendant") return "#f59e0b";
            return "#6366f1";
          }}
          nodeStrokeColor="#fff"
          nodeBorderRadius={4}
          maskColor="rgba(0,0,0,0.1)"
          pannable
          zoomable
        />
      </ReactFlow>

      {/* 쟁점 필터 바 — 상단 중앙 (그래프가 있을 때만 표시) */}
      {nodes.length > 0 && issueList.length > 0 && (
        <Panel position="top-center" className="!m-2">
          <div className="bg-surface-container-lowest rounded-lg shadow-md border border-outline-variant px-3 py-2 max-w-[calc(100vw-2rem)]">
            <IssueFilterBar
              issues={issueList}
              selectedIssues={selectedIssues}
              onToggle={handleToggleIssue}
            />
          </div>
        </Panel>
      )}

      {/* 점진적 탐색 오버레이 패널 — 노드 클릭 시 우측 슬라이드인 */}
      <DetailOverlayPanel
        node={selectedNode}
        onClose={() => setSelectedNode(null)}
        onScrollToPage={handleScrollToPage}
      />

      {/* 빈 상태 안내 */}
      {!loading && nodes.length === 0 && !error && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center text-on-surface-variant gap-3" data-oid="ediscovery-empty">
          <Network size={40} className="text-primary/40" />
          <p className="text-sm text-center max-w-xs">{t("page:result.ediscoveryEmpty")}</p>
          <button
            onClick={handleAnalyze}
            className="flex items-center gap-1.5 px-4 py-2 bg-primary text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity"
          >
            <Play size={16} />
            {t("page:result.ediscoveryAnalyze")}
          </button>
        </div>
      )}
    </>
  );
}

/* ============================================================
 * EDiscoveryViewer — 외부 컴포넌트 (ReactFlowProvider 래퍼)
 * ============================================================ */

/**
 * EDiscoveryViewer — e-Discovery GraphRAG 결과를 React Flow로 시각화하는 뷰어.
 *
 * @param {Object} props
 * @param {string} props.jobId - Job ID
 * @param {Object} props.job - Job 객체 (ediscovery_* 필드 포함)
 * @param {Function} [props.onNodeClick] - 노드 클릭 시 호출될 콜백 (node) => void
 */
export default function EDiscoveryViewer({ jobId, job, onNodeClick }) {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState("graph"); // "graph" | "mapper"

  return (
    <div className="h-full flex flex-col" data-oid="ediscovery-viewer">
      {/* 헤더 */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-outline-variant bg-surface-container-lowest">
        <Network size={16} className="text-primary" />
        <span className="text-sm font-medium text-on-surface">{t("page:result.ediscoveryView")}</span>
        <span className="text-xs text-on-surface-variant ml-2 hidden sm:inline">{t("page:result.ediscoveryHint")}</span>
        {/* 탭 전환 */}
        <div className="ml-auto flex items-center gap-1 bg-surface-container-high rounded-lg p-0.5">
          <button
            onClick={() => setActiveTab("graph")}
            className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
              activeTab === "graph" ? "bg-surface text-on-surface shadow-sm" : "text-on-surface-variant hover:text-on-surface"
            }`}
            data-oid="ediscovery-tab-graph"
          >
            <Network size={12} />
            {t("page:result.mapperTabGraph")}
          </button>
          <button
            onClick={() => setActiveTab("mapper")}
            className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md transition-colors ${
              activeTab === "mapper" ? "bg-surface text-on-surface shadow-sm" : "text-on-surface-variant hover:text-on-surface"
            }`}
            data-oid="ediscovery-tab-mapper"
          >
            <Puzzle size={12} />
            {t("page:result.mapperTabMapper")}
          </button>
        </div>
      </div>
      {/* 캔버스 — 탭에 따라 Graph 또는 Mapper 패널 렌더링 */}
      <div className="flex-1 min-h-0 relative">
        {activeTab === "graph" ? (
          <ReactFlowProvider>
            <GraphCanvas jobId={jobId} job={job} onNodeClick={onNodeClick} />
          </ReactFlowProvider>
        ) : (
          <EvidenceMapperPanel jobId={jobId} job={job} />
        )}
      </div>
    </div>
  );
}
