// [Flow: Step 1 (job ID로 진입) -> Step 2 (작업 정보 로드) -> Step 3 (비용 확인 + 고급 옵션) -> Step 4 (승인 -> 결과 페이지 이동)]
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Loader2, CreditCard, Settings2 } from "lucide-react";
import { api } from "../api.js";

export default function JobConfirmPage() {
  const { jobId } = useParams();
  const nav = useNavigate();
  const { t } = useTranslation();
  const [job, setJob] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [pipeline, setPipeline] = useState("vision");
  const [columns, setColumns] = useState("");
  const [prompt, setPrompt] = useState("");

  const pipelineOptions = [
  { value: "vision", label: t("page:confirm.vision") },
  { value: "hybrid", label: t("page:confirm.hybrid") }];


  useEffect(() => {
    if (!jobId) return;
    load();
  }, [jobId]);

  async function load() {
    try {
      const [jobData, me] = await Promise.all([api.getJob(jobId), api.me()]);
      setJob(jobData);
      setProfile(me);
      setPipeline(jobData.pipeline || "vision");
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
      await api.updateJob(jobId, { pipeline, columns, prompt });
      await api.confirmJob(jobId);
      nav(`/jobs/${jobId}`);
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
      if (e.message && e.message.includes("point")) nav("/payment");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return (
      <div
        className="min-h-screen bg-background flex items-center justify-center"
        data-oid="djxlz-q">

        <Loader2
          className="animate-spin text-primary"
          size={32}
          data-oid="shu7kyb" />

      </div>);

  }

  if (!job) {
    return (
      <div
        className="min-h-screen bg-background flex items-center justify-center"
        data-oid="2yrcouf">

        <div className="text-center" data-oid="id08acd">
          <p className="text-on-surface-variant mb-4" data-oid="8x75xz5">
            {error || t("page:confirm.notFound")}
          </p>
          <Link
            to="/"
            className="text-primary hover:underline"
            data-oid="-cck-8r">

            {t("page:confirm.home")}
          </Link>
        </div>
      </div>);

  }

  const balance = profile?.points_balance ?? job.balance ?? 0;
  const cost = job.cost?.points ?? 0;
  const insufficient = balance < cost;

  return (
    <div
      className="min-h-screen bg-background text-on-background flex flex-col"
      data-oid="nxnt213">

      <nav className="w-full bg-transparent" data-oid="3-k6pmw">
        <div
          className="max-w-container-max mx-auto flex justify-between items-center h-20 px-gutter"
          data-oid="gud7eer">

          <Link
            to="/"
            className="font-headline-md text-headline-md font-bold text-primary tracking-tight"
            data-oid=".4rj2i5">

            Chungu
          </Link>
        </div>
      </nav>

      <main
        className="flex-grow flex items-center justify-center px-gutter py-12"
        data-oid="lj9rbb1">

        <div
          className="w-full max-w-xl bg-white rounded-[32px] border border-outline-variant shadow-xl shadow-primary/5 p-8 md:p-10"
          data-oid="gslt5ko">

          <div className="flex items-center gap-2 mb-6" data-oid="rte0f89">
            <Link
              to="/"
              className="text-on-surface-variant hover:text-primary transition-colors"
              data-oid="tgp-uvn">

              <ArrowLeft size={20} data-oid=".car4ii" />
            </Link>
            <h1
              className="text-headline-lg font-bold text-on-surface"
              data-oid="ujs4:cv">

              {t("page:confirm.title")}
            </h1>
          </div>

          <p
            className="text-body-md text-on-surface-variant mb-6"
            data-oid="j143g0.">

            {job.filename}
          </p>

          <div
            className="bg-surface-container-low rounded-2xl p-6 space-y-3 mb-6"
            data-oid="x8s_b.h">

            <div
              className="flex justify-between text-body-md"
              data-oid="rfkzoa6">

              <span className="text-on-surface-variant" data-oid=".0c.0ch">
                {t("page:confirm.fileType")}
              </span>
              <span className="font-medium text-on-surface" data-oid="511-kqd">
                {job.file_type}
              </span>
            </div>
            {job.total_pages > 0 &&
            <div
              className="flex justify-between text-body-md"
              data-oid="xpiyqhh">

                <span className="text-on-surface-variant" data-oid="6nmdt2:">
                  {t("page:confirm.totalPages")}
                </span>
                <span
                className="font-medium text-on-surface"
                data-oid="cmbzuok">

                  {job.total_pages}
                </span>
              </div>
            }
            {job.total_files > 0 &&
            <div
              className="flex justify-between text-body-md"
              data-oid="t488p9k">

                <span className="text-on-surface-variant" data-oid="4f0ghra">
                  {t("page:confirm.totalFiles")}
                </span>
                <span
                className="font-medium text-on-surface"
                data-oid="712x3lb">

                  {job.total_files}
                </span>
              </div>
            }
            {job.media_duration_seconds > 0 &&
            <div
              className="flex justify-between text-body-md"
              data-oid="xc_gnd6">

                <span className="text-on-surface-variant" data-oid="w7i7vpy">
                  {t("page:confirm.mediaDuration")}
                </span>
                <span
                className="font-medium text-on-surface"
                data-oid="4i6okat">

                  {job.media_duration_seconds}
                  {t("page:confirm.seconds")}
                </span>
              </div>
            }
            <div
              className="h-px bg-outline-variant/40 my-2"
              data-oid="_tkaoqf">
            </div>
            <div
              className="flex justify-between text-body-md"
              data-oid="0e_flir">

              <span className="text-on-surface-variant" data-oid="w-n2:pj">
                {t("page:confirm.requiredPoints")}
              </span>
              <span className="font-bold text-primary" data-oid="f:gbk8s">
                {cost} {t("common:points.point")}
              </span>
            </div>
            <div
              className="flex justify-between text-body-md"
              data-oid="8qbj:al">

              <span className="text-on-surface-variant" data-oid="bsgw7yy">
                {t("page:confirm.myBalance")}
              </span>
              <span className="font-medium text-on-surface" data-oid="vu2_p3k">
                {balance} {t("common:points.point")}
              </span>
            </div>
          </div>

          <details className="mb-6 group" data-oid="9vqgwag">
            <summary
              className="flex items-center gap-2 cursor-pointer text-body-md text-on-surface-variant hover:text-primary transition-colors"
              data-oid="bbjoa1o">

              <Settings2 size={18} data-oid="q-lb4dr" />
              <span data-oid="rr27gbt">
                {t("page:confirm.advancedOptions")}
              </span>
            </summary>
            <div
              className="mt-4 space-y-4 bg-surface-container-low rounded-2xl p-5"
              data-oid="ppq.99c">

              <div data-oid="ijztqfe">
                <label
                  className="block text-sm font-medium text-on-surface mb-2"
                  data-oid="ygfwfd3">

                  {t("page:confirm.analysisMode")}
                </label>
                <div className="flex gap-3" data-oid="zxv4sf2">
                  {pipelineOptions.map((opt) =>
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setPipeline(opt.value)}
                    className={`flex-1 border rounded-lg px-3 py-2 text-sm text-left transition-colors ${
                    pipeline === opt.value ?
                    "border-primary bg-primary/5 text-primary" :
                    "border-outline-variant text-on-surface"}`
                    }
                    data-oid="807_h:d">

                      {opt.label}
                    </button>
                  )}
                </div>
              </div>
              <div data-oid="10iz:xq">
                <label
                  className="block text-sm font-medium text-on-surface mb-1"
                  data-oid="o61:4ls">

                  {t("page:confirm.extractColumns")}
                </label>
                <input
                  value={columns}
                  onChange={(e) => setColumns(e.target.value)}
                  placeholder={t("page:confirm.extractColumnsPlaceholder")}
                  className="w-full border border-outline-variant rounded-lg px-3 py-2 bg-white"
                  data-oid="vltcbyj" />

              </div>
              <div data-oid="35qt5w-">
                <label
                  className="block text-sm font-medium text-on-surface mb-1"
                  data-oid="ccv7hmm">

                  {t("page:confirm.additionalPrompt")}
                </label>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={2}
                  placeholder={t("page:confirm.additionalPromptPlaceholder")}
                  className="w-full border border-outline-variant rounded-lg px-3 py-2 bg-white"
                  data-oid="lg7__o4" />

              </div>
            </div>
          </details>

          {insufficient &&
          <div
            className="mb-6 p-4 bg-red-50 text-red-700 rounded-xl border border-red-200 text-sm"
            data-oid="tgfo.yi">

              <p className="font-medium mb-2" data-oid="v2gs:yp">
                {t("page:confirm.insufficient")}
              </p>
              <Link
              to="/payment"
              className="inline-flex items-center gap-1 underline"
              data-oid="ziafjhh">

                <CreditCard size={14} data-oid="nmf-rh4" />{" "}
                {t("page:confirm.recharge")}
              </Link>
            </div>
          }

          {error &&
          <p className="text-red-600 text-sm mb-4" data-oid="dj1a-l1">
              {error}
            </p>
          }

          <div className="flex gap-3" data-oid=".pwmux7">
            <Link
              to="/"
              className="flex-1 border border-outline-variant rounded-xl py-3 text-center font-medium text-on-surface hover:bg-surface-container transition-colors"
              data-oid="iog_grc">

              {t("page:confirm.cancel")}
            </Link>
            <button
              onClick={confirm}
              disabled={submitting || insufficient}
              className="flex-1 bg-primary text-on-primary rounded-xl py-3 font-medium hover:bg-primary-container transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              data-oid="e1yh424">

              {submitting ?
              <>
                  <Loader2
                  className="animate-spin"
                  size={18}
                  data-oid="ybu18mh" />
                {" "}
                  {t("page:confirm.processing")}
                </> :

              t("page:confirm.startWithCost", { cost })
              }
            </button>
          </div>
        </div>
      </main>
    </div>);

}