// [Flow: Step 1 (마크다운 파싱 + elk 레이아웃) -> Step 2 (React Flow 렌더링)
//       -> Step 3 (툴바: 주석 추가 / 연결 / 삭제 / 배경 전환 / 다크모드 / 레이아웃 재배치)
//       -> Step 4 (노드 클릭 시 콜백)]
// 마크다운 문서의 헤딩 구조를 React Flow 캔버스에 논리 흐름 그래프로 시각화.
// 계층 구조는 실선(hierarchy) 엣지, AI 의존성은 점선(dependency) 엣지로 표현.
// 사용자는 주석 노트 추가, 수동 연결, 엣지 재연결, 선택 삭제, 배경 전환 가능.
import { useCallback, useEffect, useRef, useState } from "react";
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
  EdgeLabelRenderer,
} from "@xyflow/react";
import {
  Loader2,
  Workflow,
  StickyNote,
  Trash2,
  LayoutGrid,
  Maximize,
  Circle,
  Plus,
} from "lucide-react";
import { parseMarkdownToFlow } from "../utils/markdownToFlow";
import { calculateElkLayout } from "../utils/elkLayout";

/* ============================================================
 * 커스텀 노드 컴포넌트
 * ========================================================== */

/**
 * 헤딩 노드 컴포넌트 — 제목 + H레벨 배지 + 내용 미리보기.
 * React Flow 커스텀 노드로 등록되어 nodeTypes에 매핑됨.
 * 사용자가 수동 연결을 할 수 있도록 Handle의 isConnectable=true.
 */
function HeadingNode({ data, selected }) {
  return (
    <div
      className={`bg-white rounded-lg border-2 shadow-sm px-4 py-3 w-[280px] transition-all ${
        selected ? "border-primary shadow-md ring-2 ring-primary/20" : "border-outline-variant"
      }`}
    >
      <Handle type="target" position={Position.Top} isConnectable={true} />
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs font-bold px-1.5 py-0.5 rounded bg-primary/10 text-primary">
          H{data.level}
        </span>
        <span className="font-semibold text-sm text-on-surface line-clamp-2">
          {data.label}
        </span>
      </div>
      {data.contentPreview && (
        <p className="text-xs text-on-surface-variant line-clamp-3 mt-1">
          {data.contentPreview}
        </p>
      )}
      <Handle type="source" position={Position.Bottom} isConnectable={true} />
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
      className={`rounded-lg border-2 shadow-sm px-3 py-2 w-[200px] min-h-[80px] transition-all ${
        selected
          ? "bg-primary-fixed border-primary shadow-md ring-2 ring-primary/20"
          : "bg-surface-container-low border-primary-fixed-dim"
      }`}
    >
      <Handle type="target" position={Position.Top} isConnectable={true} />
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
          className="w-full text-xs text-on-surface bg-transparent border-none outline-none resize-none min-h-[60px] nodrag nopan"
          placeholder="메모를 입력하세요…"
        />
      ) : (
        <p
          onDoubleClick={() => setEditing(true)}
          className="text-xs text-on-surface whitespace-pre-wrap break-words cursor-text min-h-[60px]"
        >
          {text || <span className="text-on-surface-variant italic">더블클릭하여 편집</span>}
        </p>
      )}
      <Handle type="source" position={Position.Bottom} isConnectable={true} />
    </div>
  );
}

const nodeTypes = { headingNode: HeadingNode, noteNode: NoteNode };

/* ============================================================
 * 커스텀 엣지 컴포넌트
 * ========================================================== */

/**
 * 계층 구조 엣지 — 실선 (부모-자식 heading 관계).
 * BaseEdge + getBezierPath로 곡선 패스 렌더링.
 */
function HierarchyEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd, selected }) {
  const [edgePath] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  return (
    <BaseEdge
      id={id}
      path={edgePath}
      style={{ ...style, strokeWidth: selected ? 3 : 2, stroke: selected ? "#6366f1" : (style?.stroke || "#b0b0b0") }}
      markerEnd={markerEnd || "url(#arrow-closed)"}
    />
  );
}

/**
 * 의존성 엣지 — 점선 + 호버 시 reason 툴팁.
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
          strokeDasharray: "5 5",
          stroke: selected ? "#f59e0b" : (style?.stroke || "#f59e0b"),
          strokeWidth: selected ? 3 : 2,
        }}
        markerEnd={markerEnd}
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

const edgeTypes = { hierarchy: HierarchyEdge, dependency: DependencyEdge, custom: CustomEdge };

/* ============================================================
 * 툴바 컴포넌트 (Panel 오버레이)
 * ========================================================== */

const BG_VARIANTS = [
  { key: "dots", icon: Circle, label: "Dots" },
  { key: "lines", icon: LayoutGrid, label: "Lines" },
  { key: "cross", icon: Plus, label: "Cross" },
];

/**
 * FlowToolbar — React Flow Panel 오버레이에 배치된 툴바.
 * 주석 추가, 선택 삭제, 배경 전환, 레이아웃 재배치, 전체 보기 버튼 제공.
 */
function FlowToolbar({ onAddNote, onDeleteSelected, bgVariant, setBgVariant, onRelayout, onFitView }) {
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

      {/* 우측 상단: 배경 전환 */}
      <Panel position="top-right" className="!m-2">
        <div className="flex flex-wrap items-center justify-end gap-1 bg-surface-container-lowest rounded-lg shadow-md border border-outline-variant p-1 max-w-[calc(100vw-1rem)]">
          {BG_VARIANTS.map(v => {
            const Icon = v.icon;
            return (
              <button
                key={v.key}
                onClick={() => setBgVariant(v.key)}
                title={v.label}
                className={`${btnClass} ${bgVariant === v.key ? btnActive : btnDefault}`}
                aria-label={v.label}
                data-oid={`flow-btn-bg-${v.key}`}>
                <Icon size={16} />
              </button>
            );
          })}
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
 * [Flow: Step 1 (마크다운 파싱) -> Step 2 (elkjs 레이아웃 계산) -> Step 3 (React Flow 렌더링) -> Step 4 (툴바 상호작용)]
 */
function FlowCanvas({ markdown, onNodeClick, dependencyEdges = [] }) {
  const { t } = useTranslation();
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(true);
  const [bgVariant, setBgVariant] = useState("dots");
  const [rawFlowData, setRawFlowData] = useState({ nodes: [], edges: [] });

  const reactFlow = useReactFlow();
  const { fitView, addNodes, deleteElements, screenToFlowPosition } = reactFlow;
  const noteIdCounter = useRef(0);

  // Step 1+2: 마크다운 파싱 + elkjs 레이아웃 계산
  useEffect(() => {
    if (!markdown) {
      setLoading(false);
      return;
    }
    setLoading(true);
    const { nodes: rawNodes, edges: rawEdges } = parseMarkdownToFlow(markdown);
    setRawFlowData({ nodes: rawNodes, edges: rawEdges });
    calculateElkLayout(rawNodes, rawEdges).then(layoutedNodes => {
      setNodes(layoutedNodes);
      const allEdges = [
        ...rawEdges.map(e => ({ ...e, updatable: true })),
        ...dependencyEdges.map(e => ({ ...e, type: "dependency", updatable: true })),
      ];
      setEdges(allEdges);
      setLoading(false);
    });
  }, [markdown, dependencyEdges]);

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

  // 레이아웃 재배치 — elkjs 재실행 (사용자가 드래그한 위치 리셋)
  const handleRelayout = useCallback(() => {
    if (!rawFlowData.nodes.length) return;
    setLoading(true);
    // 현재 사용자 추가 노트 노드는 유지
    const noteNodes = nodes.filter(n => n.type === "noteNode");
    calculateElkLayout(rawFlowData.nodes, rawFlowData.edges).then(layoutedNodes => {
      setNodes([...layoutedNodes, ...noteNodes]);
      setLoading(false);
      setTimeout(() => fitView({ padding: 0.2, duration: 500 }), 100);
    });
  }, [rawFlowData, nodes, setNodes, fitView]);

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
        </defs>
      </svg>
      <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      onReconnect={onReconnect}
      onNodeClick={(_, node) => onNodeClick?.(node)}
      fitView
      proOptions={{ hideAttribution: true }}
      defaultEdgeOptions={{ type: "custom" }}
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
        bgVariant={bgVariant}
        setBgVariant={setBgVariant}
        onRelayout={handleRelayout}
        onFitView={handleFitView}
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
 * @param {string} props.markdown - 시각화할 마크다운 문자열
 * @param {Function} [props.onNodeClick] - 노드 클릭 콜백 (node) => void
 * @param {Array} [props.dependencyEdges] - AI 의존성 에지 배열 [{ source, target, data: { reason } }]
 * @returns {JSX.Element} 플로우 뷰 컴포넌트
 */
export default function FlowViewer({ markdown, onNodeClick, dependencyEdges = [] }) {
  const { t } = useTranslation();

  return (
    <div className="h-full flex flex-col" data-oid="flow-viewer">
      {/* 헤더 툴바 */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-outline-variant bg-surface-container-lowest">
        <Workflow size={16} className="text-primary" />
        <span className="text-sm font-medium text-on-surface">{t("page:result.flowView")}</span>
        <span className="text-xs text-on-surface-variant ml-2">{t("page:result.flowHint")}</span>
      </div>
      {/* React Flow 캔버스 */}
      <div className="flex-1 min-h-0">
        <ReactFlowProvider>
          <FlowCanvas
            markdown={markdown}
            onNodeClick={onNodeClick}
            dependencyEdges={dependencyEdges}
          />
        </ReactFlowProvider>
      </div>
    </div>
  );
}
