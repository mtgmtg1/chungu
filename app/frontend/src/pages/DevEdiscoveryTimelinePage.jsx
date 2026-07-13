// [Flow: Step 1 (개발 mock 활성화) -> Step 2 (SAMPLE_EDISCOVERY_GRAPH 노드를 Chrono items로 변환)
//       -> Step 3 (EdiscoveryTimelineStrip만 전체 화면에 렌더링)
//       -> Step 4 (Playwright 등으로 브라우저에서 직접 타임라인 UI를 디버깅)]
// e-Discovery Timeline 하단 스트립만 별도로 개발/디버깅하기 위한 개발 전용 페이지.
// import.meta.env.DEV일 때만 라우팅되며 production 빌드에는 포함되지 않는다.

import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import EdiscoveryTimelineStrip from "../components/timeline/EdiscoveryTimelineStrip.jsx";
import { buildChronoItem } from "../components/timeline/EdiscoveryTimelinePanel.jsx";
import { SAMPLE_EDISCOVERY_GRAPH } from "../dev/ediscoverySampleData.js";
import { enableDevMock } from "../api.js";

/** 타임라인 높이 기본값 (px) — EdiscoveryTimelinePanel과 동일. */
const DEFAULT_TIMELINE_HEIGHT = 384;

/** 타임라인 높이 최소/최대 (px) — EdiscoveryTimelinePanel과 동일. */
const MIN_TIMELINE_HEIGHT = 160;
const MAX_TIMELINE_HEIGHT = 600;

/**
 * DevEdiscoveryTimelinePage — e-Discovery 타임라인 스트립만 전체 화면에서 디버깅하는 개발 페이지.
 *
 * 상단에 간단한 안내 배너만 두고, 나머지 영역을 EdiscoveryTimelineStrip이 차지한다.
 */
export default function DevEdiscoveryTimelinePage() {
  const { t } = useTranslation();

  // 개발 환경에서 API mock 활성화
  useEffect(() => {
    enableDevMock(true);
  }, []);

  // Chrono items 준비 — buildChronoItem 재사용
  const chronoItems = useMemo(() => {
    const previewData = { sourceFiles: [] };
    return (SAMPLE_EDISCOVERY_GRAPH.nodes || [])
      .filter((n) => n.type !== "swimlane")
      .map((node) => buildChronoItem(node, previewData, t));
  }, [t]);

  // 수직 리사이즈 상태
  const [timelineHeight, setTimelineHeight] = useState(DEFAULT_TIMELINE_HEIGHT);
  const resizeStartRef = useRef({ y: 0, height: DEFAULT_TIMELINE_HEIGHT });

  const [activeItemIndex, setActiveItemIndex] = useState(0);

  const handleItemSelected = (selected) => {
    setActiveItemIndex(selected.index);
  };

  const handleResizeMove = (e) => {
    const delta = resizeStartRef.current.y - e.clientY;
    const next = Math.max(
      MIN_TIMELINE_HEIGHT,
      Math.min(MAX_TIMELINE_HEIGHT, resizeStartRef.current.height + delta)
    );
    setTimelineHeight(next);
  };

  const handleResizeUp = () => {
    window.removeEventListener("pointermove", handleResizeMove);
    window.removeEventListener("pointerup", handleResizeUp);
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  };

  const handleResizeDown = (e) => {
    e.preventDefault();
    resizeStartRef.current = { y: e.clientY, height: timelineHeight };
    window.addEventListener("pointermove", handleResizeMove);
    window.addEventListener("pointerup", handleResizeUp);
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";
  };

  return (
    <div className="h-screen w-screen flex flex-col" data-oid="dev-ediscovery-timeline-page">
      {/* 개발 전용 안내 배너 */}
      <div className="flex items-center gap-2 px-4 py-2 bg-amber-50 border-b border-amber-200 text-amber-800 text-xs flex-shrink-0">
        <span className="font-bold">[DEV]</span>
        <span>e-Discovery Timeline Strip 단독 디버깅 페이지 — items: {chronoItems.length}개</span>
      </div>

      {/* 타임라인 스트립 전체 영역 */}
      <div className="flex-1 min-h-0 flex flex-col">
        <EdiscoveryTimelineStrip
          items={chronoItems}
          activeItemIndex={activeItemIndex}
          onItemSelected={handleItemSelected}
          timelineHeight={timelineHeight}
          onResizePointerDown={handleResizeDown}
          title={t("page:result.ediscoveryCourtroomTimeline")}
        />
      </div>
    </div>
  );
}
