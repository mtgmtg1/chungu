import { Position } from "@xyflow/react";

/**
 * heading 노드 배열에 대해 세로 흐름 + 왼쪽 들여쓰기 레이아웃을 계산한다.
 *
 * [Flow: Step 1 (옵션/상수 초기화) -> Step 2 (각 노드 높이 추정)
 *       -> Step 3 (depth 기반 x좌표, 순서 기반 y좌표 계산)
 *       -> Step 4 (레이아웃이 적용된 노드 배열 반환)]
 *
 * @param {Array} nodes - headingNode 객체 배열 (data.depth, data.label, data.contentPreview 포함)
 * @param {Object} [options] - 레이아웃 옵션
 * @param {number} [options.width=360] - 노드 고정 너비
 * @param {number} [options.indent=32] - depth당 들여쓰기 픽셀
 * @param {number} [options.gap=24] - 노드 간 세로 간격
 * @param {number} [options.marginLeft=16] - 좌측 여백
 * @param {number} [options.marginTop=24] - 상단 여백
 * @param {number} [options.titleCharsPerLine=28] - 제목 한 줄당 문자 수 추정
 * @param {number} [options.previewCharsPerLine=30] - 미리보기 한 줄당 문자 수 추정
 * @returns {Array} position/width/height/draggable이 설정된 노드 배열
 */
export function calculateFlowLayout(nodes, options = {}) {
  const {
    width = 360,
    indent = 32,
    gap = 24,
    marginLeft = 16,
    marginTop = 24,
    titleCharsPerLine = 28,
    previewCharsPerLine = 30,
  } = options;

  let y = marginTop;

  return nodes.map((node) => {
    const label = node.data.label || "";
    const preview = node.data.contentPreview || "";

    const titleLines = Math.min(2, Math.max(1, Math.ceil(label.length / titleCharsPerLine)));
    const previewLines = preview ? Math.min(3, Math.max(1, Math.ceil(preview.length / previewCharsPerLine))) : 0;

    const height = 48 + 20 * titleLines + 16 * previewLines;
    const x = marginLeft + (node.data.depth || 0) * indent;

    const layoutedNode = {
      ...node,
      position: { x, y },
      width,
      height,
      data: { ...node.data, width, height },
      draggable: false,
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    };

    y += height + gap;
    return layoutedNode;
  });
}
