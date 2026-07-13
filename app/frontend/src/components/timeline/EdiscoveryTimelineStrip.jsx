// [Flow: Step 1 (React Chrono items + 현재 활성 인덱스 + 선택 콜백 수신)
//       -> Step 2 (타임라인 헤더 라벨 렌더링) -> Step 3 (수직 리사이즈 핸들로 높이 조절)
//       -> Step 4 (React Chrono HORIZONTAL_ALL 대시보드로 전체 타임라인 렌더링)]
// e-Discovery Timeline의 하단 타임라인 영역만 분리한 컴포넌트.
// 별도 개발 페이지에서 직접 브라우저 디버깅을 위해 재사용 가능하도록 분리했다.

import { Chrono } from "react-chrono";

/** HORIZONTAL 모드에서 카드 하나의 너비/높이 (px). */
const CARD_WIDTH = 200;
const CARD_HEIGHT = 120;
const ITEM_WIDTH = 220;
const MEDIA_HEIGHT = 60;

/**
 * EdiscoveryTimelineStrip — e-Discovery 하단 타임라인 스트립.
 * HORIZONTAL_ALL 모드로 모든 카드를 한 줄에 보여주며, 카드 높이는 CSS로 강제 제한한다.
 *
 * @param {Object} props
 * @param {Array<Object>} props.items - React Chrono items
 * @param {number} props.activeItemIndex - 현재 활성 아이템 인덱스
 * @param {Function} props.onItemSelected - 아이템 선택 콜백 (selected) => void
 * @param {number} props.timelineHeight - 타임라인 영역 높이 (px)
 * @param {Function} props.onResizePointerDown - 수직 리사이즈 핸들 pointerDown 콜백
 * @param {string} props.title - 타임라인 헤더 라벨
 */
export default function EdiscoveryTimelineStrip({
  items,
  activeItemIndex,
  onItemSelected,
  timelineHeight,
  onResizePointerDown,
  title,
}) {
  return (
    <div className="flex flex-col flex-shrink-0" style={{ height: timelineHeight }}>
      {/* ===== 중앙-하단 수직 리사이저 ===== */}
      <div
        className="h-2 flex-shrink-0 cursor-row-resize bg-outline-variant hover:bg-primary transition-colors border-y border-transparent"
        onPointerDown={onResizePointerDown}
        title={title}
        data-oid="ediscovery-vertical-resizer"
      />

      {/* ===== React Chrono Horizontal All Dashboard ===== */}
      <div
        className="flex-1 min-h-0 relative bg-surface-container-lowest"
        data-oid="ediscovery-chrono-section"
      >
        {/* 타임라인 헤더 라벨 */}
        {items.length > 0 && (
          <div className="absolute top-1 left-2 z-10 text-[10px] font-bold uppercase tracking-wide text-on-surface-variant bg-surface-container-lowest/80 px-2 py-0.5 rounded">
            {title}
          </div>
        )}

        {items.length > 0 && (
          <div className="absolute inset-0 overflow-auto" data-oid="ediscovery-chrono">
            <Chrono
              key={items.length > 0 ? "chrono-loaded" : "chrono-loading"}
              items={items}
              mode="HORIZONTAL"
              showAllCardsHorizontal
              cardWidth={CARD_WIDTH}
              cardHeight={CARD_HEIGHT}
              itemWidth={ITEM_WIDTH}
              mediaHeight={MEDIA_HEIGHT}
              mediaSettings={{ align: "center", imageFit: "cover" }}
              timelinePointDimension={12}
              timelinePointShape="circle"
              activeItemIndex={activeItemIndex}
              focusActiveItemOnLoad
              onItemSelected={onItemSelected}
              highlightCardsOnHover
              useReadMore={false}
              theme={{
                primary: "#2563eb",
                secondary: "#f59e0b",
                cardBgColor: "#ffffff",
                cardTitleColor: "#111827",
                cardSubtitleColor: "#6b7280",
                cardDetailsColor: "#374151",
                titleColor: "#6b7280",
              }}
              fontSizes={{
                cardTitle: "0.7rem",
                cardSubtitle: "0.6rem",
                cardDetailedText: "0.65rem",
                title: "0.6rem",
              }}
              classNames={{
                card: "ediscovery-chrono-card max-h-[150px] overflow-hidden",
                cardTitle: "ediscovery-chrono-card-title",
                cardSubTitle: "ediscovery-chrono-card-subtitle",
                cardDetailedText: "ediscovery-chrono-card-text line-clamp-3",
                controls: "ediscovery-chrono-controls",
                activeProgressBar: "ediscovery-chrono-progress",
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
