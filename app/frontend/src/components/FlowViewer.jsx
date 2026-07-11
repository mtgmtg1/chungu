// [Flow: Step 1 (마크다운 파싱 + elk 레이아웃) -> Step 2 (React Flow 렌더링)
//       -> Step 3 (툴바 컨트롤) -> Step 4 (노드 클릭 시 콜백)]
// 마크다운 문서의 헤딩 구조를 React Flow 캔버스에 논리 흐름 그래프로 시각화.
// 계층 구조는 실선(hierarchy) 엣지, AI 의존성은 점선(dependency) 엣지로 표현.
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  Handle,
  Position,
  BaseEdge,
  getBezierPath,
  EdgeLabelRenderer,
} from "@xyflow/react";
import { Loader2, Workflow } from "lucide-react";
import { parseMarkdownToFlow } from "../utils/markdownToFlow";
import { calculateElkLayout } from "../utils/elkLayout";

/**
 * 헤딩 노드 컴포넌트 — 제목 + H레벨 배지 + 내용 미리보기.
 * React Flow 커스텀 노드로 등록되어 nodeTypes에 매핑됨.
 */
function HeadingNode({ data }) {
  return (
    <div className="bg-white rounded-lg border-2 border-outline-variant shadow-sm px-4 py-3 w-[280px]">
      <Handle type="target" position={Position.Top} isConnectable={false} />
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
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  );
}

/**
 * 계층 구조 엣지 — 실선 (부모-자식 heading 관계).
 * BaseEdge + getBezierPath로 곡선 패스 렌더링.
 */
function HierarchyEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd }) {
  const [edgePath] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  return <BaseEdge id={id} path={edgePath} style={style} markerEnd={markerEnd} />;
}

/**
 * 의존성 엣지 — 점선 + 호버 시 reason 툴팁.
 * EdgeLabelRenderer 포털로 SVG 위에 HTML 툴팁을 별도 레이어에 렌더링.
 */
function DependencyEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, data, markerEnd }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={{ ...style, strokeDasharray: "5 5", stroke: "#f59e0b" }}
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

const nodeTypes = { headingNode: HeadingNode };
const edgeTypes = { hierarchy: HierarchyEdge, dependency: DependencyEdge };

/**
 * FlowCanvas — React Flow 캔버스 내부 컴포넌트.
 * ReactFlowProvider 내부에서 렌더링되어 useReactFlow 등 훅 사용 가능.
 *
 * [Flow: Step 1 (마크다운 파싱) -> Step 2 (elkjs 레이아웃 계산) -> Step 3 (React Flow 렌더링)]
 */
function FlowCanvas({ markdown, onNodeClick, dependencyEdges = [] }) {
  const { t } = useTranslation();
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [loading, setLoading] = useState(true);
  const { fitView } = useReactFlow();

  useEffect(() => {
    if (!markdown) {
      setLoading(false);
      return;
    }
    setLoading(true);
    // Step 1: 마크다운 → 노드/에지 파싱
    const { nodes: rawNodes, edges: rawEdges } = parseMarkdownToFlow(markdown);
    // Step 2: elkjs 레이아웃 계산
    calculateElkLayout(rawNodes, rawEdges).then(layoutedNodes => {
      setNodes(layoutedNodes);
      // 계층 에지 + 의존성 에지 병합
      const allEdges = [
        ...rawEdges,
        ...dependencyEdges.map(e => ({ ...e, type: "dependency" })),
      ];
      setEdges(allEdges);
      setLoading(false);
    });
  }, [markdown, dependencyEdges]);

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
  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={(_, node) => onNodeClick?.(node)}
      fitView
      proOptions={{ hideAttribution: true }}
    >
      <Background />
      <Controls />
      <MiniMap nodeColor="#6366f1" />
    </ReactFlow>
  );
}

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
