// [Flow: Step 1 (선택된 sticky note 주석 + viewport 좌표 수신)
//       -> Step 2 (확장 카드 위젯을 절대 위치로 렌더링 — 코멘트 텍스트 표시)
//       -> Step 3 (닫기 버튼/외부 클릭/Escape 로 닫기 -> onClose 호출)]
// snippet PDFViewer의 기본 선택 메뉴 위에 겹쳐 보이는 확장 sticky note 위젯.
// 사용자가 "코멘트 보기" 명령을 클릭했을 때 표시되며, 주석 위치에 큰 카드로 코멘트를 바로 보여준다.
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { X, StickyNote } from "lucide-react";

/**
 * [Flow: Step 1 (annotation 객체에서 contents/color 추출) -> Step 2 (카드 렌더링)
 *       -> Step 3 (닫기 인터랙션 바인딩)]
 *
 * 확장 sticky note 위젯. 주석의 코멘트를 큰 카드 형태로 페이지 위에 직접 보여준다.
 * snippet의 기본 선택 메뉴는 이 위젯 아래에 그대로 유지된다.
 *
 * @param {object} annotation - 선택된 PdfAnnotationObject (type=1 TEXT sticky note)
 *   - annotation.contents: 코멘트 텍스트
 *   - annotation.color: 헥스 색상 문자열 (예: "#A659F2")
 *   - annotation.id: 주석 ID
 * @param {{ x: number, y: number }} position - PDFViewer 컨테이너 내 절대 좌표 (px)
 *   위젯의 좌상단이 이 좌표에 오도록 배치된다.
 * @param {Function} onClose - 위젯 닫기 요청 콜백 (닫기 버튼/외부 클릭/Escape)
 */
export default function StickyNoteOverlay({ annotation, position, onClose }) {
  const { t } = useTranslation();
  const cardRef = useRef(null);

  // [Flow: Step 1 (annotation에서 표시 데이터 추출) — 빈 코멘트/색상 fallback 포함]
  const comment = String(annotation?.contents || "").trim();
  const color = annotation?.color || annotation?.strokeColor || "#FACC15";
  const displayComment = comment || t("page:annotation.emptyComment");

  /**
   * [Flow: Step 1 (document keydown 리스너 등록) -> Step 2 (Escape 시 onClose 호출)]
   * 위젯이 열려 있는 동안 Escape 키로 닫을 수 있다.
   */
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose?.();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  /**
   * [Flow: Step 1 (document mousedown 리스너 등록) -> Step 2 (클릭 대상이 카드 외부면 onClose 호출)]
   * 위젯 바깥 영역 클릭 시 닫기. 단, snippet의 주석 조작(드래그/선택 메뉴 클릭)은 그대로 작동해야 하므로
   * 카드 자체를 클릭한 경우에는 닫지 않는다.
   */
  useEffect(() => {
    const handlePointerDown = (e) => {
      if (cardRef.current && !cardRef.current.contains(e.target)) {
        onClose?.();
      }
    };
    // mousedown 대신 pointerdown 사용 — 터치/마우스 모두 감지
    document.addEventListener("pointerdown", handlePointerDown, true);
    return () => document.removeEventListener("pointerdown", handlePointerDown, true);
  }, [onClose]);

  // [Flow: Step 1 (위젯 위치 계산) — 컨테이너 좌측 상단 기준 절대 좌표]
  // position이 null/undefined이면 렌더링하지 않는다.
  if (!position || typeof position.x !== "number" || typeof position.y !== "number") {
    return null;
  }

  return (
    <div
      ref={cardRef}
      role="dialog"
      aria-label={t("page:annotation.comment")}
      className="sticky-note-overlay"
      style={{
        position: "absolute",
        left: `${position.x}px`,
        top: `${position.y}px`,
        zIndex: 50,
        pointerEvents: "auto",
      }}
      data-oid="sticky-note-overlay"
    >
      <div
        className="flex flex-col rounded-lg shadow-xl border border-outline-variant bg-surface-container-lowest overflow-hidden"
        style={{ width: 280, maxHeight: 320 }}
      >
        {/* [Flow: 상단 헤더 — sticky note 아이콘 + 색상 띠 + 닫기 버튼] */}
        <div
          className="flex items-center gap-2 px-3 py-2 border-b border-outline-variant"
          style={{ backgroundColor: color }}
        >
          <StickyNote size={16} className="text-white flex-shrink-0" />
          <span className="text-xs font-medium text-white flex-1 truncate">
            {t("page:annotation.comment")}
          </span>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onClose?.();
            }}
            className="flex items-center justify-center rounded p-1 text-white/90 hover:bg-white/20 transition-colors flex-shrink-0"
            aria-label={t("page:annotation.close")}
            data-oid="sticky-note-overlay-close"
          >
            <X size={14} />
          </button>
        </div>

        {/* [Flow: 본문 — 코멘트 텍스트, 여러 줄 스크롤] */}
        <div className="px-3 py-2 overflow-y-auto text-sm text-on-surface whitespace-pre-wrap break-words">
          {displayComment}
        </div>
      </div>
    </div>
  );
}
