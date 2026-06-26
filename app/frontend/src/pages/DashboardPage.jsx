// [Flow: Step 1 (사용자/프로필 + 작업 목록 로드) -> Step 2 (종합 통계 계산) -> Step 3 (요약 카드 + 상태 분포 + 최근 작업 렌더링)]
import { useEffect, useMemo, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Coins,
  Loader2,
  ArrowRight,
  Upload,
  FileText,
  Eye,
  CreditCard,
} from "lucide-react";
import { useAuth } from "../AuthContext.jsx";
import { api } from "../api.js";
import i18n from "../i18n.js";
import SidebarLayout from "../components/SidebarLayout.jsx";

const STATUS_COLOR = {
  done: "bg-green-50 text-green-700 border-green-100",
  error: "bg-red-50 text-red-700 border-red-100",
  pending:
    "bg-surface-container-high text-on-surface-variant border-outline-variant",
  queued: "bg-primary-container/10 text-primary border-primary/10",
  ocr: "bg-primary-container/10 text-primary border-primary/10",
  merging: "bg-primary-container/10 text-primary border-primary/10",
};

export default function DashboardPage() {
  const { user, loading: authLoading } = useAuth();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [profile, setProfile] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const statusLabel = (status) => t(`common:status.${status}`) || status;

  useEffect(() => {
    if (!user) return;
    load();
  }, [user]);

  async function load() {
    setLoading(true);
    try {
      const [me, list] = await Promise.all([api.me(), api.listJobs()]);
      setProfile(me);
      setJobs(list);
    } catch (e) {
      setError(e.message || t("page:errors.loadFailed"));
    } finally {
      setLoading(false);
    }
  }

  const stats = useMemo(() => {
    const total = jobs.length;
    const done = jobs.filter((j) => j.status === "done").length;
    const active = jobs.filter(
      (j) => j.status !== "done" && j.status !== "error",
    ).length;
    const error = jobs.filter((j) => j.status === "error").length;
    const totalPages = jobs.reduce(
      (sum, j) => sum + (j.total_pages || j.total_files || 0),
      0,
    );
    const recent = [...jobs]
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
      .slice(0, 5);
    return { total, done, active, error, totalPages, recent };
  }, [jobs]);

  function formatDate(dateStr) {
    if (!dateStr) return "-";
    return new Date(dateStr).toLocaleString(i18n.language, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  if (authLoading || (!user && !error)) {
    return (
      <div
        className="min-h-screen flex items-center justify-center bg-background"
        data-oid="02ogmhx"
      >
        <Loader2
          className="animate-spin text-primary"
          size={32}
          data-oid="p4bxs_9"
        />
      </div>
    );
  }

  if (!user) {
    return (
      <div
        className="min-h-screen flex items-center justify-center bg-background"
        data-oid="o6cpldz"
      >
        <div className="text-center" data-oid="48erlln">
          <p className="mb-4 text-on-surface-variant" data-oid="v6juac2">
            {t("common:auth.loginRequired")}
          </p>
          <button
            onClick={() => navigate("/login")}
            className="bg-primary text-on-primary px-4 py-2 rounded-lg"
            data-oid="jk:foo0"
          >
            {t("page:auth.loginButton")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <SidebarLayout
      title={t("page:dashboard.title")}
      subtitle={t("page:dashboard.subtitle")}
      data-oid="n8otx5r"
    >
      {error && (
        <div
          className="bg-red-50 text-red-700 px-4 py-3 rounded-lg mb-6 flex items-center gap-2 border border-red-200"
          data-oid="yutjq_5"
        >
          <span className="material-symbols-outlined" data-oid="f3tm.bp">
            error
          </span>
          {error}
        </div>
      )}

      {/* Summary cards */}
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-gutter mb-stack-lg"
        data-oid="aah5_rc"
      >
        <div className="glass-panel p-6 rounded-2xl" data-oid="vnbx2f2">
          <div
            className="flex items-center justify-between mb-4"
            data-oid="1-ya6t7"
          >
            <p
              className="font-label-sm text-label-sm text-on-surface-variant"
              data-oid="4i8-v9o"
            >
              {t("page:dashboard.points")}
            </p>
            <div
              className="p-2 bg-yellow-50 rounded-lg text-yellow-600"
              data-oid="ci5jy:i"
            >
              <Coins size={20} data-oid="w7-96kh" />
            </div>
          </div>
          <p className="text-3xl font-bold text-on-surface" data-oid="a52belk">
            {profile?.points_balance?.toLocaleString() ?? "-"} P
          </p>
          <Link
            to="/payment"
            className="mt-3 inline-flex items-center gap-1 text-primary text-sm font-medium hover:underline"
            data-oid="qg_k4nb"
          >
            <CreditCard size={14} data-oid=":xnax6c" />{" "}
            {t("page:dashboard.recharge")}
          </Link>
        </div>

        <div className="glass-panel p-6 rounded-2xl" data-oid="gm_2m7.">
          <div
            className="flex items-center justify-between mb-4"
            data-oid="w0f_3u."
          >
            <p
              className="font-label-sm text-label-sm text-on-surface-variant"
              data-oid="t1b6q-l"
            >
              {t("page:dashboard.totalJobs")}
            </p>
            <div
              className="p-2 bg-primary/10 rounded-lg text-primary"
              data-oid="stvrim_"
            >
              <span className="material-symbols-outlined" data-oid="mxke524">
                task
              </span>
            </div>
          </div>
          <p className="text-3xl font-bold text-on-surface" data-oid="wlkmuhg">
            {stats.total}
          </p>
          <p
            className="mt-3 text-sm text-on-surface-variant"
            data-oid="t1oh0hv"
          >
            {t("page:dashboard.totalJobsDesc")}
          </p>
        </div>

        <div className="glass-panel p-6 rounded-2xl" data-oid="hzf4au7">
          <div
            className="flex items-center justify-between mb-4"
            data-oid="r3h5y.v"
          >
            <p
              className="font-label-sm text-label-sm text-on-surface-variant"
              data-oid="rx6rs5g"
            >
              {t("page:dashboard.completed")}
            </p>
            <div
              className="p-2 bg-green-50 rounded-lg text-green-600"
              data-oid="hu7wa92"
            >
              <span className="material-symbols-outlined" data-oid="wpzv.k8">
                check_circle
              </span>
            </div>
          </div>
          <p className="text-3xl font-bold text-on-surface" data-oid="pgamj8-">
            {stats.done}
          </p>
          <p
            className="mt-3 text-sm text-on-surface-variant"
            data-oid="0d5-ha."
          >
            {t("page:dashboard.completedDesc")}
          </p>
        </div>

        <div className="glass-panel p-6 rounded-2xl" data-oid="2ogwy1e">
          <div
            className="flex items-center justify-between mb-4"
            data-oid=".u.ycm2"
          >
            <p
              className="font-label-sm text-label-sm text-on-surface-variant"
              data-oid="ethrsle"
            >
              {t("page:dashboard.processedPages")}
            </p>
            <div
              className="p-2 bg-secondary-container rounded-lg text-secondary"
              data-oid="mi71-vi"
            >
              <span className="material-symbols-outlined" data-oid="1m54d1f">
                description
              </span>
            </div>
          </div>
          <p className="text-3xl font-bold text-on-surface" data-oid=".cd7tzp">
            {stats.totalPages.toLocaleString()}
          </p>
          <p
            className="mt-3 text-sm text-on-surface-variant"
            data-oid="p.fop_t"
          >
            {t("page:dashboard.processedPagesDesc")}
          </p>
        </div>
      </div>

      <div
        className="grid grid-cols-1 lg:grid-cols-3 gap-gutter mb-stack-lg"
        data-oid="-fj_67j"
      >
        {/* Status breakdown */}
        <div
          className="lg:col-span-2 glass-panel rounded-2xl p-6"
          data-oid="wsno84x"
        >
          <h3
            className="font-headline-md text-headline-md text-on-surface mb-6"
            data-oid="qnvnvcx"
          >
            {t("page:dashboard.statusBreakdown")}
          </h3>
          <div
            className="grid grid-cols-2 sm:grid-cols-4 gap-4"
            data-oid="f94uf6g"
          >
            {[
              {
                key: "active",
                label: t("page:dashboard.active"),
                value: stats.active,
              },
              {
                key: "done",
                label: t("page:dashboard.completed"),
                value: stats.done,
              },
              {
                key: "error",
                label: t("page:dashboard.failed"),
                value: stats.error,
              },
              {
                key: "pending",
                label: t("page:dashboard.pending"),
                value: jobs.filter((j) => j.status === "pending").length,
              },
            ].map((item) => (
              <div
                key={item.key}
                className="p-4 bg-surface-container-low rounded-xl border border-outline-variant"
                data-oid="6x1d_y8"
              >
                <p
                  className="text-sm text-on-surface-variant mb-1"
                  data-oid="m1ksr5n"
                >
                  {item.label}
                </p>
                <p
                  className="text-2xl font-bold text-on-surface"
                  data-oid="kz4lzvu"
                >
                  {item.value}
                </p>
              </div>
            ))}
          </div>

          <div className="mt-6 space-y-3" data-oid="5:bcr7b">
            {["done", "active", "error", "pending"].map((key) => {
              const value = key === "active" ? stats.active : stats[key];
              const pct = stats.total
                ? Math.round((value / stats.total) * 100)
                : 0;
              const barColor =
                key === "done"
                  ? "bg-green-500"
                  : key === "error"
                    ? "bg-red-500"
                    : key === "pending"
                      ? "bg-slate-400"
                      : "bg-primary";
              return (
                <div key={key} data-oid="13:u6hl">
                  <div
                    className="flex justify-between text-sm mb-1"
                    data-oid="ov_8nu-"
                  >
                    <span
                      className="text-on-surface-variant"
                      data-oid="zlyc0.t"
                    >
                      {statusLabel(key)}
                    </span>
                    <span
                      className="font-medium text-on-surface"
                      data-oid="fc4ppu2"
                    >
                      {pct}%
                    </span>
                  </div>
                  <div
                    className="w-full bg-outline-variant/30 rounded-full h-2 overflow-hidden"
                    data-oid="4xmymfu"
                  >
                    <div
                      className={`${barColor} h-full rounded-full transition-all duration-1000`}
                      style={{ width: `${pct}%` }}
                      data-oid="f69yf0."
                    ></div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Quick actions */}
        <div className="glass-panel rounded-2xl p-6" data-oid="afo8o6-">
          <h3
            className="font-headline-md text-headline-md text-on-surface mb-6"
            data-oid="68vc8l6"
          >
            {t("page:dashboard.quickActions")}
          </h3>
          <div className="space-y-3" data-oid="3u_z89h">
            <Link
              to="/"
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-primary text-on-primary rounded-xl font-body-md text-body-md font-medium hover:opacity-90 transition-all shadow-sm"
              data-oid="q7hekna"
            >
              <Upload size={18} data-oid="g1k3jie" />
              {t("page:dashboard.uploadNewFiles")}
            </Link>
            <Link
              to="/jobs"
              className="w-full flex items-center justify-between px-4 py-3 bg-surface-container-low rounded-xl border border-outline-variant font-body-md text-body-md text-on-surface hover:bg-surface-container-high transition-colors"
              data-oid="fgnrf.d"
            >
              <span className="flex items-center gap-2" data-oid="vj9eqni">
                <span
                  className="material-symbols-outlined text-on-surface-variant"
                  data-oid="0a2_cnc"
                >
                  list_alt
                </span>
                {t("page:dashboard.viewAllJobs")}
              </span>
              <ArrowRight
                size={16}
                className="text-outline"
                data-oid="9wpmudq"
              />
            </Link>
            <Link
              to="/developer"
              className="w-full flex items-center justify-between px-4 py-3 bg-surface-container-low rounded-xl border border-outline-variant font-body-md text-body-md text-on-surface hover:bg-surface-container-high transition-colors"
              data-oid="u-egl:o"
            >
              <span className="flex items-center gap-2" data-oid="3v7.shv">
                <span
                  className="material-symbols-outlined text-on-surface-variant"
                  data-oid="ooybu9l"
                >
                  code
                </span>
                {t("page:dashboard.developerPortal")}
              </span>
              <ArrowRight
                size={16}
                className="text-outline"
                data-oid="vrjx30i"
              />
            </Link>
            <Link
              to="/payment"
              className="w-full flex items-center justify-between px-4 py-3 bg-surface-container-low rounded-xl border border-outline-variant font-body-md text-body-md text-on-surface hover:bg-surface-container-high transition-colors"
              data-oid="fr1vrk3"
            >
              <span className="flex items-center gap-2" data-oid="_k-va:o">
                <span
                  className="material-symbols-outlined text-on-surface-variant"
                  data-oid="yhidf.0"
                >
                  account_balance_wallet
                </span>
                {t("page:dashboard.buyPoints")}
              </span>
              <ArrowRight
                size={16}
                className="text-outline"
                data-oid="z4qlun:"
              />
            </Link>
          </div>
        </div>
      </div>

      {/* Recent jobs */}
      <div
        className="glass-panel rounded-2xl overflow-hidden"
        data-oid="7iesfhm"
      >
        <div
          className="p-6 border-b border-outline-variant flex justify-between items-center"
          data-oid="33500w5"
        >
          <h3
            className="font-headline-md text-headline-md text-on-surface"
            data-oid="4mv3rxg"
          >
            {t("page:dashboard.recentJobs")}
          </h3>
          <Link
            to="/jobs"
            className="text-primary text-sm font-medium hover:underline flex items-center gap-1"
            data-oid="g70b71m"
          >
            {t("page:dashboard.viewAll")}{" "}
            <ArrowRight size={14} data-oid="gjhx639" />
          </Link>
        </div>
        <div className="overflow-x-auto custom-scrollbar" data-oid="jf.iifc">
          <table className="w-full text-left" data-oid="2z56qbf">
            <thead
              className="bg-surface-container-low/50 text-on-surface-variant font-label-sm text-label-sm uppercase tracking-wider"
              data-oid="gb7rff3"
            >
              <tr data-oid="f3c_0zn">
                <th className="px-gutter py-4" data-oid="03axq0g">
                  {t("page:dashboard.fileName")}
                </th>
                <th className="px-gutter py-4" data-oid="zilsgo.">
                  {t("page:dashboard.status")}
                </th>
                <th className="px-gutter py-4" data-oid="tu3g8jg">
                  {t("page:dashboard.date")}
                </th>
                <th className="px-gutter py-4 text-right" data-oid="i4qe_.j">
                  {t("page:dashboard.action")}
                </th>
              </tr>
            </thead>
            <tbody
              className="divide-y divide-outline-variant/50"
              data-oid="caebo50"
            >
              {loading ? (
                <tr data-oid="4v:di27">
                  <td
                    colSpan={4}
                    className="text-center py-12"
                    data-oid="rvg7gwl"
                  >
                    <Loader2
                      className="animate-spin mx-auto text-primary"
                      size={24}
                      data-oid="-vaz64f"
                    />
                  </td>
                </tr>
              ) : (
                stats.recent.map((j) => {
                  const chipClass =
                    STATUS_COLOR[j.status] || STATUS_COLOR.pending;
                  return (
                    <tr
                      key={j.job_id}
                      className="hover:bg-surface-container/30 transition-colors"
                      data-oid="-4o5u.."
                    >
                      <td
                        className="px-gutter py-4 font-body-md text-body-md text-on-surface"
                        data-oid="vhfxvcf"
                      >
                        {j.filename}
                      </td>
                      <td className="px-gutter py-4" data-oid="wwjpet8">
                        <span
                          className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${chipClass}`}
                          data-oid=".w.jgns"
                        >
                          <span
                            className="material-symbols-outlined text-[14px]"
                            data-oid="z4aaki5"
                          >
                            {j.status === "done"
                              ? "check_circle"
                              : j.status === "error"
                                ? "cancel"
                                : "refresh"}
                          </span>
                          {statusLabel(j.status)}
                        </span>
                      </td>
                      <td
                        className="px-gutter py-4 font-body-md text-body-md text-on-surface-variant"
                        data-oid="bfsp45p"
                      >
                        {formatDate(j.created_at)}
                      </td>
                      <td
                        className="px-gutter py-4 text-right"
                        data-oid="g:.3.ox"
                      >
                        {j.status === "done" ? (
                          <Link
                            to={`/jobs/${j.job_id}`}
                            className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-surface-container-high text-on-surface hover:text-primary hover:bg-surface-container transition-colors"
                            data-oid="z_ibgk0"
                          >
                            <Eye size={14} data-oid="tdhd_4n" />{" "}
                            {t("page:dashboard.view")}
                          </Link>
                        ) : (
                          <span className="text-outline" data-oid="8_4pu0x">
                            -
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
              {!loading && stats.recent.length === 0 && (
                <tr data-oid="cyqwcwm">
                  <td
                    colSpan={4}
                    className="text-center py-12 text-on-surface-variant"
                    data-oid="0n166ng"
                  >
                    <p data-oid="7z6.7zw">{t("page:dashboard.noRecentJobs")}</p>
                    <Link
                      to="/"
                      className="text-primary hover:underline mt-2 inline-flex items-center gap-1"
                      data-oid="q9:p9dr"
                    >
                      <Upload size={14} data-oid="h:85h2m" />{" "}
                      {t("page:dashboard.firstUpload")}
                    </Link>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* API promo */}
      <div
        className="mt-stack-lg grid grid-cols-1 md:grid-cols-3 gap-gutter"
        data-oid=".dvc9-4"
      >
        <div
          className="col-span-1 md:col-span-2 glass-surface p-gutter rounded-2xl border border-primary/10 flex items-start gap-4"
          data-oid="s:je:nl"
        >
          <div
            className="p-3 rounded-xl bg-primary/10 text-primary"
            data-oid="_a1iyi2"
          >
            <span className="material-symbols-outlined" data-oid="aie_adl">
              lightbulb
            </span>
          </div>
          <div data-oid="ncuosps">
            <h4
              className="font-headline-md text-headline-md text-primary mb-2"
              data-oid="br8rync"
            >
              {t("page:dashboard.apiPromoTitle")}
            </h4>
            <p
              className="font-body-md text-body-md text-on-surface-variant max-w-xl"
              data-oid="2t8_ei7"
            >
              {t("page:dashboard.apiPromoDesc")}
            </p>
            <Link
              to="/developer"
              className="mt-4 text-primary font-body-md text-body-md font-bold hover:underline inline-flex items-center gap-1"
              data-oid="0klf7bt"
            >
              {t("page:dashboard.apiPromoLink")}{" "}
              <ArrowRight size={16} data-oid="tkzt1jy" />
            </Link>
          </div>
        </div>
      </div>
    </SidebarLayout>
  );
}
