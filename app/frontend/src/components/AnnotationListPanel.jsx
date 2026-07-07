// [Flow: Step 1 (annotationsJson 수신) -> Step 2 (페이지별로 그룹화) -> Step 3 (리스트 렌더링)
//       -> Step 4 (항목 클릭 시 해당 페이지로 스크롤 + 주석 선택) -> Step 5 (색상/코멘트/투명도 편집)
//       -> Step 6 (삭제 버튼) -> Step 7 (변경 시 onAnnotationChanged 콜백)]
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { X, Trash2, MessageSquare } from "lucide-react";

/**
 * [Flow: Step 1 (annotationsJson, viewerRef, onClose 수신)
 *       -> Step 2 (주석을 페이지별로 그룹화) -> Step 3 (각 주석의 속성 표시 및 편집 UI)
 *       -> Step 4 (viewerRef를 통해 PdfViewer의 selectAnnotation/updateAnnotation/deleteAnnotation 호출)]
 *
 * @param {Array<object>} annotationsJson - EmbedPDF AnnotationTransferItem[] 형식의 주석 목록
 * @param {object} viewerRef - PdfViewer의 ref (selectAnnotation/updateAnnotation/deleteAnnotation 노출)
 * @param {Function} onAnnotationChanged - 주석 변경 시 호출되는 콜백 (자동 저장 트리거)
 * @param {Function} onClose - 패널 닫기 콜백
 */
export default function AnnotationListPanel({ annotationsJson, viewerRef, onAnnotationChanged, onClose }) {
  const { t } = useTranslation();
  const [expandedId, setExpandedId] = useState(null);

  /**
   * [Flow: Step 1 (annotationsJson을 페이지별로 그룹화) -> Step 2 (페이지 번호 기준 정렬)]
   * EmbedPDF 주석은 annotation.pageIndex(0-based)를 기준으로 그룹화한다.
   */
  const groupedAnnotations = useMemo(() => {
    if (!annotationsJson || !Array.isArray(annotationsJson)) return [];
    const groups = new Map();
    for (const item of annotationsJson) {
      const ann = item.annotation || item;
      const pageIndex = ann.pageIndex ?? ann.page_index ?? 0;
      if (!groups.has(pageIndex)) groups.set(pageIndex, []);
      groups.get(pageIndex).push({ item, ann, id: ann.id || "" });
    }
    return Array.from(groups.entries()).sort((a, b) => a[0] - b[0]);
  }, [annotationsJson]);

  /**
   * [Flow: Step 1 (항목 클릭) -> Step 2 (viewerRef.selectAnnotation 호출하여 해당 페이지로 스크롤 + 선택)
   *       -> Step 3 (확장 토글)]
   */
  const handleSelect = (pageIndex, id) => {
    if (viewerRef?.current?.selectAnnotation) {
      viewerRef.current.selectAnnotation(pageIndex, id);
    }
    setExpandedId((prev) => (prev === id ? null : id));
  };

  /**
   * [Flow: Step 1 (색상 변경) -> Step 2 (viewerRef.updateAnnotation 호출) -> Step 3 (자동 저장 트리거)]
   */
  const handleColorChange = (pageIndex, id, color) => {
    if (viewerRef?.current?.updateAnnotation) {
      viewerRef.current.updateAnnotation(pageIndex, id, { color });
      if (onAnnotationChanged) onAnnotationChanged();
    }
  };

  /**
   * [Flow: Step 1 (코멘트 변경) -> Step 2 (viewerRef.updateAnnotation 호출) -> Step 3 (자동 저장 트리거)]
   */
  const handleCommentChange = (pageIndex, id, contents) => {
    if (viewerRef?.current?.updateAnnotation) {
      viewerRef.current.updateAnnotation(pageIndex, id, { contents });
      if (onAnnotationChanged) onAnnotationChanged();
    }
  };

  /**
   * [Flow: Step 1 (투명도 변경) -> Step 2 (viewerRef.updateAnnotation 호출) -> Step 3 (자동 저장 트리거)]
   */
  const handleOpacityChange = (pageIndex, id, opacity) => {
    if (viewerRef?.current?.updateAnnotation) {
      viewerRef.current.updateAnnotation(pageIndex, id, { opacity });
      if (onAnnotationChanged) onAnnotationChanged();
    }
  };

  /**
   * [Flow: Step 1 (삭제 버튼 클릭) -> Step 2 (viewerRef.deleteAnnotation 호출) -> Step 3 (자동 저장 트리거)]
   */
  const handleDelete = (pageIndex, id) => {
    if (viewerRef?.current?.deleteAnnotation) {
      viewerRef.current.deleteAnnotation(pageIndex, id);
      if (onAnnotationChanged) onAnnotationChanged();
      if (expandedId === id) setExpandedId(null);
    }
  };

  // 주석 타입에 따른 라벨 — highlight / freetext / freetextcallout
  const typeLabel = (ann) => {
    let type = "";
    const raw = ann.type;
    if (typeof raw === "string") {
      type = raw.toLowerCase();
    } else if (typeof raw === "number") {
      // EmbedPDF numeric annotation type mapping (9 = highlight, 2 = FreeText)
      if (raw === 9) type = "highlight";
      else if (raw === 2) type = "freetext";
    }
    const intent = (ann.intent || "").toLowerCase();
    if (intent === "freetextcallout") type = "freetextcallout";
    if (type === "highlight") return t("page:result.annotationTypeHighlight");
    if (type === "freetext" || type === "freetextcallout") return t("page:result.annotationTypeCallout");
    return type || "annotation";
  };

  // 미리보기 텍스트 — 코멘트가 있으면 코멘트, 없으면 하이라이트된 텍스트
  const previewText = (ann) => {
    const text = ann.contents || ann.content || "";
    if (text) return text.length > 40 ? text.slice(0, 40) + "…" : text;
    return t("page:result.annotationNoText");
  };

  const colorOptions = ["#FFD700", "#FF0000", "#00FF00", "#0000FF", "#FFA500", "#800080", "#FFC0CB", "#808080"];

  return (
    <div
      className="absolute top-0 right-0 z-20 h-full w-72 bg-white shadow-xl border-l border-outline-variant flex flex-col transition-transform duration-300"
      data-oid="annotation-list-panel">
      {/* 헤더 — 제목 + 닫기 버튼 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant">
        <h4 className="font-bold text-sm text-on-surface flex items-center gap-1.5">
          <MessageSquare size={14} className="text-primary" />
          {t("page:result.annotationListTitle")}
        </h4>
        <button
          type="button"
          onClick={onClose}
          className="text-on-surface-variant hover:text-on-surface transition-colors"
          aria-label={t("common:actions.close")}>
          <X size={16} />
        </button>
      </div>

      {/* 주석 목록 — 페이지별 그룹화 */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-2">
        {groupedAnnotations.length === 0 ? (
          <p className="text-xs text-on-surface-variant text-center py-8">
            {t("page:result.annotationListEmpty")}
          </p>
        ) : (
          groupedAnnotations.map(([pageIndex, items]) => (
            <div key={pageIndex} className="mb-3">
              {/* 페이지 헤더 */}
              <div className="text-[10px] font-bold text-on-surface-variant uppercase tracking-wide px-2 py-1">
                {t("page:result.annotationPage", { page: pageIndex + 1 })}
              </div>
              {/* 해당 페이지의 주석 목록 */}
              {items.map(({ ann, id }) => (
                <div
                  key={id}
                  className={`rounded-lg border mb-1 transition-colors cursor-pointer ${
                    expandedId === id
                      ? "border-primary bg-primary/5"
                      : "border-outline-variant hover:bg-surface-container-high"
                  }`}>
                  {/* 주석 요약 행 — 클릭 시 해당 페이지로 스크롤 + 확장 */}
                  <div
                    className="flex items-start gap-2 px-2 py-1.5"
                    onClick={() => handleSelect(pageIndex, id)}>
                    <div
                      className="flex-shrink-0 w-3 h-3 rounded-sm mt-0.5 border border-outline-variant"
                      style={{ backgroundColor: ann.color || "#FFD700" }} />
                    <div className="flex-1 min-w-0">
                      <div className="text-[10px] text-on-surface-variant">{typeLabel(ann)}</div>
                      <div className="text-xs text-on-surface truncate">{previewText(ann)}</div>
                    </div>
                  </div>

                  {/* 확장 시 편집 UI */}
                  {expandedId === id && (
                    <div className="px-2 pb-2 space-y-2 border-t border-outline-variant pt-2">
                      {/* 색상 편집 */}
                      <div>
                        <label className="block text-[10px] text-on-surface-variant mb-1">
                          {t("page:result.annotationEditColor")}
                        </label>
                        <div className="flex flex-wrap gap-1">
                          {colorOptions.map((c) => (
                            <button
                              key={c}
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleColorChange(pageIndex, id, c);
                              }}
                              className={`w-5 h-5 rounded-sm border transition-transform hover:scale-110 ${
                                (ann.color || "#FFD700").toUpperCase() === c.toUpperCase()
                                  ? "ring-2 ring-primary ring-offset-1"
                                  : "border-outline-variant"
                              }`}
                              style={{ backgroundColor: c }}
                              aria-label={c} />
                          ))}
                        </div>
                      </div>

                      {/* 코멘트 편집 */}
                      <div>
                        <label className="block text-[10px] text-on-surface-variant mb-1">
                          {t("page:result.annotationEditComment")}
                        </label>
                        <textarea
                          value={ann.contents || ann.content || ""}
                          onChange={(e) => handleCommentChange(pageIndex, id, e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          rows={2}
                          className="w-full px-2 py-1 border border-outline-variant rounded text-xs resize-none focus:outline-none focus:ring-1 focus:ring-primary/40"
                          data-oid="annotation-comment-edit" />
                      </div>

                      {/* 투명도 편집 */}
                      <div>
                        <label className="block text-[10px] text-on-surface-variant mb-1">
                          {t("page:result.annotationEditOpacity")}: {Math.round((ann.opacity ?? 1) * 100)}%
                        </label>
                        <input
                          type="range"
                          min="0"
                          max="1"
                          step="0.1"
                          value={ann.opacity ?? 1}
                          onChange={(e) => handleOpacityChange(pageIndex, id, parseFloat(e.target.value))}
                          onClick={(e) => e.stopPropagation()}
                          className="w-full"
                          data-oid="annotation-opacity-edit" />
                      </div>

                      {/* 삭제 버튼 */}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(pageIndex, id);
                        }}
                        className="flex items-center gap-1 text-xs text-error hover:text-error/80 transition-colors"
                        data-oid="annotation-delete-btn">
                        <Trash2 size={12} />
                        {t("page:result.annotationDelete")}
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
