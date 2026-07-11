// [Flow: Step 1 (열림/닫힘 상태 수신) -> Step 2 (백드롭 또는 닫기 버튼으로 팝업 닫기) -> Step 3 (UploadWidget에 jobId/onProgress/onComplete 전달 -> 기존 Job에 파일 추가 또는 새 Job 생성)]
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { X } from "lucide-react";
import UploadWidget from "./UploadWidget.jsx";

/**
 * 랜딩페이지와 동일한 업로드 위젯을 팝업 형태로 띄우는 컴포넌트입니다.
 * jobId가 전달되면 기존 Job에 파일을 추가하고, 그렇지 않으면 새 Job을 생성하여
 * /jobs/{job_id}/confirm 페이지로 이동합니다.
 *
 * @param {object} props
 * @param {boolean} props.open - 팝업 표시 여부
 * @param {() => void} props.onClose - 팝업 닫기 콜백
 * @param {string} [props.jobId] - 기존 Job에 파일을 추가하는 모드일 때 사용
 * @param {(progress: object) => void} [props.onProgress] - 업로드 진행률 변경 시 호출
 * @param {(jobId: string) => void} [props.onComplete] - 업로드 완료 시 호출 (jobId 모드에서만 사용)
 */
export default function UploadPopup({ open, onClose, jobId, onProgress, onComplete }) {
  const { t } = useTranslation();
  const nav = useNavigate();

  if (!open) return null;

  // [Flow: Step 1 (jobId가 있으면 기존 Job에 추가 — onComplete 호출) -> Step 2 (없으면 새 Job 생성 — confirm 페이지로 이동)]
  function handleComplete(completedJobId) {
    if (jobId && onComplete) {
      onComplete(completedJobId);
    } else {
      nav(`/jobs/${completedJobId}/confirm`);
    }
  }

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
            jobId={jobId}
            onProgress={onProgress}
            onComplete={handleComplete}
            data-oid="upload-popup-widget"
          />
        </div>
      </div>
    </div>
  );
}
