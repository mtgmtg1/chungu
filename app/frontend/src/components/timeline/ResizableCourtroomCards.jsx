// [Flow: Step 1 (분류된 양측 주장/증거 수신) -> Step 2 (react-resizable-panels PanelGroup로 좌우 분할)
//       -> Step 3 (PanelResizeHandle로 양측 카드 크기를 드래그 조절) -> Step 4 (카드 클릭 시 onNodeClick 호출)]
// e-Discovery Timeline 중앙의 CLIENT ARGUMENTS / OPPONENT REBUTTALS 카드 쌍.
// 양 카드 사이 끝부분을 드래그하여 상대적 너비를 조절할 수 있다.

import { useTranslation } from "react-i18next";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import CourtroomColumn from "./CourtroomColumn.jsx";

/**
 * ResizableCourtroomCards — 중앙 양측 주장/증거 카드를 수평 드래그 리사이즈로 배치.
 *
 * @param {Object} props
 * @param {{ plaintiff: { claims: Array<Object>, evidence: Array<Object> }, defendant: { claims: Array<Object>, evidence: Array<Object> } }} props.classifiedSides
 * @param {Function} props.onNodeClick - 카드 클릭 시 호출 (node) => void
 */
export default function ResizableCourtroomCards({ classifiedSides, onNodeClick }) {
  const { t } = useTranslation();

  return (
    <PanelGroup
      direction="horizontal"
      className="h-full w-full flex min-h-0 gap-3"
      data-oid="ediscovery-courtroom-cards"
    >
      <Panel minSize={20} defaultSize={50} className="min-h-0">
        <CourtroomColumn
          side="plaintiff"
          headerKey="page:result.ediscoveryClientArguments"
          claims={classifiedSides.plaintiff.claims}
          evidence={classifiedSides.plaintiff.evidence}
          onNodeClick={onNodeClick}
        />
      </Panel>

      <PanelResizeHandle
        className="w-2 flex-shrink-0 cursor-col-resize bg-outline-variant/50 hover:bg-primary transition-colors rounded-full mx-1"
        title={t("page:result.ediscoveryResizePanels")}
        data-oid="ediscovery-cards-resize-handle"
      />

      <Panel minSize={20} defaultSize={50} className="min-h-0">
        <CourtroomColumn
          side="defendant"
          headerKey="page:result.ediscoveryOpponentRebuttals"
          claims={classifiedSides.defendant.claims}
          evidence={classifiedSides.defendant.evidence}
          onNodeClick={onNodeClick}
        />
      </Panel>
    </PanelGroup>
  );
}
