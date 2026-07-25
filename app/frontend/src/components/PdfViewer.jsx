// [Flow: Step 1 (URL, page, annotationsJson 수신) -> Step 2 (데이터 유효성 검증)
//       -> Step 3 (IntersectionObserver로 패널 가시성 감지) -> Step 4 (보이면 EmbedPDF PDFViewer를 dynamic import로 로드)
//       -> Step 5 (ErrorBoundary로 snippet preact crash 전파 차단) -> Step 6 (onReady에서 registry 획득)
//       -> Step 7 (annotation plugin으로 초기 주석 import) -> Step 8 (scroll plugin으로 page prop 위치로 이동)
//       -> Step 9 (page prop/annotationsJson 변경 시 동기화) -> Step 10 (상위 ref로 exportAnnotations 노출)]
import { Component, forwardRef, lazy, Suspense, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertCircle, RotateCw, FileText, MessageSquare } from "lucide-react";
import StickyNoteOverlay from "./StickyNoteOverlay.jsx";

/**
 * [Flow: Step 1 (@embedpdf/react-pdf-viewer의 PDFViewer를 동적 import)
 *       -> Step 2 (Suspense로 지연 로딩)]
 * 초기 번들 크기를 줄이기 위해 PDF 뷰어는 실제로 보여질 때만 로드한다.
 */
const PDFViewer = lazy(() =>
  import("@embedpdf/react-pdf-viewer").then((mod) => ({ default: mod.PDFViewer }))
);

/**
 * [Flow: Step 1 (annotationsJson 항목 순회) -> Step 2 (rect/origin/size 등 필수 좌표 필드 존재 검사)
 *       -> Step 3 (잘못된 항목은 제거하고 유효한 항목만 반환)]
 * snippet 내부 preact 컴포넌트가 rect.origin.x 등에 접근할 때 undefined 로 crash 하는 것을 방지한다.
 * EmbedPDF AnnotationTransferItem 형식이 아닌 데이터를 사전에 필터링한다.
 *
 * @param {Array} items - annotationsJson 배열
 * @returns {Array} 유효한 항목만 포함된 배열
 */
function sanitizeAnnotationsJson(items) {
  if (!Array.isArray(items)) return [];
  return items.filter((item) => {
    if (!item || typeof item !== "object") return false;
    // annotation 객체에 rect 가 있으면 origin/size 검증
    const rect = item.rect ?? item.annotation?.rect;
    if (rect) {
      if (rect.origin && typeof rect.origin.x === "number" && rect.size) {
        // 정상 포맷: {origin: {x, y}, size: {width, height}}
      } else if (typeof rect.x === "number" && typeof rect.y === "number" && typeof rect.width === "number") {
        // 하위 호환: {x, y, width, height} 포맷를 {origin, size}로 정규화
        rect.origin = { x: rect.x, y: rect.y };
        rect.size = { width: rect.width, height: rect.height || 0 };
      } else {
        return false;
      }

      // [Flow: 좌표계 혼동 가능성 경고 — origin.y가 일반적인 device-space 범위를 벗어나면 로깅]
      // PDF 뷰어는 rect.origin.y를 페이지 상단에서 아래로 떨어진 device-space 픽셀로 해석한다.
      // AI가 PDF user-space 좌표를 그대로 넘기면 origin.y가 페이지 높이에 가까워 하단에 렌더링된다.
      if (typeof rect.origin.y === "number" && rect.origin.y > 2000) {
        console.warn(
          "[PdfViewer] 의심스러운 annotation rect.origin.y 감지:",
          rect,
          "pageIndex:",
          item.pageIndex ?? item.annotation?.pageIndex,
          "PDF user-space 좌표가 device-space로 잘못 전달되었을 가능성이 있습니다."
        );
      }
    }
    // page 인덱스가 음수면 제거
    if (typeof item.pageIndex === "number" && item.pageIndex < 0) return false;
    return true;
  });
}

/**
 * [Flow: Step 1 (snippet preact 렌더링 crash 감지) -> Step 2 (에러 상태 저장)
 *       -> Step 3 (fallback UI: 에러 메시지 + 재시도 버튼 + iframe PDF 폴백)]
 * @embedpdf/snippet 내부 preact 컴포넌트가 특정 데이터에서 crash 할 때
 * 에러가 React 트리로 전파되어 결과 페이지 전체가 망가지는 것을 차단한다.
 * crash 시 iframe 으로 최소한의 PDF 보기 기능을 제공한다.
 */
class PdfViewerErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("[PdfViewer] snippet crash (ErrorBoundary):", error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      const { url, t } = this.props;
      return (
        <div className="flex flex-col h-full w-full min-h-0 items-center justify-center gap-3 p-4 bg-surface-container-low" data-oid="pdf-viewer-error">
          <AlertCircle size={32} className="text-error flex-shrink-0" />
          <div className="text-center text-sm text-on-surface-variant max-w-xs">
            {t("page:errors.loadFailed")}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={this.handleRetry}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary text-white text-sm hover:opacity-90 transition-opacity"
              data-oid="pdf-viewer-retry">
              <RotateCw size={14} />
              {t("page:retry")}
            </button>
            {url && (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-outline-variant text-on-surface text-sm hover:bg-surface-container-high transition-colors"
                data-oid="pdf-viewer-open-external">
                <FileText size={14} />
                {t("page:result.openInNewTab")}
              </a>
            )}
          </div>
          {/* iframe 폴백: 주석 편집은 불가하지만 최소한 PDF 내용 확인 가능 */}
          {url && (
            <iframe
              src={url}
              title="PDF fallback"
              className="flex-1 w-full min-h-0 mt-2 rounded border border-outline-variant bg-white"
              data-oid="pdf-viewer-fallback-iframe"
            />
          )}
        </div>
      );
    }
    return this.props.children;
  }
}

/**
 * [Flow: Step 1 (url, page, annotationsJson, onAnnotationChanged 수신)
 *       -> Step 2 (컨테이너 가시성 감시) -> Step 3 (EmbedPDF 뷰어 렌더링)
 *       -> Step 4 (registry에서 annotation/scroll plugin 획득)
 *       -> Step 5 (초기 주석 import 및 페이지 이동) -> Step 6 (상위 ref로 exportAnnotations 제공)]
 *
 * @param {string} url - PDF 서명 URL
 * @param {number} page - 초기 페이지 번호 (1-based)
 * @param {Array<object>} annotationsJson - EmbedPDF AnnotationTransferItem[] 형식의 초기 주석 목록
 * @param {Function} onAnnotationChanged - 주석 변경 이벤트 콜백
 */
const PdfViewer = forwardRef(function PdfViewer({ url, page = 1, annotationsJson, onAnnotationChanged }, ref) {
  const { t, i18n } = useTranslation();
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const annotationApiRef = useRef(null);
  const scrollApiRef = useRef(null);
  const viewportApiRef = useRef(null);
  const unsubscribeEventRef = useRef(null);
  const unsubscribeScrollRef = useRef(null);
  const unsubscribeViewportRef = useRef(null);
  const unsubscribeStateChangeRef = useRef(null);
  const overlayCloseTimerRef = useRef(null);
  const [hasBeenVisible, setHasBeenVisible] = useState(false);
  const [isReady, setIsReady] = useState(false);
  const importedAnnotationsJsonRef = useRef(null);
  // [Flow: sticky note 확장 위젯 상태 — 선택된 주석 + viewport 내 좌표]
  // expandedAnnotation이 null이 아닐 때 StickyNoteOverlay가 렌더링된다.
  const [expandedAnnotation, setExpandedAnnotation] = useState(null);
  const [overlayPosition, setOverlayPosition] = useState(null);
  // [Flow: expandedAnnotation을 ref에 미러링 — 이벤트 핸들러 클로저에서 최신 값 참조]
  // React state는 이벤트 구독 시점의 클로저에 갇히므로 ref로 최신 값을 추적한다.
  const expandedAnnotationRef = useRef(null);

  // [Flow: Step 1 (데이터 유효성 정규화) — url 빈 문자열/undefined 처리, page 1 이상 보장, annotationsJson 형식 검증]
  const validUrl = url && typeof url === "string" && url.trim() ? url : null;
  const normalizedPage = Math.max(1, Number(page) || 1);
  const safeAnnotationsJson = sanitizeAnnotationsJson(annotationsJson);

  /**
   * [Flow: Step 1 (상위 ref로 노출할 API 정의) -> Step 2 (annotation plugin 메서드 래핑)]
   * exportAnnotations: 모든 주석을 JSON 문자열로 반환
   * getAnnotations: 모든 주석을 배열로 반환 (TrackedAnnotation[])
   * selectAnnotation: 특정 페이지의 주석을 선택 (해당 페이지로 스크롤 + 하이라이트)
   * updateAnnotation: 기존 주석의 속성을 부분 업데이트 (색상/코멘트/투명도 등)
   * deleteAnnotation: 특정 페이지의 주석을 삭제
   * scrollToPage: 지정 페이지로 스크롤
   */
  useImperativeHandle(ref, () => ({
    exportAnnotations: async () => {
      const api = annotationApiRef.current;
      if (!api) return null;
      try {
        const task = api.exportAnnotations();
        if (!task) return null;
        if (typeof task.toPromise === "function") {
          const items = await task.toPromise();
          return JSON.stringify(items ?? []);
        }
        if (typeof task.wait === "function") {
          const items = await new Promise((resolve, reject) => {
            task.wait((result) => resolve(result ?? []), (error) => reject(error));
          });
          return JSON.stringify(items);
        }
        // 이미 Promise-like이거나 배열인 경우
        const items = await task;
        return JSON.stringify(items ?? []);
      } catch (e) {
        console.error("[PdfViewer] exportAnnotations failed:", e);
        return null;
      }
    },
    getAnnotations: () => {
      const api = annotationApiRef.current;
      if (!api || typeof api.getAnnotations !== "function") return [];
      try {
        return api.getAnnotations() ?? [];
      } catch (e) {
        console.error("[PdfViewer] getAnnotations failed:", e);
        return [];
      }
    },
    selectAnnotation: (pageIndex, annotationId) => {
      const api = annotationApiRef.current;
      const scrollApi = scrollApiRef.current;
      if (!api) return;
      try {
        // 해당 페이지로 스크롤한 뒤 주석 선택
        if (scrollApi && typeof scrollApi.scrollToPage === "function") {
          scrollApi.scrollToPage({ pageNumber: pageIndex + 1 });
        }
        if (typeof api.selectAnnotation === "function") {
          api.selectAnnotation(pageIndex, annotationId);
        }
      } catch (e) {
        console.error("[PdfViewer] selectAnnotation failed:", e);
      }
    },
    updateAnnotation: (pageIndex, annotationId, patch) => {
      const api = annotationApiRef.current;
      if (!api || typeof api.updateAnnotation !== "function") return;
      try {
        api.updateAnnotation(pageIndex, annotationId, patch);
      } catch (e) {
        console.error("[PdfViewer] updateAnnotation failed:", e);
      }
    },
    deleteAnnotation: (pageIndex, annotationId) => {
      const api = annotationApiRef.current;
      if (!api || typeof api.deleteAnnotation !== "function") return;
      try {
        api.deleteAnnotation(pageIndex, annotationId);
      } catch (e) {
        console.error("[PdfViewer] deleteAnnotation failed:", e);
      }
    },
    scrollToPage: (pageNumber) => {
      const scrollApi = scrollApiRef.current;
      if (!scrollApi || typeof scrollApi.scrollToPage !== "function") return;
      try {
        scrollApi.scrollToPage({ pageNumber });
      } catch (e) {
        console.error("[PdfViewer] scrollToPage failed:", e);
      }
    },
  }));

  /**
   * [Flow: Step 1 (page prop 변경 감지) -> Step 2 (scroll plugin이 준비되면 scrollToPage 호출)]
   */
  useEffect(() => {
    if (!isReady || !scrollApiRef.current) return;
    scrollApiRef.current.scrollToPage({ pageNumber: normalizedPage });
  }, [normalizedPage, isReady]);

  /**
   * [Flow: Step 1 (컴포넌트 언마운트 시) -> Step 2 (scroll/viewport/annotation 이벤트 구독 해제)
   *       -> Step 3 (throttle 타이머 정리)]
   * 메모리 누수 방지 — snippet registry 이벤트 구독을 모두 해제한다.
   */
  useEffect(() => {
    return () => {
      if (typeof unsubscribeScrollRef.current === "function") {
        unsubscribeScrollRef.current();
        unsubscribeScrollRef.current = null;
      }
      if (typeof unsubscribeViewportRef.current === "function") {
        unsubscribeViewportRef.current();
        unsubscribeViewportRef.current = null;
      }
      if (typeof unsubscribeStateChangeRef.current === "function") {
        unsubscribeStateChangeRef.current();
        unsubscribeStateChangeRef.current = null;
      }
      if (overlayCloseTimerRef.current) {
        clearTimeout(overlayCloseTimerRef.current);
        overlayCloseTimerRef.current = null;
      }
    };
  }, []);

  /**
   * [Flow: Step 1 (api.importAnnotations(items) 호출) -> Step 2 (반환값 종류 판별)
   *       -> Step 3 (Task/Promise면 await, void면 즉시 완료)]
   */
  const importAnnotationsAsPromise = async (api, items) => {
    const task = api.importAnnotations(items);
    console.log("[PdfViewer] importAnnotations returned:", typeof task, task ? Object.keys(task) : null);
    if (!task) return;
    if (typeof task.toPromise === "function") {
      await task.toPromise();
    } else if (typeof task.wait === "function") {
      await new Promise((resolve, reject) => {
        task.wait(resolve, reject);
      });
    } else if (typeof task.then === "function") {
      await task;
    }
  };

  /**
   * [Flow: Step 1 (annotationsJson 변경 감지) -> Step 2 (annotation plugin이 준비되면 importAnnotations 호출)
   *       -> Step 3 (중복 import 방지를 위해 마지막 import 문자열 기록)]
   */
  useEffect(() => {
    const api = annotationApiRef.current;
    console.log("[PdfViewer] annotation import effect:", JSON.stringify({ isReady, hasApi: !!api, count: safeAnnotationsJson?.length || 0 }));
    if (!isReady || !api) {
      console.warn("[PdfViewer] not ready to import annotations:", { isReady, hasApi: !!api });
      return;
    }
    if (!safeAnnotationsJson || safeAnnotationsJson.length === 0) {
      console.warn("[PdfViewer] safeAnnotationsJson is empty");
      return;
    }
    const currentJson = JSON.stringify(safeAnnotationsJson);
    if (currentJson === importedAnnotationsJsonRef.current) {
      console.log("[PdfViewer] annotations already imported, skipping");
      return;
    }
    const runImport = async () => {
      try {
        console.log("[PdfViewer] importing annotations (effect):", safeAnnotationsJson.length);
        await importAnnotationsAsPromise(api, safeAnnotationsJson);
        importedAnnotationsJsonRef.current = currentJson;
        console.log("[PdfViewer] annotations imported (effect)");
      } catch (e) {
        console.error("[PdfViewer] importAnnotations failed (effect):", e);
      }
    };
    runImport();
  }, [safeAnnotationsJson, isReady]);

  /**
   * [Flow: Step 1 (컨테이너 ref가 있으면 Observer 생성) -> Step 2 (교차 상태 변경 시 가시성 플래그 갱신)
   *       -> Step 3 (한 번이라도 보이면 hasBeenVisible 유지)]
   */
  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setHasBeenVisible(true);
        }
      },
      { threshold: 0.1, rootMargin: "100px" }
    );
    observer.observe(element);

    return () => {
      observer.disconnect();
    };
  }, []);

  if (!validUrl) {
    return (
      <div className="flex-1 flex items-center justify-center h-full w-full min-h-0 text-on-surface-variant text-sm" data-oid="pdf-empty">
        {t("page:errors.loadFailed")}
      </div>
    );
  }

  /**
   * [Flow: Step 1 (EmbedPDF 뷰어 준비 완료) -> Step 2 (registry에서 annotation/scroll plugin 획득)
   *       -> Step 3 (isReady true 설정) -> Step 4 (page 위치로 이동) -> Step 5 (주석 import)
   *       -> Step 6 (주석 변경 이벤트 구독)]
   */
  const handleReady = (registry) => {
    annotationApiRef.current = registry?.getPlugin("annotation")?.provides() ?? null;
    scrollApiRef.current = registry?.getPlugin("scroll")?.provides() ?? null;
    viewportApiRef.current = registry?.getPlugin("viewport")?.provides() ?? null;
    console.log("[PdfViewer] onReady:", {
      hasAnnotationApi: !!annotationApiRef.current,
      hasScrollApi: !!scrollApiRef.current,
      hasViewportApi: !!viewportApiRef.current,
      annotationCount: safeAnnotationsJson?.length,
    });
    setIsReady(true);

    if (scrollApiRef.current && normalizedPage > 1) {
      scrollApiRef.current.scrollToPage({ pageNumber: normalizedPage });
    }

    // [Flow: sticky note 확장 위젯 — onStateChange 구독으로 주석 선택 자동 감지]
    // selectionMenu 명령 방식(버튼 클릭 필요) 대신, 주석 선택 자체를 감지해 바로 확장 위젯 표시.
    // 사용자가 sticky note 클릭 -> onStateChange 발생 -> selectedUids에서 sticky note 찾기 -> 확장 위젯 표시.
    // 기존 snippet 선택 메뉴는 그 아래에 그대로 유지된다 — "그 아래에는 기존의 선택메뉴도 떠야한다" 요구사항.
    subscribeAnnotationSelectionChanges();

    // [Flow: 스크롤/뷰포트 변경 시 오버레이 위치 재계산 구독]
    // 확장 위젯이 열려 있을 때만 위치를 업데이트한다.
    subscribeOverlayPositionSync();

    const api = annotationApiRef.current;
    if (api) {
      if (safeAnnotationsJson && safeAnnotationsJson.length > 0) {
        const currentJson = JSON.stringify(safeAnnotationsJson);
        if (currentJson !== importedAnnotationsJsonRef.current) {
          console.log("[PdfViewer] importing annotations (onReady):", safeAnnotationsJson.length);
          importAnnotationsAsPromise(api, safeAnnotationsJson)
            .then(() => {
              importedAnnotationsJsonRef.current = currentJson;
              console.log("[PdfViewer] annotations imported (onReady)");
            })
            .catch((e) => {
              console.error("[PdfViewer] initial importAnnotations failed:", e);
            });
        }
      }
      if (api.onAnnotationEvent) {
        unsubscribeEventRef.current = api.onAnnotationEvent((event) => {
          if (onAnnotationChanged) {
            onAnnotationChanged(event);
          }
          // [Flow: 주석 삭제/업데이트 시 열려 있는 오버레이가 해당 주석이면 닫기]
          if (event.type === "delete" && expandedAnnotationRef.current) {
            const deletedId = event.annotation?.id;
            if (deletedId != null && String(deletedId) === String(expandedAnnotationRef.current?.id)) {
              setExpandedAnnotation(null);
              setOverlayPosition(null);
            }
          }
        });
      }
    } else {
      console.warn("[PdfViewer] annotation plugin API not available in registry");
    }
  };

  /**
   * [Flow: Step 1 (annotation plugin의 onStateChange 구독) -> Step 2 (selectedUids 변경 감지)
   *       -> Step 3 (선택된 주석이 sticky note이면 확장 위젯 표시, 아니면 닫기)]
   * selectionMenu 명령 방식(버튼 클릭 필요) 대신 주석 선택 자체를 감지.
   * 사용자가 sticky note 클릭 -> onStateChange 발생 -> selectedUids에서 sticky note 찾기 -> 확장 위젯 자동 표시.
   * 기존 snippet 선택 메뉴는 그 아래에 그대로 유지된다.
   */
  const subscribeAnnotationSelectionChanges = () => {
    const annotationApi = annotationApiRef.current;
    if (!annotationApi) {
      console.warn("[PdfViewer] annotation API not available, skipping selection subscription");
      return;
    }
    // [Flow: onStateChange는 capability와 scope 양쪽에 존재 — 페이로드가 다름]
    // - capability.onStateChange: (event: { documentId, state: AnnotationDocumentState }) => void
    // - scope.onStateChange: (state: AnnotationDocumentState) => void
    // capability 레벨로 구독하면 {documentId, state} 형태, scope 레벨이면 state만.
    // 어느 쪽이든 동작하도록 정규화한다.
    const handler = (payload) => {
      // [Flow: 페이로드 정규화 — {documentId, state} 형태이면 state를 추출, 아니면 payload 자체가 state]
      const state = payload?.state ?? payload;
      const selectedUids = state?.selectedUids ?? [];
      console.log("[PdfViewer] onStateChange fired, selectedUids:", selectedUids);
      // [Flow: 선택이 없으면 열려 있는 오버레이 닫기]
      if (selectedUids.length === 0) {
        if (expandedAnnotationRef.current) {
          setExpandedAnnotation(null);
          setOverlayPosition(null);
        }
        return;
      }
      // [Flow: 선택된 주석 중 첫 sticky note 찾기]
      const byUid = state?.byUid ?? {};
      let stickyNote = null;
      for (const uid of selectedUids) {
        const ta = byUid[uid];
        if (ta && isStickyNoteAnnotation(ta.object)) {
          stickyNote = ta.object;
          break;
        }
      }
      if (!stickyNote) {
        // [Flow: sticky note가 아닌 주석 선택 시 오버레이 닫기]
        if (expandedAnnotationRef.current) {
          setExpandedAnnotation(null);
          setOverlayPosition(null);
        }
        return;
      }
      console.log("[PdfViewer] sticky note selected:", { id: stickyNote.id, type: stickyNote.type, contents: stickyNote.contents });
      // [Flow: 같은 주석이 이미 열려 있으면 위치만 재계산, 아니면 새로 표시]
      const currentId = expandedAnnotationRef.current?.id;
      const isSameAnnotation = currentId != null && String(currentId) === String(stickyNote.id);
      // [Flow: 주석 rect 기반 위치 계산 — 메뉴 높이만큼 여유를 둬 메뉴를 가리지 않음]
      const fallbackPosition = computeOverlayPositionForAnnotation(stickyNote) ?? { x: 100, y: 100 };
      setExpandedAnnotation(stickyNote);
      setOverlayPosition(fallbackPosition);
      // [Flow: 선택 메뉴 DOM이 렌더링되면 메뉴 바로 "아래" 위치로 보정 (최대 1초 폴링)]
      if (!isSameAnnotation) {
        let attempts = 0;
        const maxAttempts = 20;
        const pollSelectionMenu = () => {
          attempts++;
          const precise = computeOverlayPositionFromSelectionMenu(stickyNote);
          if (precise) {
            setOverlayPosition(precise);
            return;
          }
          if (attempts < maxAttempts) setTimeout(pollSelectionMenu, 50);
        };
        requestAnimationFrame(pollSelectionMenu);
      }
    };
    try {
      if (typeof annotationApi.onStateChange === "function") {
        unsubscribeStateChangeRef.current = annotationApi.onStateChange(handler);
        console.log("[PdfViewer] subscribed to annotation capability onStateChange");
      } else {
        console.warn("[PdfViewer] annotation API has no onStateChange, selection detection disabled");
      }
    } catch (e) {
      console.error("[PdfViewer] failed to subscribe onStateChange:", e);
    }
  };

  /**
   * [Flow: Step 1 (주석 객체의 type 확인) -> Step 2 (type=1 TEXT sticky note이면 true)]
   * embedpdf PdfAnnotationSubtype.TEXT = 1 (sticky note).
   * @param {object} annotationObject - PdfAnnotationObject
   * @returns {boolean}
   */
  const isStickyNoteAnnotation = (annotationObject) => {
    if (!annotationObject) return false;
    const type = annotationObject.type;
    // type은 숫자(1) 또는 문자열("text"/"TEXT")일 수 있음 — 모두 처리
    return type === 1 || type === "text" || type === "TEXT" || type === "sticky";
  };

  /**
   * [Flow: Step 1 (PDF 뷰어 영역의 모든 button 요소 수집) -> Step 2 (주석 근처(아래쪽)에 있는 버튼만 필터)
   *       -> Step 3 (필터된 버튼들의 union rect = 선택 메뉴 박스) -> Step 4 (메뉴 bottom 반환)]
   * snippet 선택 메뉴는 아이콘 button들의 가로 묶음으로 렌더링된다. 속성 이름(role/data-*)은 버전마다
   * 달라질 수 있어 신뢰하기 어려우므로, "주석 주변에 떠 있는 버튼 묶음"이라는 구조적 특징으로 찾는다.
   * @param {{ x: number, y: number, width: number, height: number }} annoRect - wrap 기준 주석 박스
   * @param {HTMLElement} wrapEl - pdf-viewer-wrap 요소
   * @param {DOMRect} wrapRect - wrapEl의 client rect
   * @returns {{ left: number, bottom: number } | null} wrap 기준 메뉴 좌측/하단
   */
  const findSelectionMenuBox = (annoRect, wrapEl, wrapRect) => {
    // [Flow: 선택 메뉴는 portal로 wrap 밖에 렌더링될 수 있으므로 document 전체에서 버튼을 모은다]
    // 위젯 자신의 닫기 버튼은 제외한다.
    const buttons = Array.from(document.querySelectorAll("button")).filter(
      (b) => !b.closest('[data-oid="sticky-note-overlay"]'),
    );
    // [Flow: snippet 선택 메뉴의 Comment 버튼을 tooltip 요소로 찾는다]
    // snippet은 각 메뉴 버튼 아래에 role="tooltip" 요소를 렌더링하며, 텍스트로 "Comment"를 가진다.
    // tooltip은 visibility:hidden이더라도 DOM에 존재하므로 안정적으로 찾을 수 있다.
    // tooltip의 부모가 메뉴 버튼이며, 메뉴 컨테이너는 그 버튼의 positioned 부모다.
    const commentTooltip = Array.from(document.querySelectorAll('[role="tooltip"]'))
      .find((el) => el.textContent?.trim() === "Comment");
    const commentBtn = commentTooltip?.parentElement ?? buttons.find((b) => b.getAttribute("aria-label") === "Comment");
    if (commentBtn) {
      // [Flow: Comment 버튼에서 positioned 부모(메뉴 컨테이너)를 찾아 올라간다]
      let menuContainer = commentBtn.parentElement;
      while (menuContainer && menuContainer !== document.body) {
        const pos = getComputedStyle(menuContainer).position;
        if (pos === "absolute" || pos === "fixed") break;
        menuContainer = menuContainer.parentElement;
      }
      const containerEl = menuContainer && menuContainer !== document.body ? menuContainer : commentBtn;
      const r = containerEl.getBoundingClientRect();
      const left = r.left - wrapRect.left;
      const bottom = r.bottom - wrapRect.top;
      return { left, bottom };
    }
    // [Flow: Comment 버튼을 못 찾으면 기존 휴리스틱(주석 주변 버튼 묶음)으로 fallback]
    // 주석 박스 기준 탐색 창 — 주석 위/아래 140px, 좌우 260px 이내의 버튼을 메뉴 후보로 본다
    const annoCenterX = annoRect.x + annoRect.width / 2;
    const annoTop = annoRect.y;
    const annoBottom = annoRect.y + annoRect.height;
    const SEARCH_V = 140;
    const SEARCH_H = 260;
    const nearby = buttons
      .map((b) => {
        const r = b.getBoundingClientRect();
        return { left: r.left - wrapRect.left, top: r.top - wrapRect.top, bottom: r.bottom - wrapRect.top, right: r.right - wrapRect.left, width: r.width, height: r.height };
      })
      .filter((r) => r.width > 0 && r.height > 0)
      // 아이콘 버튼 크기대(대략 20~64px) — 툴바의 큰 버튼/전혀 다른 UI 제외
      .filter((r) => r.height <= 64)
      // [Flow: wrap 영역(PDF 뷰어) 안에 있는 버튼만 — 앱 헤더/좌측 패널 버튼 배제]
      .filter((r) => r.top >= -8 && r.bottom <= wrapRect.height + 8 && r.left >= -8 && r.right <= wrapRect.width + 8)
      .filter((r) => r.bottom > annoTop - SEARCH_V && r.top < annoBottom + SEARCH_V)
      .filter((r) => Math.abs((r.left + r.right) / 2 - annoCenterX) < SEARCH_H);
    if (nearby.length < 2) return null;
    const left = Math.min(...nearby.map((r) => r.left));
    const bottom = Math.max(...nearby.map((r) => r.bottom));
    return { left, bottom };
  };

  /**
   * [Flow: Step 1 (주석 wrap 좌표 계산) -> Step 2 (주석 주변 선택 메뉴 박스 탐색)
   *       -> Step 3 (메뉴를 찾으면 메뉴 bottom 아래에 배치) -> Step 4 (못 찾으면 null)]
   * 선택 메뉴 바로 "아래"에 위젯을 배치해 메뉴를 가리지 않게 한다.
   * @param {object} annotationObject - PdfAnnotationObject
   * @returns {{ x: number, y: number } | null}
   */
  const computeOverlayPositionFromSelectionMenu = (annotationObject) => {
    const wrapEl = containerRef.current?.querySelector?.('[data-oid="pdf-viewer-wrap"]');
    const anno = annotationObject ?? expandedAnnotationRef.current;
    if (!wrapEl || !anno) return null;
    const annoRect = computeAnnotationWrapRect(anno);
    if (!annoRect) return null;
    const wrapRect = wrapEl.getBoundingClientRect();
    const menuBox = findSelectionMenuBox(annoRect, wrapEl, wrapRect);
    if (!menuBox) return null;
    // [Flow: 메뉴 bottom + 8px — 메뉴를 완전히 비켜 아래에 배치]
    const y = menuBox.bottom + 8;
    // [Flow: x는 스티키 노트 아이콘 중앙 기준 — 위젯 가로 중앙이 아이콘 중앙에 오도록]
    const x = centerWidgetXOnAnnotation(annoRect, wrapEl);
    return { x, y };
  };

  /**
   * [Flow: Step 1 (주석 중앙 x 계산) -> Step 2 (위젯 폭 절반을 빼서 가로 중앙 정렬)
   *       -> Step 3 (컨테이너 좌/우 경계 안으로 clamp)]
   * 확장 위젯이 작은 sticky note 아이콘을 가로 중앙에 두도록 x 좌표를 계산한다.
   * @param {{ x: number, width: number }} annoRect - wrap 기준 주석 박스
   * @param {HTMLElement} wrapEl - pdf-viewer-wrap 요소
   * @returns {number} wrap 기준 위젯 left 좌표
   */
  const centerWidgetXOnAnnotation = (annoRect, wrapEl) => {
    const WIDGET_WIDTH = 280;
    const EDGE_GAP = 8;
    const annoCenterX = annoRect.x + annoRect.width / 2;
    let x = annoCenterX - WIDGET_WIDTH / 2;
    const wrapWidth = wrapEl?.clientWidth ?? 0;
    // [Flow: 좌우 경계를 벗어나면 컨테이너 안으로 밀어넣는다]
    if (wrapWidth > 0 && x + WIDGET_WIDTH > wrapWidth - EDGE_GAP) {
      x = wrapWidth - WIDGET_WIDTH - EDGE_GAP;
    }
    return Math.max(EDGE_GAP, x);
  };

  /**
   * [Flow: Step 1 (주석 rect/pageIndex 추출) -> Step 2 (getRectPositionForPage로 viewport 좌표 획득)
   *       -> Step 3 (스크롤 컨테이너 offset 보정) -> Step 4 (wrap 기준 박스 반환)]
   * 주석의 화면 위치(pdf-viewer-wrap 기준)를 구한다. 위젯 배치의 기준 좌표계로 사용.
   * @param {object} annotationObject - PdfAnnotationObject
   * @returns {{ x: number, y: number, width: number, height: number } | null}
   */
  const computeAnnotationWrapRect = (annotationObject) => {
    const scrollApi = scrollApiRef.current;
    if (!scrollApi || !annotationObject) return null;
    const pageIndex = annotationObject.pageIndex ?? 0;
    const rect = annotationObject.rect;
    if (!rect || !rect.origin || !rect.size) return null;
    const isUsable = (r) => r && r.origin && !Number.isNaN(r.origin.x) && !Number.isNaN(r.origin.y);
    // [Flow: page 인자가 1-based/0-based 어느 쪽인지 불분명하므로 둘 다 시도]
    let viewportRect = null;
    if (typeof scrollApi.getRectPositionForPage === "function") {
      const r1 = scrollApi.getRectPositionForPage(pageIndex + 1, rect);
      if (isUsable(r1)) viewportRect = r1;
      else {
        const r0 = scrollApi.getRectPositionForPage(pageIndex, rect);
        if (isUsable(r0)) viewportRect = r0;
      }
    }
    if (!viewportRect) return null;
    // [Flow: snippet 스크롤 컨테이너가 wrap 안에서 갖는 offset 보정]
    let offsetX = 0;
    let offsetY = 0;
    const wrapEl = containerRef.current?.querySelector('[data-oid="pdf-viewer-wrap"]');
    if (wrapEl) {
      const embedContainer = wrapEl.querySelector("embedpdf-container");
      const scrollContainer = embedContainer?.querySelector('[style*="overflow"]') ||
        embedContainer?.querySelector('[class*="overflow"]') ||
        embedContainer?.firstElementChild?.firstElementChild ||
        embedContainer?.firstElementChild;
      if (scrollContainer) {
        const wrapRect = wrapEl.getBoundingClientRect();
        const scRect = scrollContainer.getBoundingClientRect();
        offsetX = scRect.left - wrapRect.left;
        offsetY = scRect.top - wrapRect.top;
      }
    }
    return {
      x: viewportRect.origin.x + offsetX,
      y: viewportRect.origin.y + offsetY,
      width: viewportRect.size?.width ?? 18,
      height: viewportRect.size?.height ?? 18,
    };
  };

  /**
   * [Flow: Step 1 (주석의 pageIndex와 rect 추출) -> Step 2 (getRectPositionForPage 1-based 시도)
   *       -> Step 3 (null이면 0-based 시도) -> Step 4 (viewport container 기준 좌표로 변환)
   *       -> Step 5 (위젯이 주석 위쪽에 배치되도록 y 오프셋 조정, 화면 밖이면 아래로) -> Step 6 (좌표 반환 또는 null)]
   * 주석의 rect(페이지 내 device-space 좌표)를 pdf-viewer-wrap 컨테이너 내 절대 좌표로 변환.
   * getRectPositionForPage는 viewport(스크롤 컨테이너) 기준 좌표를 반환하므로,
   * viewport container의 offset을 빼서 pdf-viewer-wrap 기준으로 맞춘다.
   * 위젯 높이(약 200px)만큼 위로 오프셋해 주석 위에 배치. 화면 상단을 벗어나면 주석 아래로 배치.
   * @param {object} annotationObject - PdfAnnotationObject
   * @returns {{ x: number, y: number } | null}
   */
  const computeOverlayPositionForAnnotation = (annotationObject) => {
    try {
      const annoRect = computeAnnotationWrapRect(annotationObject);
      if (!annoRect) {
        console.warn("[PdfViewer] annotation wrap rect unavailable, cannot position overlay");
        return null;
      }
      // [Flow: 선택 메뉴가 주석 바로 아래 뜨므로, 메뉴 높이 추정치만큼 더 내려 겹침을 피한다]
      // 메뉴 DOM을 찾으면 computeOverlayPositionFromSelectionMenu가 정확한 값으로 덮어쓴다.
      const SELECTION_MENU_CLEARANCE = 112;
      const wrapEl = containerRef.current?.querySelector('[data-oid="pdf-viewer-wrap"]');
      const y = annoRect.y + annoRect.height + SELECTION_MENU_CLEARANCE;
      // [Flow: x는 스티키 노트 아이콘 중앙 기준 가로 중앙 정렬]
      const x = centerWidgetXOnAnnotation(annoRect, wrapEl);
      return { x, y };
    } catch (e) {
      console.error("[PdfViewer] computeOverlayPositionForAnnotation failed:", e);
      return null;
    }
  };

  /**
   * [Flow: Step 1 (scroll/viewport 이벤트 구독) -> Step 2 (오버레이 열려 있을 때만 위치 재계산)
   *       -> Step 3 (throttle 16ms로 성능 최적화)]
   * 스크롤/줌/리사이즈 시 확장 위젯 위치가 주석을 따라 이동하도록 동기화.
   */
  const subscribeOverlayPositionSync = () => {
    const scrollApi = scrollApiRef.current;
    const viewportApi = viewportApiRef.current;
    const throttledRecompute = () => {
      if (overlayCloseTimerRef.current) return;
      overlayCloseTimerRef.current = setTimeout(() => {
        overlayCloseTimerRef.current = null;
        const current = expandedAnnotationRef.current;
        if (!current) return;
        // [Flow: selectionMenu DOM 기반 위치를 우선 사용 — 실패 시 getRectPositionForPage fallback]
        const position = computeOverlayPositionFromSelectionMenu(current) ?? computeOverlayPositionForAnnotation(current);
        if (position) setOverlayPosition(position);
      }, 16);
    };
    if (scrollApi?.onScroll) {
      unsubscribeScrollRef.current = scrollApi.onScroll(throttledRecompute);
    }
    if (viewportApi?.onViewportChange) {
      unsubscribeViewportRef.current = viewportApi.onViewportChange(throttledRecompute);
    }
  };

  // [Flow: expandedAnnotation을 ref에 미러링 — 이벤트 핸들러 클로저에서 최신 값 참조]
  // React state는 이벤트 구독 시점의 클로저에 갇히므로 ref로 최신 값을 추적한다.
  useEffect(() => {
    expandedAnnotationRef.current = expandedAnnotation;
  }, [expandedAnnotation]);

  /**
   * [Flow: Step 1 (오버레이 닫기) -> Step 2 (상태 초기화 + 타이머 정리)]
   */
  const handleCloseOverlay = useCallback(() => {
    setExpandedAnnotation(null);
    setOverlayPosition(null);
  }, []);

  /**
   * [Flow: Step 1 (언어에 따라 EmbedPDF locale 선택) -> Step 2 (ko/ja/en 중 하나 반환)]
   */
  const locale = (() => {
    const lang = i18n.language || "en";
    if (lang.startsWith("ko")) return "ko";
    if (lang.startsWith("ja")) return "ja";
    return "en";
  })();

  return (
    <div ref={containerRef} className="flex-1 flex flex-col h-full w-full min-h-0 overflow-hidden bg-surface-container-low" data-oid="pdf-viewer">
      <div className="flex-1 overflow-hidden min-h-0 relative" data-oid="pdf-viewer-wrap">
        {hasBeenVisible ? (
          <PdfViewerErrorBoundary url={validUrl} t={t}>
            <Suspense
              fallback={(
                <div className="absolute inset-0 flex items-center justify-center text-on-surface-variant text-sm" data-oid="pdf-loading">
                  {t("page:result.preview")}
                </div>
              )}
            >
              <PDFViewer
                ref={viewerRef}
                config={{
                  src: validUrl,
                  documentId: "source-doc",
                  i18n: { locale },
                }}
                style={{ width: "100%", height: "100%" }}
                onReady={handleReady}
              />
            </Suspense>
          </PdfViewerErrorBoundary>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-on-surface-variant text-sm" data-oid="pdf-placeholder">
            {t("page:result.preview")}
          </div>
        )}
        {/* [Flow: sticky note 확장 위젯 오버레이 — 선택된 주석 위치에 절대 배치, snippet 위에 겹침] */}
        {expandedAnnotation && overlayPosition && (
          <StickyNoteOverlay
            annotation={expandedAnnotation}
            position={overlayPosition}
            onClose={handleCloseOverlay}
          />
        )}
      </div>
    </div>
  );
});

export default PdfViewer;
