// [Flow: Step 1 (job ID로 진입) -> Step 2 (작업 정보 및 구독 상태 로드) -> Step 3 (OCR 모델 선택 + 구독 한도 확인) -> Step 4 (승인 -> 결과 페이지 이동)]
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Loader2, CreditCard, Zap, Sparkles, FileText, Brain, CheckCircle2, Clock } from "lucide-react";
import { api } from "../api.js";
import { SkeletonCard } from "../components/Skeleton.jsx";

export default function JobConfirmPage() {
  const { jobId } = useParams();
  const nav = useNavigate();
  const { t } = useTranslation();
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [ocrModel, setOcrModel] = useState("premium");

  useEffect(() => {
    if (!jobId) return;
    load();
  }, [jobId]);

  async function load() {
    try {
      const jobData = await api.getJob(jobId);
      setJob(jobData);
      setOcrModel(jobData.ocr_model || "premium");
    } catch (e) {
      setError(e.message || t("page:confirm.loadError"));
    } finally {
      setLoading(false);
    }
  }

  async function confirm() {
    setSubmitting(true);
    setError("");
    try {
      await api.updateJob(jobId, { ocr_model: ocrModel });
      await api.confirmJob(jobId);
      nav(`/jobs/${jobId}`);
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
      if (e.message && (e.message.includes("한도") || e.message.includes("구독"))) nav("/price");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center p-6" data-oid="djxlz-q">
        <div className="w-full max-w-xl">
          <SkeletonCard rows={6} />
        </div>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center" data-oid="2yrcouf">
        <div className="text-center" data-oid="id08acd">
          <p className="text-on-surface-variant mb-4" data-oid="8x75xz5">
            {error || t("page:confirm.notFound")}
          </p>
          <Link to="/" className="text-primary hover:underline" data-oid="-cck-8r">
            {t("page:confirm.home")}
          </Link>
        </div>
      </div>
    );
  }

  const hasMedia = job.has_media || false;
  const effectiveModel = hasMedia ? "premium" : ocrModel;
  const subscription = job.subscription || {};
  const remaining = subscription.remaining || {};
  const limits = subscription.limits || {};
  const used = subscription.used || {};
  const basicPages = effectiveModel === "basic" ? job.total_pages : 0;
  const premiumPages = effectiveModel !== "basic" ? job.total_pages : 0;
  const mediaSeconds = job.media_duration_seconds || 0;
  const wouldExceed = effectiveModel === "basic" ? subscription.would_exceed_basic : subscription.would_exceed_premium;
  const reason = effectiveModel === "basic" ? subscription.reason_basic : subscription.reason_premium;
  const insufficientBasic = basicPages > (remaining.basic_pages ?? 0);
  const insufficientPremium = premiumPages > (remaining.premium_pages ?? 0);
  const insufficientMedia = mediaSeconds > (remaining.media_seconds ?? 0);
  const insufficient = !subscription.active || wouldExceed || insufficientBasic || insufficientPremium || insufficientMedia;

  return (
    <div className="min-h-screen bg-background text-on-background flex flex-col" data-oid="nxnt213">
      <nav className="w-full bg-transparent" data-oid="3-k6pmw">
        <div className="max-w-container-max mx-auto flex justify-between items-center h-20 px-gutter" data-oid="gud7eer">
          <Link
            to="/"
            className="font-headline-md text-headline-md font-bold text-primary tracking-tight"
            data-oid=".4rj2i5">
            PROOF
          </Link>
        </div>
      </nav>

      <main className="flex-grow flex items-center justify-center px-gutter py-10" data-oid="lj9rbb1">
        <div className="w-full max-w-xl bg-white border border-outline-variant shadow-xl shadow-primary/5 p-6 md:p-8" data-oid="gslt5ko">
          <div className="flex items-center gap-2 mb-5" data-oid="rte0f89">
            <Link
              to="/"
              className="text-on-surface-variant hover:text-primary transition-colors"
              data-oid="tgp-uvn">
              <ArrowLeft size={20} data-oid=".car4ii" />
            </Link>
            <h1 className="text-headline-md font-bold text-on-surface" data-oid="ujs4:cv">
              {t("page:confirm.title")}
            </h1>
          </div>

          <p className="text-body-md text-on-surface-variant mb-5" data-oid="j143g0.">
            {job.filename}
          </p>

          <div className="bg-surface-container-low p-5 space-y-3 mb-5" data-oid="x8s_b.h">
            <div className="flex justify-between text-body-md" data-oid="rfkzoa6">
              <span className="text-on-surface-variant" data-oid=".0c.0ch">
                {t("page:confirm.fileType")}
              </span>
              <span className="font-medium text-on-surface" data-oid="511-kqd">
                {job.file_type}
              </span>
            </div>
            {job.total_pages > 0 && (
              <div className="flex justify-between text-body-md" data-oid="xpiyqhh">
                <span className="text-on-surface-variant" data-oid="6nmdt2:">
                  {t("page:confirm.totalPages")}
                </span>
                <span className="font-medium text-on-surface" data-oid="cmbzuok">
                  {job.total_pages}
                </span>
              </div>
            )}
            {job.total_files > 0 && (
              <div className="flex justify-between text-body-md" data-oid="t488p9k">
                <span className="text-on-surface-variant" data-oid="4f0ghra">
                  {t("page:confirm.totalFiles")}
                </span>
                <span className="font-medium text-on-surface" data-oid="712x3lb">
                  {job.total_files}
                </span>
              </div>
            )}
            {job.media_duration_seconds > 0 && (
              <div className="flex justify-between text-body-md" data-oid="xc_gnd6">
                <span className="text-on-surface-variant" data-oid="w7i7vpy">
                  {t("page:confirm.mediaDuration")}
                </span>
                <span className="font-medium text-on-surface" data-oid="4i6okat">
                  {job.media_duration_seconds}
                  {t("page:confirm.seconds")}
                </span>
              </div>
            )}
            <div className="h-px bg-outline-variant/40 my-2" data-oid="_tkaoqf"></div>
            <div className="flex justify-between text-body-md" data-oid="subscription-plan">
              <span className="text-on-surface-variant">
                {t("page:confirm.subscriptionPlan")}
              </span>
              <span className="font-bold text-primary">
                {subscription.plan ? subscription.plan.toUpperCase() : "Free"}
              </span>
            </div>
          </div>

          <div className="mb-6" data-oid="model-select">
            <label className="block text-sm font-medium text-on-surface mb-3" data-oid="model-label">
              {t("page:confirm.ocrModel")}
            </label>
            <div className="grid grid-cols-2 gap-3" data-oid="model-cards">
              <button
                type="button"
                onClick={() => !hasMedia && setOcrModel("basic")}
                disabled={hasMedia}
                className={`w-full border p-4 text-left transition-all ${
                  effectiveModel === "basic"
                    ? "border-primary bg-primary/5 ring-2 ring-primary/20"
                    : "border-outline-variant hover:border-primary/50"
                } ${hasMedia ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
                data-oid="btn-basic">
                <div className="flex items-center gap-2 mb-3" data-oid="basic-icon">
                  <Zap size={20} className={effectiveModel === "basic" ? "text-primary" : "text-on-surface-variant"} data-oid="zap-icon" />
                  <span className="font-semibold text-on-surface" data-oid="basic-title">
                    {t("page:confirm.basicModel")}
                  </span>
                </div>
                <div className="space-y-2 text-xs text-on-surface-variant" data-oid="basic-detail">
                  <div className="flex items-start gap-1.5" data-oid="basic-f1">
                    <FileText size={14} className="shrink-0 mt-0.5 text-primary/70" data-oid="bf-icon1" />
                    <span data-oid="bf-text1">{t("page:confirm.basicFeature1")}</span>
                  </div>
                  <div className="flex items-start gap-1.5" data-oid="basic-f2">
                    <CheckCircle2 size={14} className="shrink-0 mt-0.5 text-primary/70" data-oid="bf-icon2" />
                    <span data-oid="bf-text2">{t("page:confirm.basicFeature2")}</span>
                  </div>
                  <div className="flex items-start gap-1.5" data-oid="basic-f3">
                    <Clock size={14} className="shrink-0 mt-0.5 text-primary/70" data-oid="bf-icon3" />
                    <span data-oid="bf-text3">{t("page:confirm.basicFeature3")}</span>
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
                data-oid="btn-premium">
                <div className="flex items-center gap-2 mb-3" data-oid="premium-icon">
                  <Sparkles size={20} className={effectiveModel === "premium" ? "text-primary" : "text-on-surface-variant"} data-oid="sparkles-icon" />
                  <span className="font-semibold text-on-surface" data-oid="premium-title">
                    {t("page:confirm.premiumModel")}
                  </span>
                </div>
                <div className="space-y-2 text-xs text-on-surface-variant" data-oid="premium-detail">
                  <div className="flex items-start gap-1.5" data-oid="premium-f1">
                    <Brain size={14} className="shrink-0 mt-0.5 text-primary/70" data-oid="pf-icon1" />
                    <span data-oid="pf-text1">{t("page:confirm.premiumFeature1")}</span>
                  </div>
                  <div className="flex items-start gap-1.5" data-oid="premium-f2">
                    <CheckCircle2 size={14} className="shrink-0 mt-0.5 text-primary/70" data-oid="pf-icon2" />
                    <span data-oid="pf-text2">{t("page:confirm.premiumFeature2")}</span>
                  </div>
                  <div className="flex items-start gap-1.5" data-oid="premium-f3">
                    <FileText size={14} className="shrink-0 mt-0.5 text-primary/70" data-oid="pf-icon3" />
                    <span data-oid="pf-text3">{t("page:confirm.premiumFeature3")}</span>
                  </div>
                </div>
              </button>
            </div>
            {hasMedia && (
              <p className="mt-2 text-xs text-amber-600" data-oid="media-notice">
                {t("page:confirm.mediaForcesPremium")}
              </p>
            )}
          </div>

          <div className="bg-surface-container-low p-5 space-y-3 mb-6" data-oid="subscription-usage">
            <h3 className="text-sm font-medium text-on-surface mb-2">
              {t("page:confirm.subscriptionUsage")}
            </h3>
            <div className="flex justify-between text-body-md">
              <span className="text-on-surface-variant">{t("page:confirm.basicPagesRemaining")}</span>
              <span className="font-medium text-on-surface">
                {remaining.basic_pages ?? 0} / {limits.basic_pages ?? 0}
              </span>
            </div>
            <div className="flex justify-between text-body-md">
              <span className="text-on-surface-variant">{t("page:confirm.premiumPagesRemaining")}</span>
              <span className="font-medium text-on-surface">
                {remaining.premium_pages ?? 0} / {limits.premium_pages ?? 0}
              </span>
            </div>
            <div className="flex justify-between text-body-md">
              <span className="text-on-surface-variant">{t("page:confirm.mediaMinutesRemaining")}</span>
              <span className="font-medium text-on-surface">
                {Math.floor((remaining.media_seconds ?? 0) / 60)} / {Math.floor((limits.media_seconds ?? 0) / 60)}
              </span>
            </div>
          </div>

          {insufficient && (
            <div className="mb-6 p-4 bg-red-50 text-red-700 rounded-xl border border-red-200 text-sm" data-oid="tgfo.yi">
              <p className="font-medium mb-2" data-oid="v2gs:yp">
                {reason || t("page:confirm.insufficient")}
              </p>
              <Link
                to="/price"
                className="inline-flex items-center gap-1 underline"
                data-oid="ziafjhh">
                <CreditCard size={14} data-oid="nmf-rh4" />{" "}
                {t("page:confirm.upgradePlan")}
              </Link>
            </div>
          )}

          {error && (
            <p className="text-red-600 text-sm mb-4" data-oid="dj1a-l1">
              {error}
            </p>
          )}

          <div className="flex gap-3" data-oid=".pwmux7">
            <Link
              to="/"
              className="flex-1 border border-outline-variant rounded-lg py-2.5 text-center font-medium text-on-surface hover:bg-surface-container transition-colors"
              data-oid="iog_grc">
              {t("page:confirm.cancel")}
            </Link>
            <button
              onClick={confirm}
              disabled={submitting || insufficient}
              className="flex-1 bg-primary text-on-primary rounded-lg py-2.5 font-medium hover:bg-primary-container transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              data-oid="e1yh424">
              {submitting ? (
                <>
                  <Loader2 className="animate-spin" size={18} data-oid="ybu18mh" />
                  {" "}
                  {t("page:confirm.processing")}
                </>
              ) : (
                t("page:confirm.start")
              )}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
