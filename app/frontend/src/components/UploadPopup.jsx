// [Flow: Step 1 (열림/닫힘 상태 수신) -> Step 2 (백드롭 또는 닫기 버튼으로 팝업 닫기) -> Step 3 (UploadWidget에 onComplete 전달 -> job 확인 페이지로 이동)]
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { X } from "lucide-react";
import UploadWidget from "./UploadWidget.jsx";

/**
 * 랜딩페이지와 동일한 업로드 위젯을 팝업 형태로 띄우는 컴포넌트입니다.
 * 업로드가 완료되면 /jobs/{job_id}/confirm 페이지로 이동합니다.
 *
 * @param {object} props
 * @param {boolean} props.open - 팝업 표시 여부
 * @param {() => void} props.onClose - 팝업 닫기 콜백
 */
export default function UploadPopup({ open, onClose }) {
  const { t } = useTranslation();
  const nav = useNavigate();

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onClick={onClose}
      data-oid="upload-popup-overlay"
    >
      <div
        className="bg-white rounded-lg shadow-lg border border-outline-variant w-full max-w-3xl max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
        data-oid="upload-popup-container"
      >
        <div className="flex items-center justify-between p-4 border-b border-outline-variant" data-oid="upload-popup-header">
          <h3 className="font-headline-md text-headline-md font-bold text-on-surface" data-oid="upload-popup-title">
            {t("page:result.uploadNewFiles")}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-lg text-on-surface-variant hover:bg-surface-container-high transition-colors"
            aria-label={t("common:actions.close")}
            data-oid="upload-popup-close"
          >
            <X size={20} />
          </button>
        </div>
        <div className="p-4" data-oid="upload-popup-body">
          <UploadWidget
            onComplete={(jobId) => nav(`/jobs/${jobId}/confirm`)}
            data-oid="upload-popup-widget"
          />
        </div>
      </div>
    </div>
  );
}
