// [Flow: Step 1 (마크다운 파싱 + 커스텀 레이아웃) -> Step 2 (React Flow 렌더링)
//       -> Step 3 (툴바: 주석 추가 / 연결 / 삭제 / 배경 전환 / 다크모드 / 레이아웃 재배치)
//       -> Step 4 (노드 클릭 시 콜백)]
// 마크다운 문서의 헤딩 구조를 React Flow 캔버스에 논리 흐름 그래프로 시각화.
// 계층 구조는 실선(hierarchy) 엣지, AI 의존성은 점선(dependency) 엣지로 표현.
// 사용자는 주석 노트 추가, 수동 연결, 엣지 재연결, 선택 삭제, 배경 전환 가능.
import { useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, forwardRef } from "react";
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
  addEdge,
  reconnectEdge,
  Handle,
  Position,
  BaseEdge,
  getBezierPath,
  getSmoothStepPath,
  EdgeLabelRenderer,
  NodeResizer,
} from "@xyflow/react";
import {
  Loader2,
  Workflow,
  StickyNote,
  Trash2,
  LayoutGrid,
  Maximize,
  Image as ImageIcon,
  Video,
  List,
  Table,
  Code2,
  Quote,
  FileText,
  File,
} from "lucide-react";
import { parseMarkdownToFlow, parseMultiFileMarkdownToFlow } from "../utils/markdownToFlow";
import { calculateFlowLayout } from "../utils/flowLayout";
import { useFlowDrawing } from "../hooks/useFlowDrawing.js";
import DrawingOverlay from "./flow/DrawingOverlay.jsx";
import DrawingToolbar from "./flow/DrawingToolbar.jsx";

/* ============================================================
 * 커스텀 노드 컴포넌트
 * ========================================================== */

/**
 * 타이틀 노드 컴포넌트 — H1 제목을 캔버스 최상단에 크게 표시.
 * 문서의 최상위 제목을 시각적으로 강조하며, 하위 H2 노드들을 자식으로 가짐.
 * HeadingNode보다 크고 눈에 띄는 스타일로 렌더링.
 */
function TitleNode({ data, selected }) {
  return (
    <div
      className={`bg-primary rounded-lg border-2 shadow-md px-6 py-5 transition-all min-h-[80px] ${
        selected ? "border-primary ring-4 ring-primary/30" : "border-primary-variant"
      }`}
      style={{ width: "100%" }}
    >
      {/* 부모-자식 hierarchy 엣지: 위쪽 (타이틀은 최상단이므로 보통 없음) */}
      {data.hasParent && <Handle type="target" position={Position.Top} id="top" isConnectable={true} />}
      {/* 들어오는 next 엣지: 왼쪽 (다중 파일 시 이전 파일에서 연결) */}
      {data.hasPrev && <Handle type="target" position={Position.Left} id="left" isConnectable={true} />}
      <div className="flex items-center gap-2 mb-1">
        <Workflow size={20} className="text-on-primary" />
        <span className="text-xs font-bold uppercase tracking-wide text-on-primary/80">
          TITLE
        </span>
      </div>
      <div className="font-bold text-lg text-on-surface line-clamp-2 break-words">
        {data.label}
      </div>
      {/* 나가는 next 엣지: 오른쪽 */}
      {data.hasNext && <Handle type="source" position={Position.Right} id="right" isConnectable={true} />}
      {/* 부모-자식 hierarchy 엣지: 아래쪽 (H2 자식들) */}
      {data.hasChildren && <Handle type="source" position={Position.Bottom} id="bottom" isConnectable={true} />}
    </div>
  );
}

/**
 * 헤딩 노드 컴포넌트 — 제목 + H레벨 배지 + 내용 미리보기.
 * React Flow 커스텀 노드로 등록되어 nodeTypes에 매핑됨.
 * hasNext/hasPrev/hasParent/hasChildren 플래그에 따라 4방향 Handle을 동적으로 렌더링.
 */
function HeadingNode({ data, selected }) {
  return (
    <div
      className={`bg-white rounded-lg border-2 shadow-sm px-5 py-4 transition-all min-h-[96px] ${
        selected ? "border-primary shadow-md ring-2 ring-primary/20" : "border-outline-variant"
      }`}
      style={{ width: "100%" }}
    >
      {/* 들어오는 next 엣지: 항상 왼쪽 */}
      {data.hasPrev && <Handle type="target" position={Position.Left} id="left" isConnectable={true} />}
      {/* 부모-자식 hierarchy 엣지: 위쪽 */}
      {data.hasParent && <Handle type="target" position={Position.Top} id="top" isConnectable={true} />}
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm font-bold px-2 py-1 rounded bg-primary/10 text-primary">
          H{data.level}
        </span>
        <span className="font-semibold text-base text-on-surface line-clamp-2">
          {data.label}
        </span>
      </div>
      {data.contentPreview && (
        <p className="text-sm text-on-surface-variant line-clamp-3 mt-2">
          {data.contentPreview}
        </p>
      )}
      {/* 나가는 next 엣지: 항상 오른쪽 */}
      {data.hasNext && <Handle type="source" position={Position.Right} id="right" isConnectable={true} />}
      {/* 부모-자식 hierarchy 엣지: 아래쪽 */}
      {data.hasChildren && <Handle type="source" position={Position.Bottom} id="bottom" isConnectable={true} />}
    </div>
  );
}

// 콘텐츠 타입별 아이콘/색상 매핑 — markdownToFlow.js의 CONTENT_TYPE_LABELS와 대응
const CONTENT_TYPE_META = {
  image: { Icon: ImageIcon, color: "text-emerald-600", bg: "bg-emerald-50", border: "border-emerald-200" },
  video: { Icon: Video, color: "text-rose-600", bg: "bg-rose-50", border: "border-rose-200" },
  list: { Icon: List, color: "text-amber-600", bg: "bg-amber-50", border: "border-amber-200" },
  table: { Icon: Table, color: "text-cyan-600", bg: "bg-cyan-50", border: "border-cyan-200" },
  code: { Icon: Code2, color: "text-violet-600", bg: "bg-violet-50", border: "border-violet-200" },
  quote: { Icon: Quote, color: "text-slate-600", bg: "bg-slate-50", border: "border-slate-200" },
  text: { Icon: FileText, color: "text-blue-600", bg: "bg-blue-50", border: "border-blue-200" },
};

/**
 * 콘텐츠 노드 컴포넌트 — heading 하위의 본문/이미지/리스트/표/코드/인용/동영상 블록.
 * 타입별 아이콘 + 라벨 배지 + 미리보기 텍스트를 표시.
 * 노드 본문에는 전체 내용이 아닌 일부만 표시하고, 클릭 시 onNodeClick으로 원문 페이지로 이동.
 * 이미지는 <img> 썸네일, 동영상은 <video preload="metadata"> 첫 프레임을 썸네일로 표시 (iframe 불가 대응).
 */
function ContentNode({ data, selected }) {
  const meta = CONTENT_TYPE_META[data.contentType] || CONTENT_TYPE_META.text;
  const { Icon } = meta;

  // 이미지/동영상 콘텐츠에서 URL 추출 — 썸네일 표시용
  const mediaUrl = (() => {
    if (data.contentType !== "image" && data.contentType !== "video") return null;
    const firstToken = data.content?.[0];
    if (!firstToken) return null;
    if (data.contentType === "image") {
      const imgToken = (firstToken.tokens || []).find(t => t.type === "image");
      return imgToken?.href || null;
    }
    // video — html 토큰에서 src 속성 추출, 또는 paragraph 텍스트에서 URL 추출
    const htmlText = firstToken.text || "";
    const match = htmlText.match(/src="([^"]+)"/);
    if (match) return match[1];
    // paragraph에 비디오 URL이 있는 경우
    const urlMatch = (firstToken.text || "").match(/(https?:\/\/[^\s)]+\.(mp4|webm|mov|avi|mkv|m4v)(\?[^\s)]*)?)/i);
    return urlMatch?.[1] || null;
  })();

  // YouTube 링크인 경우 썸네일 URL 추출 — iframe 없이 썸네일 이미지만 표시
  const youtubeThumbUrl = (() => {
    if (!mediaUrl) return null;
    const ytMatch = mediaUrl.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([\w-]{11})/);
    if (ytMatch) return `https://img.youtube.com/vi/${ytMatch[1]}/hqdefault.jpg`;
    return null;
  })();

  const isDirectVideo = data.contentType === "video" && mediaUrl && !youtubeThumbUrl;

  return (
    <div
      className={`rounded-lg border-2 shadow-sm px-4 py-3 transition-all cursor-pointer min-h-[80px] ${meta.bg} ${
        selected ? `${meta.border} shadow-md ring-2 ring-primary/20` : meta.border
      }`}
      style={{ width: "100%" }}
    >
      {data.hasParent && <Handle type="target" position={Position.Top} id="top" isConnectable={true} />}
      {/* 들어오는 next 엣지: 항상 왼쪽 */}
      {data.hasPrev && <Handle type="target" position={Position.Left} id="left" isConnectable={true} />}
      <div className="flex items-center gap-2 mb-2">
        <Icon size={18} className={meta.color} />
        <span className={`text-xs font-bold uppercase tracking-wide ${meta.color}`}>
          {data.contentTypeLabel}
        </span>
      </div>
      {/* 미리보기 텍스트 — 전체가 아닌 일부만 표시 */}
      <p className="text-sm text-on-surface line-clamp-3 break-words">
        {data.label}
      </p>
      {/* 이미지 썸네일 — <img> 인라인 미리보기 */}
      {data.contentType === "image" && mediaUrl && (
        <a
          href={mediaUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 block relative"
          onClick={(e) => e.stopPropagation()}
        >
          <img
            src={mediaUrl}
            alt={data.label}
            className="w-full h-32 object-cover rounded border border-outline-variant"
            loading="lazy"
            onError={(e) => { e.target.style.display = "none"; }}
          />
        </a>
      )}
      {/* 동영상 썸네일 — YouTube 썸네일 이미지 (iframe 불가 대응) */}
      {data.contentType === "video" && youtubeThumbUrl && (
        <a
          href={mediaUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 block relative"
          onClick={(e) => e.stopPropagation()}
        >
          <img
            src={youtubeThumbUrl}
            alt={data.label}
            className="w-full h-32 object-cover rounded border border-outline-variant"
            loading="lazy"
            onError={(e) => { e.target.style.display = "none"; }}
          />
          {/* 재생 버튼 오버레이 */}
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="bg-black/60 rounded-full p-2">
              <Video size={20} className="text-white" />
            </div>
          </div>
        </a>
      )}
      {/* 동영상 썸네일 — 직접 비디오 파일은 <video preload="metadata">로 첫 프레임 표시 */}
      {isDirectVideo && (
        <a
          href={mediaUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 block relative"
          onClick={(e) => e.stopPropagation()}
        >
          <video
            src={mediaUrl}
            preload="metadata"
            muted
            className="w-full h-32 object-cover rounded border border-outline-variant"
            onError={(e) => { e.target.style.display = "none"; }}
          />
          {/* 재생 버튼 오버레이 */}
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="bg-black/60 rounded-full p-2">
              <Video size={20} className="text-white" />
            </div>
          </div>
        </a>
      )}
      {/* 동영상 URL만 있고 썸네일을 가져올 수 없는 경우 — 링크 버튼 */}
      {data.contentType === "video" && mediaUrl && !youtubeThumbUrl && !isDirectVideo && (
        <a
          href={mediaUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-flex items-center gap-1 text-sm text-rose-600 hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          <Video size={12} />
          동영상 보기
        </a>
      )}
      {data.hasNext && <Handle type="source" position={Position.Right} id="right" isConnectable={true} />}
      {data.hasChildren && <Handle type="source" position={Position.Bottom} id="bottom" isConnectable={true} />}
    </div>
  );
}

/**
 * 주석 노트 노드 — 스티키 노트. 더블클릭으로 텍스트 편집.
 * 사용자가 툴바에서 추가할 수 있으며, 자유롭게 드래그/편집/삭제 가능.
 */
function NoteNode({ data, selected, id }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(data.text || "");
  const textareaRef = useRef(null);

  // 편집 모드 진입 시 textarea에 포커스
  useEffect(() => {
    if (editing && textareaRef.current) {
      textareaRef.current.focus();
      textareaRef.current.select();
    }
  }, [editing]);

  // 편집 완료 시 data.text 업데이트 (상위에서 onChange로 반영)
  const handleBlur = () => {
    setEditing(false);
    if (data.onTextChange) data.onTextChange(id, text);
  };

  return (
    <div
      className={`rounded-lg border-2 shadow-sm px-3 py-2 min-h-[80px] transition-all ${
        selected
          ? "bg-primary-fixed border-primary shadow-md ring-2 ring-primary/20"
          : "bg-surface-container-low border-primary-fixed-dim"
      }`}
      style={{ width: "100%", height: "100%" }}
    >
      <NodeResizer
        minWidth={120}
        maxWidth={500}
        minHeight={60}
        isVisible={selected}
        color="#f59e0b"
      />
      <Handle type="target" position={Position.Top} isConnectable={true} />
      <div className="flex flex-col h-full">
        <div className="flex items-center gap-1 mb-1">
          <StickyNote size={12} className="text-primary" />
          <span className="text-[10px] font-bold text-on-primary-fixed-variant uppercase tracking-wide">Note</span>
        </div>
        {editing ? (
          <textarea
            ref={textareaRef}
            value={text}
            onChange={e => setText(e.target.value)}
            onBlur={handleBlur}
            onKeyDown={e => {
              if (e.key === "Escape") handleBlur();
            }}
            className="flex-1 w-full text-xs text-on-surface bg-transparent border-none outline-none resize-none min-h-0 nodrag nopan"
            placeholder="메모를 입력하세요…"
          />
        ) : (
          <p
            onDoubleClick={() => setEditing(true)}
            className="flex-1 text-xs text-on-surface whitespace-pre-wrap break-words cursor-text min-h-0"
          >
            {text || <span className="text-on-surface-variant italic">더블클릭하여 편집</span>}
          </p>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} isConnectable={true} />
    </div>
  );
}

/**
 * 파일 구분 노드 컴포넌트 — 다중 파일 플로우에서 파일 경계를 표시.
 * 파일 아이콘 + 파일명을 크게 표시하며, 클릭 시 해당 파일로 이동.
 */
function FileNode({ data, selected }) {
  return (
    <div
      className={`rounded-lg border-2 shadow-sm px-5 py-4 transition-all min-h-[80px] bg-surface-container-high ${
        selected ? "border-primary shadow-md ring-2 ring-primary/20" : "border-primary-variant"
      }`}
      style={{ width: "100%" }}
    >
      {data.hasPrev && <Handle type="target" position={Position.Left} id="left" isConnectable={true} />}
      <div className="flex items-center gap-2 mb-1">
        <File size={20} className="text-primary" />
        <span className="text-xs font-bold uppercase tracking-wide text-primary">
          FILE
        </span>
      </div>
      <div className="font-semibold text-base text-on-surface line-clamp-2 break-words">
        {data.label}
      </div>
      {data.hasNext && <Handle type="source" position={Position.Right} id="right" isConnectable={true} />}
      {data.hasChildren && <Handle type="source" position={Position.Bottom} id="bottom" isConnectable={true} />}
    </div>
  );
}

const nodeTypes = { titleNode: TitleNode, headingNode: HeadingNode, contentNode: ContentNode, fileNode: FileNode, noteNode: NoteNode };

/* ============================================================
 * 커스텀 엣지 컴포넌트
 * ========================================================== */

/**
 * 트리 엣지 — 실선 (부모-자식 heading 관계 + top-level 페이지 순서 next 엣지).
 * BaseEdge + getSmoothStepPath로 직각 패스 렌더링.
 */
function TreeEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd, selected }) {
  const [edgePath] = getSmoothStepPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
    borderRadius: 8,
  });
  return (
    <BaseEdge
      id={id}
      path={edgePath}
      style={{ ...style, strokeWidth: selected ? 3 : 2, stroke: selected ? "#6366f1" : (style?.stroke || "#b0b0b0") }}
      markerEnd={markerEnd}
    />
  );
}

/**
 * 트리 엣지 — 실선 + 호버 시 reason 툴팁.
 * LLM이 생성한 논리적 트리 부모-자식 관계를 표현.
 * EdgeLabelRenderer 포털로 SVG 위에 HTML 툴팁을 별도 레이어에 렌더링.
 */
function DependencyEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, data, markerEnd, selected }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          ...style,
          stroke: selected ? "#6366f1" : (style?.stroke || "#b0b0b0"),
          strokeWidth: selected ? 3 : 2,
        }}
        markerEnd={markerEnd || "url(#arrow-closed)"}
      />
      {/* 호버 감지용 투명한 클릭 영역 */}
      <BaseEdge
        id={`${id}-hit`}
        path={edgePath}
        style={{ strokeWidth: 20, stroke: "transparent", cursor: "pointer" }}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
      />
      {showTooltip && data?.reason && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              background: "#1f2937",
              color: "white",
              padding: "6px 10px",
              borderRadius: "6px",
              fontSize: "12px",
              pointerEvents: "none",
              maxWidth: "240px",
              zIndex: 1000,
            }}
            className="nodrag nopan"
          >
            {data.reason}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

/**
 * 사용자 연결 엣지 — 사용자가 수동으로 연결한 엣지.
 * 라벨 표시 + 선택 시 삭제 가능.
 */
function CustomEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, data, markerEnd, selected }) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          ...style,
          stroke: selected ? "#6366f1" : (style?.stroke || "#6366f1"),
          strokeWidth: selected ? 3 : 2,
        }}
        markerEnd={markerEnd}
      />
      {data?.label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              background: "white",
              border: "1px solid #d1d5db",
              borderRadius: "4px",
              padding: "2px 8px",
              fontSize: "11px",
              fontWeight: 500,
              color: "#374151",
              pointerEvents: "none",
            }}
            className="nodrag nopan"
          >
            {data.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const edgeTypes = { hierarchy: TreeEdge, next: TreeEdge, dependency: DependencyEdge, custom: CustomEdge };

/* ============================================================
 * 툴바 컴포넌트 (Panel 오버레이)
 * ========================================================== */

/**
 * FlowToolbar — React Flow Panel 오버레이에 배치된 툴바.
 * 주석 추가, 선택 삭제, 레이아웃 재배치, 전체 보기 버튼 제공.
 */
function FlowToolbar({ onAddNote, onDeleteSelected, onRelayout, onFitView }) {
  const { t } = useTranslation();
  const btnClass = "flex items-center justify-center w-10 h-10 md:w-8 md:h-8 rounded-lg text-sm font-medium transition-colors border";
  const btnDefault = "border-outline-variant bg-surface-container-lowest text-on-surface hover:bg-surface-container-high";
  const btnActive = "border-primary bg-primary/10 text-primary";

  return (
    <>
      {/* 좌측 상단: 주 액션 툴바 */}
      <Panel position="top-left" className="!m-2">
        <div className="flex flex-wrap items-center gap-1 bg-surface-container-lowest rounded-lg shadow-md border border-outline-variant p-1 max-w-[calc(100vw-1rem)]">
          <button
            onClick={onAddNote}
            title={t("page:result.flowAddNote")}
            className={`${btnClass} ${btnDefault}`}
            aria-label={t("page:result.flowAddNote")}
            data-oid="flow-btn-note">
            <StickyNote size={16} />
          </button>
          <button
            onClick={onDeleteSelected}
            title={t("page:result.flowDeleteSelected")}
            className={`${btnClass} ${btnDefault}`}
            aria-label={t("page:result.flowDeleteSelected")}
            data-oid="flow-btn-delete">
            <Trash2 size={16} />
          </button>
          <div className="w-px h-6 bg-outline-variant mx-0.5" />
          <button
            onClick={onRelayout}
            title={t("page:result.flowResetLayout")}
            className={`${btnClass} ${btnDefault}`}
            aria-label={t("page:result.flowResetLayout")}
            data-oid="flow-btn-relayout">
            <LayoutGrid size={16} />
          </button>
          <button
            onClick={onFitView}
            title={t("page:result.flowFitView")}
            className={`${btnClass} ${btnDefault}`}
            aria-label={t("page:result.flowFitView")}
            data-oid="flow-btn-fitview">
            <Maximize size={16} />
          </button>
        </div>
      </Panel>


    </>
  );
}

/* ============================================================
 * FlowCanvas — 메인 캔버스
 * ========================================================== */

/**
 * FlowCanvas — React Flow 캔버스 내부 컴포넌트.
 * ReactFlowProvider 내부에서 렌더링되어 useReactFlow 등 훅 사용 가능.
 *
 * [Flow: Step 1 (rawNodes/rawEdges를 받아 커스텀 레이아웃) -> Step 2 (React Flow 렌더링) -> Step 3 (툴바 상호작용)]
 */
function FlowCanvas({ rawNodes, rawEdges, onNodeClick, dependencyEdges = [], jobId, drawingApiRef }) {
  const { t } = useTranslation();
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(true);
  const bgVariant = "lines";

  // [Flow: 노드 위치/크기 영속화 — localStorage에 저장하여 새로고침 후에도 드래그 위치 유지]
  // 헤딩 노드 ID가 heading-{index}로 결정론적이므로 새로고침 후에도 동일 ID로 매칭 가능
  const layoutStorageKey = jobId ? `flow-node-layout-${jobId}` : null;
  const saveLayoutTimerRef = useRef(null);
  const nodesRef = useRef(nodes);
  useEffect(() => { nodesRef.current = nodes; }, [nodes]);

  const reactFlow = useReactFlow();
  const { fitView, addNodes, deleteElements, screenToFlowPosition } = reactFlow;
  const noteIdCounter = useRef(0);

  // [Flow: 헤딩 노드 위치를 localStorage에서 복원 — 레이아웃 후 저장된 위치로 override, 크기는 계산값 유지]
  const restoreSavedLayout = useCallback((layoutedNodes) => {
    if (!layoutStorageKey) return layoutedNodes;
    try {
      const raw = localStorage.getItem(layoutStorageKey);
      if (!raw) return layoutedNodes;
      const savedMap = JSON.parse(raw); // { [nodeId]: { x, y } }
      return layoutedNodes.map(node => {
        const saved = savedMap[node.id];
        if (!saved) return node;
        return {
          ...node,
          position: { x: saved.x ?? node.position.x, y: saved.y ?? node.position.y },
        };
      });
    } catch { return layoutedNodes; }
  }, [layoutStorageKey]);

  // [Flow: 헤딩 노드 위치를 localStorage에 저장 — debounced (500ms), 크기는 저장하지 않음]
  const saveNodeLayout = useCallback((nodesToSave) => {
    if (!layoutStorageKey) return;
    if (saveLayoutTimerRef.current) clearTimeout(saveLayoutTimerRef.current);
    saveLayoutTimerRef.current = setTimeout(() => {
      // headingNode 타입만 저장 (noteNode는 useFlowDrawing에서 별도 관리)
      const layoutMap = {};
      for (const n of nodesToSave) {
        if (n.type === "headingNode") {
          layoutMap[n.id] = { x: n.position.x, y: n.position.y };
        }
      }
      try { localStorage.setItem(layoutStorageKey, JSON.stringify(layoutMap)); } catch { /* quota 무시 */ }
    }, 500);
  }, [layoutStorageKey]);

  // [Flow: 노드 드래그 종료 시 위치 저장]
  const onNodeDragStop = useCallback(() => {
    saveNodeLayout(nodesRef.current);
  }, [saveNodeLayout]);

  // [Flow: 드로잉/주석 상태 관리 — perfect-freehand 기반 곡선, 도형, 텍스트, 지우개]
  const drawing = useFlowDrawing(jobId, screenToFlowPosition);
  const isDrawingMode = drawing.tool !== "select";

  // [Flow: 스페이스바 누르고 있는 동안 pan 모드 강제 활성화]
  // 노드 인접/선택 상태에서도 스페이스바로 이동 커서(grab)가 되도록 한다.
  // 단, input/textarea/contenteditable에 포커스가 있으면 무시한다.
  const [isSpacePanning, setIsSpacePanning] = useState(false);

  useEffect(() => {
    const isEditableTarget = (target) => {
      if (!target) return false;
      const tag = target.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
      if (target.isContentEditable) return true;
      return false;
    };

    const handleKeyDown = (e) => {
      if (e.code !== "Space" && e.key !== " ") return;
      if (isEditableTarget(e.target)) return;
      e.preventDefault();
      setIsSpacePanning(true);
    };

    const handleKeyUp = (e) => {
      if (e.code !== "Space" && e.key !== " ") return;
      setIsSpacePanning(false);
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, []);

  // [Flow: drawingApiRef에 updateFromAgent 노출 — 에이전트 도구 결과로 로컬 상태 갱신]
  useEffect(() => {
    if (drawingApiRef) {
      drawingApiRef.current = { updateFromAgent: drawing.updateFromAgent };
    }
  }, [drawing.updateFromAgent, drawingApiRef]);

  // 주석 노트 텍스트 변경 핸들러 (NoteNode의 data.onTextChange 콜백)
  const handleNoteTextChange = useCallback((nodeId, newText) => {
    setNodes(nds => nds.map(n => n.id === nodeId ? { ...n, data: { ...n.data, text: newText } } : n));
  }, [setNodes]);

  // 주석 노트 추가 — 화면 중앙에 새 노트 노드 생성
  const handleAddNote = useCallback(() => {
    noteIdCounter.current += 1;
    const newNote = {
      id: `note-${Date.now()}-${noteIdCounter.current}`,
      type: "noteNode",
      position: { x: 200 + Math.random() * 100, y: 200 + Math.random() * 100 },
      data: {
        text: "",
        onTextChange: handleNoteTextChange,
      },
    };
    addNodes(newNote);
  }, [addNodes, handleNoteTextChange]);

  // [Flow: 서버에서 로드한 noteNodes를 React Flow 노드로 통합]
  useEffect(() => {
    if (!drawing.noteNodes || drawing.noteNodes.length === 0) return;
    const noteFlowNodes = drawing.noteNodes.map(n => ({
      id: n.id,
      type: "noteNode",
      position: { x: n.x, y: n.y },
      data: {
        text: n.text,
        width: n.width,
        height: n.height,
        onTextChange: handleNoteTextChange,
      },
    }));
    // 기존 noteNode 타입 노드를 제거하고 새로 추가 (중복 방지)
    setNodes(prev => {
      const nonNoteNodes = prev.filter(n => n.type !== "noteNode");
      return [...nonNoteNodes, ...noteFlowNodes];
    });
  }, [drawing.noteNodes, handleNoteTextChange, setNodes]);

  // [Flow: 서버에서 로드한 customEdges를 React Flow 엣지로 통합]
  useEffect(() => {
    if (!drawing.customEdges || drawing.customEdges.length === 0) return;
    const customFlowEdges = drawing.customEdges.map(e => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: "custom",
      data: { label: e.label || "" },
      updatable: true,
    }));
    // 기존 custom 타입 엣지를 제거하고 새로 추가 (중복 방지)
    setEdges(prev => {
      const nonCustomEdges = prev.filter(e => e.type !== "custom");
      return [...nonCustomEdges, ...customFlowEdges];
    });
  }, [drawing.customEdges, setEdges]);

  // Step 1+2: rawNodes/rawEdges에 커스텀 레이아웃 적용 + 저장된 위치 복원 + note/custom 엣지 유지
  useEffect(() => {
    if (!rawNodes.length) {
      setNodes([]);
      setEdges([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const layoutedNodes = calculateFlowLayout(rawNodes, rawEdges);
    // localStorage에서 저장된 위치로 override (새로고침 후에도 드래그 위치 유지)
    const restoredNodes = restoreSavedLayout(layoutedNodes);
    setNodes(prev => {
      const noteNodes = prev?.filter(n => n.type === "noteNode") || [];
      return [...restoredNodes, ...noteNodes];
    });
    // 파싱 계층/순서 엣지 + LLM 트리 에지(dependency) + 기존 custom 엣지 통합
    const dependencyFlowEdges = dependencyEdges.map(e => ({ ...e, type: "dependency", updatable: true }));
    setEdges(prev => {
      const customEdges = prev?.filter(e => e.type === "custom") || [];
      const allEdges = [
        ...rawEdges.map(e => ({ ...e, updatable: e.updatable ?? true })),
        ...dependencyFlowEdges,
        ...customEdges,
      ];
      return allEdges;
    });
    setLoading(false);
    setTimeout(() => fitView({ padding: 0.2, duration: 500 }), 100);
  }, [rawNodes, rawEdges, dependencyEdges, restoreSavedLayout, fitView, setNodes, setEdges]);

  // [Flow: onNodesChange 래핑 — NodeResizer의 dimensions 변경 시 저장 트리거]
  const handleNodesChange = useCallback((changes) => {
    onNodesChange(changes);
    // dimensions 변경(리사이즈)이 포함된 경우 저장
    if (changes.some(c => c.type === "dimensions" && c.resizing === false)) {
      // setNodes 후 최신 nodes를 가져오기 위해 ref 사용 + 약간 지연
      setTimeout(() => saveNodeLayout(nodesRef.current), 0);
    }
  }, [onNodesChange, saveNodeLayout]);

  // 선택된 노드/엣지 삭제
  const handleDeleteSelected = useCallback(() => {
    const selectedNodes = nodes.filter(n => n.selected);
    const selectedEdges = edges.filter(e => e.selected);
    if (!selectedNodes.length && !selectedEdges.length) return;
    deleteElements({ nodes: selectedNodes, edges: selectedEdges });
  }, [nodes, edges, deleteElements]);

  // 사용자 수동 연결 (onConnect + addEdge)
  const onConnect = useCallback((params) => {
    const newEdge = {
      ...params,
      id: `e-${params.source}-${params.target}-${Date.now()}`,
      type: "custom",
      animated: false,
      updatable: true,
      data: { label: "" },
    };
    setEdges(eds => addEdge(newEdge, eds));
  }, [setEdges]);

  // 엣지 재연결 (onReconnect + reconnectEdge)
  const onReconnect = useCallback((oldEdge, newConnection) => {
    setEdges(els => reconnectEdge(oldEdge, newConnection, els));
  }, [setEdges]);

  // 레이아웃 재배치 — 커스텀 레이아웃 재계산 (사용자가 드래그한 위치 리셋 + 저장된 위치도 클리어)
  const handleRelayout = useCallback(() => {
    if (!rawNodes.length) return;
    setLoading(true);
    // 저장된 위치 삭제 — 재배치 후에는 레이아웃 결과를 새 기준으로 사용
    if (layoutStorageKey) { try { localStorage.removeItem(layoutStorageKey); } catch { /* 무시 */ } }
    // 현재 사용자 추가 노트 노드는 유지
    const noteNodes = nodes.filter(n => n.type === "noteNode");
    const layoutedNodes = calculateFlowLayout(rawNodes, rawEdges);
    setNodes([...layoutedNodes, ...noteNodes]);
    setLoading(false);
    setTimeout(() => fitView({ padding: 0.2, duration: 500 }), 100);
  }, [rawNodes, rawEdges, nodes, setNodes, fitView, layoutStorageKey]);

  // 전체 보기
  const handleFitView = useCallback(() => {
    fitView({ padding: 0.2, duration: 500 });
  }, [fitView]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center" data-oid="flow-loading">
        <Loader2 className="animate-spin text-primary" size={24} />
      </div>
    );
  }

  if (!nodes.length) {
    return (
      <div className="h-full flex items-center justify-center text-on-surface-variant" data-oid="flow-empty">
        {t("page:result.flowEmpty")}
      </div>
    );
  }

  // Step 3: React Flow 렌더링
  const bgVariantEnum = bgVariant === "lines" ? BackgroundVariant.Lines
    : bgVariant === "cross" ? BackgroundVariant.Cross
    : BackgroundVariant.Dots;

  return (
    <>
      {/* 전역 SVG marker 정의 — 엣지 화살표용. React Flow는 markerEnd를 URL 문자열로 참조. */}
      <svg style={{ position: "absolute", width: 0, height: 0 }}>
        <defs>
          <marker
            id="arrow-closed"
            markerWidth="10"
            markerHeight="10"
            refX="9"
            refY="5"
            orient="auto-start-reverse"
            markerUnits="strokeWidth">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#b0b0b0" />
          </marker>
          <marker
            id="arrow-next"
            markerWidth="10"
            markerHeight="10"
            refX="9"
            refY="5"
            orient="auto-start-reverse"
            markerUnits="strokeWidth">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#6366f1" />
          </marker>
        </defs>
      </svg>
      <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodesChange={handleNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      onReconnect={onReconnect}
      onNodeClick={(_, node) => onNodeClick?.(node)}
      onNodeDragStop={onNodeDragStop}
      fitView
      proOptions={{ hideAttribution: true }}
      defaultEdgeOptions={{ type: "custom" }}
      nodesDraggable={!isDrawingMode && !isSpacePanning}
      panOnDrag={!isDrawingMode || isSpacePanning}
      selectionOnDrag={!isDrawingMode && !isSpacePanning}
      style={{ cursor: isSpacePanning ? "grab" : undefined }}
      data-oid="flow-canvas">
      <Background variant={bgVariantEnum} gap={16} size={1} />
      <Controls position="bottom-left" className="!flex" />
      <MiniMap
        className="hidden md:block"
        nodeColor={n => n.type === "noteNode" ? "#f59e0b" : "#6366f1"}
        nodeStrokeColor="#fff"
        nodeBorderRadius={4}
        maskColor="rgba(0,0,0,0.1)"
        pannable
        zoomable
      />
      <FlowToolbar
        onAddNote={handleAddNote}
        onDeleteSelected={handleDeleteSelected}
        onRelayout={handleRelayout}
        onFitView={handleFitView}
      />
      {/* [Flow: 드로잉 오버레이 — ViewportPortal로 pan/zoom 자동 따라감] */}
      <DrawingOverlay
        isActive={isDrawingMode}
        paths={drawing.paths}
        currentPathD={drawing.getCurrentPathD()}
        strokeColor={drawing.strokeColor}
        strokeWidth={drawing.strokeWidth}
        isShapeMode={drawing.isShapeMode}
        textAnnotations={drawing.textAnnotations}
        onPointerDown={drawing.startDrawing}
        onPointerMove={drawing.continueDrawing}
        onPointerUp={drawing.endDrawing}
        onDeleteText={drawing.deleteTextAnnotation}
      />
      {/* [Flow: 드로잉 도구 툴바 — 하단 중앙 Panel] */}
      <DrawingToolbar
        tool={drawing.tool}
        onToolChange={drawing.setTool}
        strokeColor={drawing.strokeColor}
        onStrokeColorChange={drawing.setStrokeColor}
        strokeWidth={drawing.strokeWidth}
        onStrokeWidthChange={drawing.setStrokeWidth}
        shapeType={drawing.shapeType}
        onShapeTypeChange={drawing.setShapeType}
        onUndo={drawing.undo}
        onClear={drawing.clear}
        canUndo={drawing.paths.length > 0 || drawing.textAnnotations.length > 0}
      />
    </ReactFlow>
    </>
  );
}

/* ============================================================
 * FlowViewer — 외부 컴포넌트 (ReactFlowProvider 래퍼)
 * ========================================================== */

/**
 * FlowViewer — 마크다운 문서의 헤딩 구조를 React Flow 그래프로 시각화.
 * ReactFlowProvider로 감싸서 내부 훅(useReactFlow 등) 사용 가능하게 함.
 *
 * @param {Object} props
 * @param {string} [props.markdown] - 시각화할 마크다운 문자열 (단일 파일)
 * @param {Array<{ filename: string, markdown: string }>} [props.files] - 다중 파일 마크다운 배열 (files가 있으면 markdown보다 우선)
 * @param {Function} [props.onNodeClick] - 노드 클릭 콜백 (node) => void
 * @param {Array} [props.dependencyEdges] - AI 의존성 에지 배열 [{ source, target, data: { reason } }]
 * @param {string} [props.filename] - 제목 fallback용 파일명
 * @returns {JSX.Element} 플로우 뷰 컴포넌트
 */
const FlowViewer = forwardRef(function FlowViewer({ markdown, files, onNodeClick, dependencyEdges = [], jobId, filename }, ref) {
  const { t } = useTranslation();
  const drawingApiRef = useRef(null);

  // [Flow: 마크다운에서 제목/노드/에지 추출 후 FlowCanvas에 전달]
  // files prop이 있으면 다중 파일 파싱, 없으면 단일 markdown 파싱
  const rawFlowData = useMemo(() => {
    if (files && files.length > 0) {
      return parseMultiFileMarkdownToFlow(files);
    }
    return parseMarkdownToFlow(markdown || "");
  }, [markdown, files]);
  const displayTitle = rawFlowData.title || filename || t("page:result.flowView") || jobId;

  // [Flow: useImperativeHandle로 updateFromAgent 메서드를 외부에 노출]
  useImperativeHandle(ref, () => ({
    updateFromAgent: (data) => {
      drawingApiRef.current?.updateFromAgent?.(data);
    },
  }), []);

  return (
    <div className="h-full flex flex-col" data-oid="flow-viewer">
      {/* 헤더 — 원문 제목을 상단에 크게 표시 */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-outline-variant bg-surface-container-lowest" data-oid="flow-title-bar">
        <Workflow size={20} className="text-primary" />
        <h2 className="text-lg font-bold text-on-surface truncate" title={displayTitle}>
          {displayTitle}
        </h2>
      </div>
      {/* React Flow 캔버스 */}
      <div className="flex-1 min-h-0">
        <ReactFlowProvider>
          <FlowCanvas
            rawNodes={rawFlowData.nodes}
            rawEdges={rawFlowData.edges}
            onNodeClick={onNodeClick}
            dependencyEdges={dependencyEdges}
            jobId={jobId}
            drawingApiRef={drawingApiRef}
          />
        </ReactFlowProvider>
      </div>
    </div>
  );
});

export default FlowViewer;
