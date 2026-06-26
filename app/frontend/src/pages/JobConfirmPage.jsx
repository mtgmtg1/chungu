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
    { value: "hybrid", label: t("page:confirm.hybrid") },
  ];

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
        data-oid="9m0x6.s"
      >
        <Loader2
          className="animate-spin text-primary"
          size={32}
          data-oid="tu8c0yk"
        />
      </div>
    );
  }

  if (!job) {
    return (
      <div
        className="min-h-screen bg-background flex items-center justify-center"
        data-oid="n-0jdni"
      >
        <div className="text-center" data-oid="6ux-ilm">
          <p className="text-on-surface-variant mb-4" data-oid="3bo2fid">
            {error || t("page:confirm.notFound")}
          </p>
          <Link
            to="/"
            className="text-primary hover:underline"
            data-oid="9y6e1wn"
          >
            {t("page:confirm.home")}
          </Link>
        </div>
      </div>
    );
  }

  const balance = profile?.points_balance ?? job.balance ?? 0;
  const cost = job.cost?.points ?? 0;
  const insufficient = balance < cost;

  return (
    <div
      className="min-h-screen bg-background text-on-background flex flex-col"
      data-oid="ka7pw7p"
    >
      <nav className="w-full bg-transparent" data-oid="tt0ph-t">
        <div
          className="max-w-container-max mx-auto flex justify-between items-center h-20 px-gutter"
          data-oid="i__hlij"
        >
          <Link
            to="/"
            className="font-headline-md text-headline-md font-bold text-primary tracking-tight"
            data-oid="hoq6k5m"
          >
            Chungu
          </Link>
        </div>
      </nav>

      <main
        className="flex-grow flex items-center justify-center px-gutter py-12"
        data-oid="tlf3b.i"
      >
        <div
          className="w-full max-w-xl bg-white rounded-[32px] border border-outline-variant shadow-xl shadow-primary/5 p-8 md:p-10"
          data-oid="5-he_1_"
        >
          <div className="flex items-center gap-2 mb-6" data-oid="mcg2k5:">
            <Link
              to="/"
              className="text-on-surface-variant hover:text-primary transition-colors"
              data-oid="r5oz3ax"
            >
              <ArrowLeft size={20} data-oid="n66zf38" />
            </Link>
            <h1
              className="text-headline-lg font-bold text-on-surface"
              data-oid="yxzv5n:"
            >
              {t("page:confirm.title")}
            </h1>
          </div>

          <p
            className="text-body-md text-on-surface-variant mb-6"
            data-oid=":jyrhre"
          >
            {job.filename}
          </p>

          <div
            className="bg-surface-container-low rounded-2xl p-6 space-y-3 mb-6"
            data-oid="o14qs51"
          >
            <div
              className="flex justify-between text-body-md"
              data-oid="3aiva9d"
            >
              <span className="text-on-surface-variant" data-oid="e5rjj60">
                {t("page:confirm.fileType")}
              </span>
              <span className="font-medium text-on-surface" data-oid="my7._h.">
                {job.file_type}
              </span>
            </div>
            {job.total_pages > 0 && (
              <div
                className="flex justify-between text-body-md"
                data-oid="qcagu4k"
              >
                <span className="text-on-surface-variant" data-oid="_we1x-k">
                  {t("page:confirm.totalPages")}
                </span>
                <span
                  className="font-medium text-on-surface"
                  data-oid="0t165.m"
                >
                  {job.total_pages}
                </span>
              </div>
            )}
            {job.total_files > 0 && (
              <div
                className="flex justify-between text-body-md"
                data-oid="2gkih-1"
              >
                <span className="text-on-surface-variant" data-oid="sb7ejwx">
                  {t("page:confirm.totalFiles")}
                </span>
                <span
                  className="font-medium text-on-surface"
                  data-oid="d.vb0tx"
                >
                  {job.total_files}
                </span>
              </div>
            )}
            {job.media_duration_seconds > 0 && (
              <div
                className="flex justify-between text-body-md"
                data-oid="2cowq6o"
              >
                <span className="text-on-surface-variant" data-oid="1w45ch-">
                  {t("page:confirm.mediaDuration")}
                </span>
                <span
                  className="font-medium text-on-surface"
                  data-oid="07:y_lc"
                >
                  {job.media_duration_seconds}
                  {t("page:confirm.seconds")}
                </span>
              </div>
            )}
            <div
              className="h-px bg-outline-variant/40 my-2"
              data-oid="u576ew8"
            ></div>
            <div
              className="flex justify-between text-body-md"
              data-oid="m6g_n2e"
            >
              <span className="text-on-surface-variant" data-oid="yct1x55">
                {t("page:confirm.requiredPoints")}
              </span>
              <span className="font-bold text-primary" data-oid="mhxvzts">
                {cost} {t("common:points.point")}
              </span>
            </div>
            <div
              className="flex justify-between text-body-md"
              data-oid="bnerws9"
            >
              <span className="text-on-surface-variant" data-oid=":2hou5o">
                {t("page:confirm.myBalance")}
              </span>
              <span className="font-medium text-on-surface" data-oid="v1yo30n">
                {balance} {t("common:points.point")}
              </span>
            </div>
          </div>

          <details className="mb-6 group" data-oid="-8jr1z8">
            <summary
              className="flex items-center gap-2 cursor-pointer text-body-md text-on-surface-variant hover:text-primary transition-colors"
              data-oid="qy:.oip"
            >
              <Settings2 size={18} data-oid="xyr:a26" />
              <span data-oid="nb10ldj">
                {t("page:confirm.advancedOptions")}
              </span>
            </summary>
            <div
              className="mt-4 space-y-4 bg-surface-container-low rounded-2xl p-5"
              data-oid=":chxxrl"
            >
              <div data-oid="x5wazyn">
                <label
                  className="block text-sm font-medium text-on-surface mb-2"
                  data-oid="iky.844"
                >
                  {t("page:confirm.analysisMode")}
                </label>
                <div className="flex gap-3" data-oid="nafbi7v">
                  {pipelineOptions.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setPipeline(opt.value)}
                      className={`flex-1 border rounded-lg px-3 py-2 text-sm text-left transition-colors ${
                        pipeline === opt.value
                          ? "border-primary bg-primary/5 text-primary"
                          : "border-outline-variant text-on-surface"
                      }`}
                      data-oid="ed59y5a"
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
              <div data-oid="byg9hq3">
                <label
                  className="block text-sm font-medium text-on-surface mb-1"
                  data-oid="riga6n8"
                >
                  {t("page:confirm.extractColumns")}
                </label>
                <input
                  value={columns}
                  onChange={(e) => setColumns(e.target.value)}
                  placeholder={t("page:confirm.extractColumnsPlaceholder")}
                  className="w-full border border-outline-variant rounded-lg px-3 py-2 bg-white"
                  data-oid="8c7go0g"
                />
              </div>
              <div data-oid="i1tkvjd">
                <label
                  className="block text-sm font-medium text-on-surface mb-1"
                  data-oid="p7hyv7g"
                >
                  {t("page:confirm.additionalPrompt")}
                </label>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={2}
                  placeholder={t("page:confirm.additionalPromptPlaceholder")}
                  className="w-full border border-outline-variant rounded-lg px-3 py-2 bg-white"
                  data-oid=":zph:5p"
                />
              </div>
            </div>
          </details>

          {insufficient && (
            <div
              className="mb-6 p-4 bg-red-50 text-red-700 rounded-xl border border-red-200 text-sm"
              data-oid="oqcdlgr"
            >
              <p className="font-medium mb-2" data-oid="tdvcg9-">
                {t("page:confirm.insufficient")}
              </p>
              <Link
                to="/payment"
                className="inline-flex items-center gap-1 underline"
                data-oid="vpd_nrw"
              >
                <CreditCard size={14} data-oid="prse3p2" />{" "}
                {t("page:confirm.recharge")}
              </Link>
            </div>
          )}

          {error && (
            <p className="text-red-600 text-sm mb-4" data-oid="husl4x1">
              {error}
            </p>
          )}

          <div className="flex gap-3" data-oid="8l8zms_">
            <Link
              to="/"
              className="flex-1 border border-outline-variant rounded-xl py-3 text-center font-medium text-on-surface hover:bg-surface-container transition-colors"
              data-oid="u1i.adk"
            >
              {t("page:confirm.cancel")}
            </Link>
            <button
              onClick={confirm}
              disabled={submitting || insufficient}
              className="flex-1 bg-primary text-on-primary rounded-xl py-3 font-medium hover:bg-primary-container transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              data-oid="5.vyytz"
            >
              {submitting ? (
                <>
                  <Loader2
                    className="animate-spin"
                    size={18}
                    data-oid="ah7z9yi"
                  />{" "}
                  {t("page:confirm.processing")}
                </>
              ) : (
                t("page:confirm.startWithCost", { cost })
              )}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
