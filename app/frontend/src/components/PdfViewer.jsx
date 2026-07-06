// [Flow: Step 1 (URL, page, annotationsJson 수신) -> Step 2 (IntersectionObserver로 패널 가시성 감지)
//       -> Step 3 (보이면 EmbedPDF PDFViewer를 dynamic import로 로드) -> Step 4 (onReady에서 registry 획득)
//       -> Step 5 (annotation plugin으로 초기 주석 import) -> Step 6 (scroll plugin으로 page prop 위치로 이동)
//       -> Step 7 (page prop/annotationsJson 변경 시 동기화) -> Step 8 (상위 ref로 exportAnnotations 노출)]
import { forwardRef, lazy, Suspense, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import * as jsonpatch from "fast-json-patch";

/**
 * [Flow: Step 1 (@embedpdf/react-pdf-viewer의 PDFViewer를 동적 import)
 *       -> Step 2 (Suspense로 지연 로딩)]
 * 초기 번들 크기를 줄이기 위해 PDF 뷰어는 실제로 보여질 때만 로드한다.
 */
const PDFViewer = lazy(() =>
  import("@embedpdf/react-pdf-viewer").then((mod) => ({ default: mod.PDFViewer }))
);

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
  const unsubscribeEventRef = useRef(null);
  const [hasBeenVisible, setHasBeenVisible] = useState(false);
  const [isReady, setIsReady] = useState(false);
  const importedAnnotationsJsonRef = useRef(null);

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
    scrollApiRef.current.scrollToPage({ pageNumber: page });
  }, [page, isReady]);

  /**
   * [Flow: Step 1 (annotation plugin이 있으면 importAnnotations Task를 Promise로 변환)
   *       -> Step 2 (toPromise/wait 중 사용 가능한 메서드로 await)]
   */
  const importAnnotationsAsPromise = async (api, items) => {
    const task = api.importAnnotations(items);
    if (!task) return;
    if (typeof task.toPromise === "function") {
      await task.toPromise();
    } else if (typeof task.wait === "function") {
      await new Promise((resolve, reject) => {
        task.wait(resolve, reject);
      });
    }
  };

  /**
   * [Flow: Step 1 (기존 주석을 모두 삭제) -> Step 2 (새 주석 JSON을 importAnnotations로 로드)]
   * exportAnnotations 실패나 diff 적용 불가 시 폴백으로 사용한다.
   */
  const replaceAnnotations = async (api, items) => {
    try {
      if (typeof api.deleteAllAnnotations === "function") {
        api.deleteAllAnnotations();
      }
    } catch (e) {
      console.warn("[PdfViewer] deleteAllAnnotations failed:", e);
    }
    await importAnnotationsAsPromise(api, items);
  };

  /**
   * [Flow: Step 1 (현재 뷰어 주석 export) -> Step 2 (ID 기준으로 old/new Map 구성)
   *       -> Step 3 (new에 없는 ID 삭제) -> Step 4 (current에 없는 ID 생성)
   *       -> Step 5 (같은 ID의 주석 중 변경된 필드만 updateAnnotation)
   *       -> Step 6 (fast-json-patch로 검증)]
   *
   * importAnnotations가 기존 주석을 업데이트하지 않고 추가만 하므로,
   * diff 기반으로 추가/삭제/갱신을 분리하여 안전하게 갱신한다.
   * 사용자가 그린 미저장 주석은 current에 있고, 서버 JSON에도 포함되면 new에 있어
   * 삭제되지 않고 유지된다. 만약 서버 JSON에 아직 없다면, export 후 재import 시
   * 복원되지 않을 수 있으므로 폴백(deleteAll+import)을 사용한다.
   */
  const applyAnnotationDiff = async (api, newItems) => {
    // [Flow: Step 1 — 현재 뷰어 주석 export]
    let currentItems = [];
    try {
      const task = api.exportAnnotations();
      if (task) {
        if (typeof task.toPromise === "function") {
          currentItems = (await task.toPromise()) ?? [];
        } else if (typeof task.wait === "function") {
          currentItems = await new Promise((resolve, reject) => {
            task.wait((result) => resolve(result ?? []), (error) => reject(error));
          });
        } else {
          currentItems = await task;
        }
      }
    } catch (e) {
      console.warn("[PdfViewer] exportAnnotations failed, falling back to deleteAll+import:", e);
      return replaceAnnotations(api, newItems);
    }

    if (!Array.isArray(currentItems)) {
      currentItems = [];
    }

    const getId = (item) => item?.annotation?.id ?? item?.id;
    const getPage = (item) => item?.annotation?.pageIndex ?? item?.pageIndex;
    const getAnnotation = (item) => item?.annotation ?? item;

    // [Flow: Step 2 — ID 기준 Map 구성]
    const currentById = new Map();
    for (const item of currentItems) {
      const id = getId(item);
      if (id) currentById.set(id, item);
    }

    const newById = new Map();
    for (const item of newItems) {
      const id = getId(item);
      if (id) newById.set(id, item);
    }

    // [Flow: Step 3 — new에 없는 ID 삭제]
    for (const [id, item] of currentById) {
      if (!newById.has(id)) {
        try {
          const pageIndex = getPage(item);
          if (typeof api.deleteAnnotation === "function" && pageIndex != null) {
            api.deleteAnnotation(pageIndex, id);
          }
        } catch (e) {
          console.warn("[PdfViewer] deleteAnnotation failed:", id, e);
        }
      }
    }

    // [Flow: Step 4 — current에 없는 ID 생성]
    for (const [id, item] of newById) {
      if (!currentById.has(id)) {
        try {
          const ann = getAnnotation(item);
          const pageIndex = getPage(item);
          if (typeof api.createAnnotation === "function" && pageIndex != null) {
            api.createAnnotation(ann, pageIndex);
          }
        } catch (e) {
          console.warn("[PdfViewer] createAnnotation failed:", id, e);
        }
      }
    }

    // [Flow: Step 5 — 같은 ID의 주석 중 변경된 필드만 updateAnnotation]
    const UPDATABLE_FIELDS = ["color", "contents", "opacity", "strokeColor", "strokeWidth", "calloutLine"];
    for (const [id, newItem] of newById) {
      const oldItem = currentById.get(id);
      if (!oldItem) continue;
      const oldAnn = getAnnotation(oldItem);
      const newAnn = getAnnotation(newItem);
      const patch = {};
      for (const field of UPDATABLE_FIELDS) {
        if (JSON.stringify(oldAnn[field]) !== JSON.stringify(newAnn[field])) {
          patch[field] = newAnn[field];
        }
      }
      if (Object.keys(patch).length > 0) {
        try {
          const pageIndex = getPage(newItem);
          if (typeof api.updateAnnotation === "function" && pageIndex != null) {
            api.updateAnnotation(pageIndex, id, patch);
          }
        } catch (e) {
          console.warn("[PdfViewer] updateAnnotation failed:", id, e);
        }
      }
    }

    // [Flow: Step 6 — fast-json-patch 검증: old에 diff를 적용하면 new가 되어야 함]
    try {
      const oldForPatch = Array.from(currentById.values()).map((item) => getAnnotation(item));
      const newForPatch = Array.from(newById.values()).map((item) => getAnnotation(item));
      const indexMap = new Map(oldForPatch.map((ann, i) => [ann.id, i]));
      const oldArray = oldForPatch;
      const newArray = newForPatch;
      const patch = jsonpatch.compare(oldArray, newArray);
      if (patch.length > 0) {
        const result = jsonpatch.applyPatch(oldArray, patch).newDocument;
        const match = JSON.stringify(result) === JSON.stringify(newArray);
        if (!match) {
          console.warn("[PdfViewer] fast-json-patch verification mismatch");
        }
      }
    } catch (e) {
      console.warn("[PdfViewer] fast-json-patch verification failed:", e);
    }
  };

  /**
   * [Flow: Step 1 (annotationsJson 변경 감지) -> Step 2 (annotation plugin이 준비되면 diff 기반 갱신)
   *       -> Step 3 (중복 import 방지를 위해 마지막 import 문자열 기록)]
   */
  useEffect(() => {
    const api = annotationApiRef.current;
    if (!isReady || !api) return;
    if (!annotationsJson || annotationsJson.length === 0) return;
    const currentJson = JSON.stringify(annotationsJson);
    if (currentJson === importedAnnotationsJsonRef.current) return;
    const runImport = async () => {
      try {
        await applyAnnotationDiff(api, annotationsJson);
        importedAnnotationsJsonRef.current = currentJson;
      } catch (e) {
        console.error("[PdfViewer] applyAnnotationDiff failed:", e);
      }
    };
    runImport();
  }, [annotationsJson, isReady]);

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

  if (!url) {
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
    setIsReady(true);

    if (scrollApiRef.current && page > 1) {
      scrollApiRef.current.scrollToPage({ pageNumber: page });
    }

    const api = annotationApiRef.current;
    if (api) {
      if (annotationsJson && annotationsJson.length > 0) {
        const currentJson = JSON.stringify(annotationsJson);
        if (currentJson !== importedAnnotationsJsonRef.current) {
          importAnnotationsAsPromise(api, annotationsJson)
            .then(() => {
              importedAnnotationsJsonRef.current = currentJson;
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
        });
      }
    }
  };

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
                src: url,
                documentId: "source-doc",
                i18n: { locale },
              }}
              style={{ width: "100%", height: "100%" }}
              onReady={handleReady}
            />
          </Suspense>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-on-surface-variant text-sm" data-oid="pdf-placeholder">
            {t("page:result.preview")}
          </div>
        )}
      </div>
    </div>
  );
});

export default PdfViewer;
