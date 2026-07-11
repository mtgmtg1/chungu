// [Flow: Step 1 (도구/색상/굵기 선택) -> Step 2 (Pointer 이벤트로 드로잉) -> Step 3 (SVG path 생성) -> Step 4 (localStorage + 서버 저장)]
// React Flow 캔버스 위 드로잉 상태 관리 훅 — perfect-freehand 기반 곡선, 도형, 텍스트, 지우개.
// koda-learn의 useCardDrawing 패턴을 React Flow 좌표계에 맞게 변환.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  getFreehandPath,
  createShapePath,
  eraseAtPoint,
  eraseTextAtPoint,
} from "../utils/drawingUtils.js";
import { api } from "../api.js";

/**
 * 드로잉 상태 관리 훅 — React Flow 캔버스 위 드로잉/주석 기능.
 *
 * [Flow: Step 1 (도구 선택) -> Step 2 (Pointer down: 드로잉 시작) -> Step 3 (Pointer move: 경로 추가) -> Step 4 (Pointer up: 경로 확정 + 저장) -> Step 5 (undo/clear/erase)]
 *
 * @param {string} jobId - 작업 ID (서버 저장 키)
 * @param {Function} screenToFlowPosition - React Flow의 screenToFlowPosition (화면 좌표 → flow 좌표 변환)
 * @returns {Object} 드로잉 상태 + 액션 객체
 */
export function useFlowDrawing(jobId, screenToFlowPosition) {
  const [paths, setPaths] = useState([]);
  const [textAnnotations, setTextAnnotations] = useState([]);
  const [noteNodes, setNoteNodes] = useState([]);
  const [customEdges, setCustomEdges] = useState([]);
  const [currentPoints, setCurrentPoints] = useState([]);
  const currentPointsRef = useRef([]);
  const [isDrawing, setIsDrawing] = useState(false);
  const isDrawingRef = useRef(false);
  const [strokeColor, setStrokeColor] = useState("#6366f1");
  const [strokeWidth, setStrokeWidth] = useState(4);
  const [tool, setTool] = useState("pen");
  const [shapeType, setShapeType] = useState("line");
  const [shapeStart, setShapeStart] = useState(null);
  const [currentShapeEnd, setCurrentShapeEnd] = useState(null);

  const storageKey = jobId ? `flow-drawing-${jobId}` : null;
  const saveTimerRef = useRef(null);
  const screenToFlowRef = useRef(screenToFlowPosition);

  // screenToFlowPosition 최신값 유지
  useEffect(() => {
    screenToFlowRef.current = screenToFlowPosition;
  }, [screenToFlowPosition]);

  // Step 1: localStorage에서 복원
  useEffect(() => {
    if (!storageKey) return;
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (parsed.paths) setPaths(parsed.paths);
      if (parsed.textAnnotations) setTextAnnotations(parsed.textAnnotations);
      if (parsed.noteNodes) setNoteNodes(parsed.noteNodes);
      if (parsed.customEdges) setCustomEdges(parsed.customEdges);
    } catch { /* parse error 무시 */ }
  }, [storageKey]);

  // Step 2: 서버에서 복원
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    api.getFlowDrawings(jobId)
      .then((data) => {
        if (cancelled || !data) return;
        if (data.paths?.length) setPaths(data.paths);
        if (data.textAnnotations?.length) setTextAnnotations(data.textAnnotations);
        if (data.note_nodes?.length) setNoteNodes(data.note_nodes);
        if (data.custom_edges?.length) setCustomEdges(data.custom_edges);
      })
      .catch(() => { /* 서버 실패 시 localStorage만 사용 */ });
    return () => { cancelled = true; };
  }, [jobId]);

  // localStorage 자동 저장 (paths / textAnnotations 변경 시)
  useEffect(() => {
    if (!storageKey) return;
    try {
      localStorage.setItem(storageKey, JSON.stringify({ paths, textAnnotations, noteNodes, customEdges }));
    } catch { /* quota 초과 무시 */ }
  }, [storageKey, paths, textAnnotations]);

  // 서버 자동 저장 (2초 debounce)
  const scheduleServerSave = useCallback(() => {
    if (!jobId) return;
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      api.saveFlowDrawings(jobId, { paths, textAnnotations, note_nodes: noteNodes, custom_edges: customEdges }).catch(() => {});
    }, 2000);
  }, [jobId, paths, textAnnotations, noteNodes, customEdges]);

  useEffect(() => {
    if (paths.length > 0 || textAnnotations.length > 0 || noteNodes.length > 0 || customEdges.length > 0) {
      scheduleServerSave();
    }
  }, [paths, textAnnotations, noteNodes, customEdges, scheduleServerSave]);

  // 화면 좌표 → flow 좌표 변환
  const getFlowPoint = useCallback((e) => {
    const fn = screenToFlowRef.current;
    if (!fn) return { x: 0, y: 0 };
    return fn({ x: e.clientX, y: e.clientY });
  }, []);

  // 드로잉 시작
  const startDrawing = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    const point = getFlowPoint(e);

    // 지우개 모드
    if (tool === "eraser") {
      setPaths((prev) => eraseAtPoint(prev, point));
      setTextAnnotations((prev) => eraseTextAtPoint(prev, point));
      setIsDrawing(true);
      isDrawingRef.current = true;
      return;
    }

    // 텍스트 모드 — 클릭 위치에 텍스트 주석 추가
    if (tool === "text") {
      const text = window.prompt("텍스트를 입력하세요:");
      if (text?.trim()) {
        setTextAnnotations((prev) => [...prev, {
          id: `text-${Date.now()}`,
          x: point.x,
          y: point.y,
          text: text.trim(),
          fontSize: 14,
          color: strokeColor,
        }]);
      }
      return;
    }

    // 도형 모드 — 시작점 저장
    if (tool === "shape") {
      setShapeStart(point);
      setCurrentShapeEnd(point);
      setIsDrawing(true);
      isDrawingRef.current = true;
      return;
    }

    // 펜 / 형광펜 모드
    setIsDrawing(true);
    isDrawingRef.current = true;
    currentPointsRef.current = [point];
    setCurrentPoints([point]);
  }, [tool, getFlowPoint, strokeColor]);

  // 드로잉 중
  const continueDrawing = useCallback((e) => {
    if (!isDrawingRef.current) return;
    e.preventDefault();
    e.stopPropagation();
    const point = getFlowPoint(e);

    // 지우개 — 드래그하면서 삭제
    if (tool === "eraser") {
      setPaths((prev) => eraseAtPoint(prev, point));
      setTextAnnotations((prev) => eraseTextAtPoint(prev, point));
      return;
    }

    // 도형 — 끝점만 갱신
    if (tool === "shape") {
      setCurrentShapeEnd(point);
      return;
    }

    // 펜 / 형광펜 — 포인트 추가 (ref에도 누적, 실시간 미리보기용 state도 갱신)
    currentPointsRef.current.push(point);
    setCurrentPoints((prev) => [...prev, point]);
  }, [tool, getFlowPoint]);

  // 드로잉 종료
  const endDrawing = useCallback(() => {
    if (!isDrawingRef.current) return;

    // 도형 완성
    if (tool === "shape" && shapeStart && currentShapeEnd) {
      const d = createShapePath(shapeStart, currentShapeEnd, shapeType);
      if (d) {
        setPaths((prev) => [...prev, {
          id: `shape-${Date.now()}`,
          d,
          stroke: strokeColor,
          strokeWidth,
          type: "shape",
          shapeType,
        }]);
      }
      setShapeStart(null);
      setCurrentShapeEnd(null);
      isDrawingRef.current = false;
      setIsDrawing(false);
      return;
    }

    // 지우개 — 경로 저장 안함
    if (tool === "eraser") {
      isDrawingRef.current = false;
      setIsDrawing(false);
      return;
    }

    // 펜 / 형광펜 — SVG path 확정 (최신 좌표는 ref에서 읽음)
    if (currentPointsRef.current.length > 1) {
      const d = getFreehandPath(currentPointsRef.current, strokeWidth);
      if (d) {
        setPaths((prev) => [...prev, {
          id: `path-${Date.now()}`,
          d,
          stroke: strokeColor,
          strokeWidth: tool === "highlighter" ? strokeWidth * 3 : strokeWidth,
          type: "path",
        }]);
      }
    }

    setCurrentPoints([]);
    currentPointsRef.current = [];
    isDrawingRef.current = false;
    setIsDrawing(false);
  }, [tool, shapeStart, currentShapeEnd, shapeType, strokeColor, strokeWidth]);

  // 현재 그리는 중인 경로의 SVG path (실시간 미리보기용)
  const getCurrentPathD = useCallback(() => {
    if (tool === "shape" && shapeStart && currentShapeEnd) {
      return createShapePath(shapeStart, currentShapeEnd, shapeType);
    }
    if (currentPoints.length === 0) return "";
    return getFreehandPath(currentPoints, strokeWidth);
  }, [tool, shapeStart, currentShapeEnd, shapeType, currentPoints, strokeWidth]);

  // 실행 취소 — 마지막 경로 제거
  const undo = useCallback(() => {
    setPaths((prev) => prev.slice(0, -1));
  }, []);

  // 전체 지우기
  const clear = useCallback(() => {
    setPaths([]);
    setTextAnnotations([]);
    setNoteNodes([]);
    setCustomEdges([]);
  }, []);

  // 텍스트 주석 삭제
  const deleteTextAnnotation = useCallback((id) => {
    setTextAnnotations((prev) => prev.filter((a) => a.id !== id));
  }, []);

  // 에이전트 도구 결과로 받은 전체 상태를 로컬에 반영 — 동기화 메서드
  const updateFromAgent = useCallback((data) => {
    if (data.paths !== undefined) setPaths(data.paths);
    if (data.text_annotations !== undefined) setTextAnnotations(data.text_annotations);
    if (data.textAnnotations !== undefined) setTextAnnotations(data.textAnnotations);
    if (data.note_nodes !== undefined) setNoteNodes(data.note_nodes);
    if (data.noteNodes !== undefined) setNoteNodes(data.noteNodes);
    if (data.custom_edges !== undefined) setCustomEdges(data.custom_edges);
    if (data.customEdges !== undefined) setCustomEdges(data.customEdges);
  }, []);

  return {
    // 상태
    paths,
    textAnnotations,
    noteNodes,
    customEdges,
    isDrawing,
    strokeColor,
    strokeWidth,
    tool,
    shapeType,
    isShapeMode: tool === "shape",

    // 액션
    startDrawing,
    continueDrawing,
    endDrawing,
    getCurrentPathD,
    setStrokeColor,
    setStrokeWidth,
    setTool,
    setShapeType,
    undo,
    clear,
    deleteTextAnnotation,
    updateFromAgent,
  };
}
