// [Flow: Step 1 (jobId로 작업·구독 정보 로드) -> Step 2 (OCR 모델 선택 + 비용 확인) -> Step 3 (승인 -> onConfirmed 콜백)]
// 변환 비용 확인 모달 — JobConfirmPage 의 본문 로직을 팝업 형태로 재사용.
// JobsPage 리스트에서 "결제 대기(pending)" 상태 작업 클릭 시 오픈됨.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Loader2, CreditCard, Zap, Sparkles, FileText, Brain, CheckCircle2, Clock, X } from "lucide-react";
import { api } from "../api.js";

/**
 * 변환 비용 확인 모달 컴포넌트
 * @param {string} jobId - 변환을 확정할 작업 ID
 * @param {() => void} onClose - 모달 닫기 콜백
 * @param {(jobId: string) => void} [onConfirmed] - 변환 시작 성공 후 호출되는 콜백 (선택)
 */
export default function JobConfirmModal({ jobId, onClose, onConfirmed }) {
  const { t } = useTranslation();
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [ocrModel, setOcrModel] = useState("premium");
  const [ediscoveryContext, setEdiscoveryContext] = useState("");

  // [Flow: Step 1 — jobId 변경 시 작업 정보 로드]
  useEffect(() => {
    if (!jobId) return;
    load();
  }, [jobId]);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const jobData = await api.getJob(jobId);
      setJob(jobData);
      setOcrModel(jobData.ocr_model || "premium");
      setEdiscoveryContext(jobData.ediscovery_context || "");
    } catch (e) {
      setError(e.message || t("page:confirm.loadError"));
    } finally {
      setLoading(false);
    }
  }

  // [Flow: Step 3 — 변환 시작: 모델/맥락 저장 -> confirmJob 호출 -> onConfirmed]
  async function confirm() {
    setSubmitting(true);
    setError("");
    try {
      await api.updateJob(jobId, { ocr_model: ocrModel, ediscovery_context: ediscoveryContext.trim() });
      await api.confirmJob(jobId);
      onConfirmed?.(jobId);
      onClose();
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    } finally {
      setSubmitting(false);
    }
  }

  // ESC 키로 모달 닫기
  useEffect(() => {
    if (!jobId) return;
    const handleEsc = (e) => { if (e.key === "Escape" && !submitting) onClose(); };
    window.addEventListener("keydown", handleEsc);
    return () => window.removeEventListener("keydown", handleEsc);
  }, [jobId, submitting, onClose]);

  if (!jobId) return null;

  const hasMedia = job?.has_media || false;
  const effectiveModel = hasMedia ? "premium" : ocrModel;
  const subscription = job?.subscription || {};
  const pointsBalance = subscription.points_balance ?? 0;
  const remainingPoints = subscription.remaining ?? 0;
  const isUnlimited = remainingPoints === -1;
  const cost = job?.cost || { points: 0 };
  const estimatedCost = effectiveModel === "basic" ? (job?.cost_basic || cost) : (job?.cost_premium || cost);
  const wouldExceed = effectiveModel === "basic" ? subscription.would_exceed_basic : subscription.would_exceed_premium;
  const reason = effectiveModel === "basic" ? subscription.reason_basic : subscription.reason_premium;
  const insufficient = !subscription.active || wouldExceed || (!isUnlimited && estimatedCost.points > remainingPoints);

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4 overflow-y-auto"
      data-oid="job-confirm-modal-overlay"
      onClick={(e) => { if (e.target === e.currentTarget && !submitting) onClose(); }}
    >
      <div
        className="relative w-full max-w-xl bg-white border border-outline-variant shadow-2xl my-8"
        data-oid="job-confirm-modal-card"
      >
        {/* 닫기 버튼 */}
        <button
          onClick={() => !submitting && onClose()}
          disabled={submitting}
          className="absolute top-3 right-3 p-1.5 rounded-lg text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors disabled:opacity-50 z-10"
          data-oid="job-confirm-modal-close"
          aria-label={t("page:confirm.cancel")}
        >
          <X size={20} />
        </button>

        <div className="p-4 md:p-6 lg:p-8 max-h-[90vh] overflow-y-auto" data-oid="job-confirm-modal-body">
          {loading ? (
            <div className="flex items-center justify-center py-20" data-oid="job-confirm-modal-loading">
              <Loader2 className="animate-spin text-primary" size={32} />
            </div>
          ) : !job ? (
            <div className="text-center py-20" data-oid="job-confirm-modal-error">
              <p className="text-on-surface-variant mb-4">{error || t("page:confirm.notFound")}</p>
              <button
                onClick={onClose}
                className="text-primary hover:underline"
                data-oid="job-confirm-modal-back"
              >
                {t("page:confirm.cancel")}
              </button>
            </div>
          ) : (
            <>
              <h1 className="text-headline-md font-bold text-on-surface mb-1 pr-8" data-oid="job-confirm-modal-title">
                {t("page:confirm.title")}
              </h1>
              <p className="text-body-md text-on-surface-variant mb-5 break-all" data-oid="job-confirm-modal-filename">
                {job.filename}
              </p>

              {/* 작업 메타데이터 */}
              <div className="bg-surface-container-low p-5 space-y-3 mb-5" data-oid="job-confirm-modal-meta">
                <div className="flex justify-between text-body-md">
                  <span className="text-on-surface-variant">{t("page:confirm.fileType")}</span>
                  <span className="font-medium text-on-surface">{job.file_type}</span>
                </div>
                {job.total_pages > 0 && (
                  <div className="flex justify-between text-body-md">
                    <span className="text-on-surface-variant">{t("page:confirm.totalPages")}</span>
                    <span className="font-medium text-on-surface">{job.total_pages}</span>
                  </div>
                )}
                {job.total_files > 0 && (
                  <div className="flex justify-between text-body-md">
                    <span className="text-on-surface-variant">{t("page:confirm.totalFiles")}</span>
                    <span className="font-medium text-on-surface">{job.total_files}</span>
                  </div>
                )}
                {job.media_duration_seconds > 0 && (
                  <div className="flex justify-between text-body-md">
                    <span className="text-on-surface-variant">{t("page:confirm.mediaDuration")}</span>
                    <span className="font-medium text-on-surface">
                      {job.media_duration_seconds}{t("page:confirm.seconds")}
                    </span>
                  </div>
                )}
                <div className="h-px bg-outline-variant/40 my-2" />
                <div className="flex justify-between text-body-md">
                  <span className="text-on-surface-variant">{t("page:confirm.subscriptionPlan")}</span>
                  <span className="font-bold text-primary">
                    {subscription.plan ? subscription.plan.toUpperCase() : "Free"}
                  </span>
                </div>
              </div>

              {/* OCR 모델 선택 */}
              <div className="mb-6" data-oid="job-confirm-modal-model">
                <label className="block text-sm font-medium text-on-surface mb-3">
                  {t("page:confirm.ocrModel")}
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => !hasMedia && setOcrModel("basic")}
                    disabled={hasMedia}
                    className={`w-full border p-4 text-left transition-all ${
                      effectiveModel === "basic"
                        ? "border-primary bg-primary/5 ring-2 ring-primary/20"
                        : "border-outline-variant hover:border-primary/50"
                    } ${hasMedia ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                    data-oid="job-confirm-modal-btn-basic"
                  >
                    <div className="flex items-center gap-2 mb-3">
                      <Zap size={20} className={effectiveModel === "basic" ? "text-primary" : "text-on-surface-variant"} />
                      <span className="font-semibold text-on-surface">{t("page:confirm.basicModel")}</span>
                    </div>
                    <div className="space-y-2 text-xs text-on-surface-variant">
                      <div className="flex items-start gap-1.5">
                        <FileText size={14} className="shrink-0 mt-0.5 text-primary/70" />
                        <span>{t("page:confirm.basicFeature1")}</span>
                      </div>
                      <div className="flex items-start gap-1.5">
                        <CheckCircle2 size={14} className="shrink-0 mt-0.5 text-primary/70" />
                        <span>{t("page:confirm.basicFeature2")}</span>
                      </div>
                      <div className="flex items-start gap-1.5">
                        <Clock size={14} className="shrink-0 mt-0.5 text-primary/70" />
                        <span>{t("page:confirm.basicFeature3")}</span>
                      </div>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setOcrModel("premium")}
                    className={`w-full border p-4 text-left transition-all cursor-pointer ${
                      effectiveModel === "premium"
                        ? "border-primary bg-primary/5 ring-2 ring-primary/20"
                        : "border-outline-variant hover:border-primary/50"
                    }`}
                    data-oid="job-confirm-modal-btn-premium"
                  >
                    <div className="flex items-center gap-2 mb-3">
                      <Sparkles size={20} className={effectiveModel === "premium" ? "text-primary" : "text-on-surface-variant"} />
                      <span className="font-semibold text-on-surface">{t("page:confirm.premiumModel")}</span>
                    </div>
                    <div className="space-y-2 text-xs text-on-surface-variant">
                      <div className="flex items-start gap-1.5">
                        <Brain size={14} className="shrink-0 mt-0.5 text-primary/70" />
                        <span>{t("page:confirm.premiumFeature1")}</span>
                      </div>
                      <div className="flex items-start gap-1.5">
                        <CheckCircle2 size={14} className="shrink-0 mt-0.5 text-primary/70" />
                        <span>{t("page:confirm.premiumFeature2")}</span>
                      </div>
                      <div className="flex items-start gap-1.5">
                        <FileText size={14} className="shrink-0 mt-0.5 text-primary/70" />
                        <span>{t("page:confirm.premiumFeature3")}</span>
                      </div>
                    </div>
                  </button>
                </div>
                {hasMedia && (
                  <p className="mt-2 text-xs text-amber-600">{t("page:confirm.mediaForcesPremium")}</p>
                )}
              </div>

              {/* e-Discovery 분석 맥락 입력 */}
              <div className="mb-6 bg-surface-container-lowest border border-outline-variant p-4" data-oid="job-confirm-modal-ctx">
                <label htmlFor="job-confirm-ctx" className="block text-sm font-medium text-on-surface mb-1.5">
                  {t("page:upload.ediscoveryContextLabel")}
                </label>
                <p className="text-xs text-on-surface-variant mb-2">
                  {t("page:upload.ediscoveryContextHint")}
                </p>
                <textarea
                  id="job-confirm-ctx"
                  value={ediscoveryContext}
                  onChange={(e) => setEdiscoveryContext(e.target.value)}
                  placeholder={t("page:upload.ediscoveryContextPlaceholder")}
                  rows={3}
                  className="w-full text-sm text-on-surface bg-surface border border-outline-variant rounded-lg p-2.5 focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
                  data-oid="job-confirm-modal-ctx-input"
                />
              </div>

              {/* 크레딧 잔액 / 예상 비용 */}
              <div className="bg-surface-container-low p-5 space-y-3 mb-6" data-oid="job-confirm-modal-usage">
                <h3 className="text-sm font-medium text-on-surface mb-2">
                  {t("page:confirm.pointsBalance")}
                </h3>
                <div className="flex justify-between text-body-md">
                  <span className="text-on-surface-variant">{t("page:confirm.pointsBalance")}</span>
                  <span className="font-medium text-on-surface">
                    {isUnlimited ? t("page:confirm.unlimited") : `${pointsBalance.toLocaleString()}${t("common:points.point")}`}
                  </span>
                </div>
                <div className="flex justify-between text-body-md">
                  <span className="text-on-surface-variant">{t("page:confirm.estimatedCost")}</span>
                  <span className="font-medium text-on-surface">
                    {estimatedCost.points.toLocaleString()}{t("common:points.point")}
                  </span>
                </div>
                <div className="flex justify-between text-body-md">
                  <span className="text-on-surface-variant">{t("page:confirm.pointsRemaining")}</span>
                  <span className="font-medium text-on-surface">
                    {isUnlimited ? t("page:confirm.unlimited") : `${Math.max(0, pointsBalance - estimatedCost.points).toLocaleString()}${t("common:points.point")}`}
                  </span>
                </div>
              </div>

              {insufficient && (
                <div className="mb-6 p-4 bg-red-50 text-red-700 rounded-xl border border-red-200 text-sm" data-oid="job-confirm-modal-insufficient">
                  <p className="font-medium mb-2">{reason || t("page:confirm.insufficient")}</p>
                  <Link to="/price" className="inline-flex items-center gap-1 underline" data-oid="job-confirm-modal-upgrade">
                    <CreditCard size={14} /> {t("page:confirm.upgradePlan")}
                  </Link>
                </div>
              )}

              {error && (
                <p className="text-red-600 text-sm mb-4" data-oid="job-confirm-modal-error-msg">{error}</p>
              )}

              <div className="flex gap-3" data-oid="job-confirm-modal-actions">
                <button
                  onClick={onClose}
                  disabled={submitting}
                  className="flex-1 border border-outline-variant rounded-lg py-2.5 text-center font-medium text-on-surface hover:bg-surface-container transition-colors disabled:opacity-50"
                  data-oid="job-confirm-modal-cancel-btn"
                >
                  {t("page:confirm.cancel")}
                </button>
                <button
                  onClick={confirm}
                  disabled={submitting || insufficient}
                  className="flex-1 bg-primary text-on-primary rounded-lg py-2.5 font-medium hover:bg-primary-container transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                  data-oid="job-confirm-modal-start-btn"
                >
                  {submitting ? (
                    <>
                      <Loader2 className="animate-spin" size={18} />
                      {t("page:confirm.processing")}
                    </>
                  ) : (
                    t("page:confirm.start")
                  )}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
