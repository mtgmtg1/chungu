// [Flow: Step 1 (perfect-freehand 스트로크 생성) -> Step 2 (SVG path d 속성 변환) -> Step 3 (도형 path 생성 / 지우개 거리 계산)]
// koda-learn 프로젝트의 드로잉 유틸리티를 이식 — perfect-freehand 기반 부드러운 곡선 + 도형 SVG path 생성.
import { getStroke } from "perfect-freehand";

/**
 * 드로잉 도구 타입 — 펜 / 형광펜 / 지우개 / 텍스트 / 도형.
 * @typedef {"pen" | "highlighter" | "eraser" | "text" | "shape"} DrawingTool
 */

/**
 * 도형 타입 — 선 / 화살표 / 사각형 / 원.
 * @typedef {"line" | "arrow" | "rectangle" | "circle"} ShapeType
 */

/**
 * 드로잉 경로 — SVG path d 속성 + 스타일 메타데이터.
 * @typedef {Object} DrawingPath
 * @property {string} [id] - 서버 저장 시 발급되는 ID
 * @property {string} d - SVG path d 속성
 * @property {string} stroke - 선 색상
 * @property {number} strokeWidth - 선 굵기
 * @property {"path" | "shape"} [type] - 경로 유형
 * @property {ShapeType} [shapeType] - 도형 타입 (type이 "shape"일 때)
 */

/**
 * 텍스트 주석 — 캔버스 빈 공간에 배치된 텍스트.
 * @typedef {Object} TextAnnotation
 * @property {string} id - 고유 ID
 * @property {number} x - flow 좌표계 x 위치
 * @property {number} y - flow 좌표계 y 위치
 * @property {string} text - 주석 텍스트
 * @property {number} fontSize - 폰트 크기
 * @property {string} color - 텍스트 색상
 */

/**
 * 2D 점 — x, y 좌표 + 선택적 압력.
 * @typedef {Object} Point
 * @property {number} x
 * @property {number} y
 * @property {number} [pressure]
 */

// perfect-freehand 기본 옵션 — 부드러운 곡선, 둥근 끝
const DEFAULT_FREEHAND_OPTIONS = {
  size: 4,
  thinning: 0.5,
  smoothing: 0.5,
  streamline: 0.5,
  easing: (t) => t,
  start: { taper: 0, cap: true },
  end: { taper: 0, cap: true },
};

/**
 * perfect-freehand 스트로크 결과를 SVG path d 속성으로 변환.
 * @param {number[][]} stroke - getStroke() 반환값 (외곽선 점 배열)
 * @returns {string} SVG path d 속성 문자열
 */
function getSvgPathFromStroke(stroke) {
  if (!stroke.length) return "";
  const d = stroke.reduce(
    (acc, [x0, y0], i, arr) => {
      const [x1, y1] = arr[(i + 1) % arr.length];
      acc.push(x0, y0, (x0 + x1) / 2, (y0 + y1) / 2);
      return acc;
    },
    ["M", ...stroke[0], "Q"],
  );
  d.push("Z");
  return d.join(" ");
}

/**
 * perfect-freehand로 부드러운 곡선 SVG path 생성.
 * @param {Point[]} points - 드로잉 포인트 배열
 * @param {number} strokeWidth - 선 굵기
 * @returns {string} SVG path d 속성
 */
export function getFreehandPath(points, strokeWidth) {
  const stroke = getStroke(
    points.map((p) => [p.x, p.y, p.pressure || 0.5]),
    { ...DEFAULT_FREEHAND_OPTIONS, size: strokeWidth },
  );
  return getSvgPathFromStroke(stroke);
}

/**
 * 도형 SVG path 생성 — 선 / 화살표 / 사각형 / 원.
 * @param {Point} start - 시작점
 * @param {Point} end - 끝점
 * @param {ShapeType} shape - 도형 타입
 * @returns {string} SVG path d 속성
 */
export function createShapePath(start, end, shape) {
  const x1 = start.x, y1 = start.y;
  const x2 = end.x, y2 = end.y;

  switch (shape) {
    case "line":
      return `M ${x1} ${y1} L ${x2} ${y2}`;
    case "arrow": {
      const angle = Math.atan2(y2 - y1, x2 - x1);
      const headLength = 12;
      const headAngle = Math.PI / 6;
      const x3 = x2 - headLength * Math.cos(angle - headAngle);
      const y3 = y2 - headLength * Math.sin(angle - headAngle);
      const x4 = x2 - headLength * Math.cos(angle + headAngle);
      const y4 = y2 - headLength * Math.sin(angle + headAngle);
      return `M ${x1} ${y1} L ${x2} ${y2} M ${x3} ${y3} L ${x2} ${y2} L ${x4} ${y4}`;
    }
    case "rectangle": {
      const rx = Math.min(x1, x2);
      const ry = Math.min(y1, y2);
      const rw = Math.abs(x2 - x1);
      const rh = Math.abs(y2 - y1);
      return `M ${rx} ${ry} L ${rx + rw} ${ry} L ${rx + rw} ${ry + rh} L ${rx} ${ry + rh} Z`;
    }
    case "circle": {
      const cx = (x1 + x2) / 2;
      const cy = (y1 + y2) / 2;
      const radiusX = Math.abs(x2 - x1) / 2;
      const radiusY = Math.abs(y2 - y1) / 2;
      return `M ${cx - radiusX} ${cy} A ${radiusX} ${radiusY} 0 1 0 ${cx + radiusX} ${cy} A ${radiusX} ${radiusY} 0 1 0 ${cx - radiusX} ${cy}`;
    }
    default:
      return "";
  }
}

/**
 * 지우개 — 클릭/드래그 위치 근처의 경로를 거리 기반으로 삭제.
 * SVG path d 속성에서 좌표를 추출하여 임계값 내 점이 있으면 해당 경로 제거.
 * @param {DrawingPath[]} paths - 현재 경로 배열
 * @param {Point} point - 지우개 위치
 * @param {number} threshold - 삭제 임계값 (픽셀)
 * @returns {DrawingPath[]} 제거된 경로를 뺀 배열
 */
export function eraseAtPoint(paths, point, threshold = 15) {
  return paths.filter((path) => {
    const coords = path.d.match(/[\d.]+/g);
    if (!coords) return true;
    for (let i = 0; i < coords.length - 1; i += 2) {
      const px = parseFloat(coords[i]);
      const py = parseFloat(coords[i + 1]);
      const distance = Math.sqrt((px - point.x) ** 2 + (py - point.y) ** 2);
      if (distance < threshold) return false;
    }
    return true;
  });
}

/**
 * 지우개 — 텍스트 주석 위치 기반 삭제.
 * @param {TextAnnotation[]} annotations - 텍스트 주석 배열
 * @param {Point} point - 지우개 위치
 * @param {number} threshold - 삭제 임계값
 * @returns {TextAnnotation[]} 제거된 주석을 뺀 배열
 */
export function eraseTextAtPoint(annotations, point, threshold = 15) {
  return annotations.filter((a) => {
    const distance = Math.sqrt((a.x - point.x) ** 2 + (a.y - point.y) ** 2);
    return distance >= threshold;
  });
}

export { DEFAULT_FREEHAND_OPTIONS };
