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
  CreditCard } from
"lucide-react";
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
  merging: "bg-primary-container/10 text-primary border-primary/10"
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
      (j) => j.status !== "done" && j.status !== "error"
    ).length;
    const error = jobs.filter((j) => j.status === "error").length;
    const totalPages = jobs.reduce(
      (sum, j) => sum + (j.total_pages || j.total_files || 0),
      0
    );
    const recent = [...jobs].
    sort((a, b) => new Date(b.created_at) - new Date(a.created_at)).
    slice(0, 5);
    return { total, done, active, error, totalPages, recent };
  }, [jobs]);

  function formatDate(dateStr) {
    if (!dateStr) return "-";
    return new Date(dateStr).toLocaleString(i18n.language, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  if (authLoading || !user && !error) {
    return (
      <div
        className="min-h-screen flex items-center justify-center bg-background"
        data-oid="jkwgbnm">

        <Loader2
          className="animate-spin text-primary"
          size={32}
          data-oid="fs6-n.h" />

      </div>);

  }

  if (!user) {
    return (
      <div
        className="min-h-screen flex items-center justify-center bg-background"
        data-oid="22_6cf8">

        <div className="text-center" data-oid="j86uk-_">
          <p className="mb-4 text-on-surface-variant" data-oid="kd7t84i">
            {t("common:auth.loginRequired")}
          </p>
          <button
            onClick={() => navigate("/login")}
            className="bg-primary text-on-primary px-4 py-2 rounded-lg"
            data-oid="gvf4git">

            {t("page:auth.loginButton")}
          </button>
        </div>
      </div>);

  }

  return (
    <SidebarLayout
      title={t("page:dashboard.title")}
      subtitle={t("page:dashboard.subtitle")}
      data-oid="q7oyxf2">

      {error &&
      <div
        className="bg-red-50 text-red-700 px-4 py-3 rounded-lg mb-6 flex items-center gap-2 border border-red-200"
        data-oid="eoits7u">

          <span className="material-symbols-outlined" data-oid="imghsa2">
            error
          </span>
          {error}
        </div>
      }

      {/* Summary cards */}
      <div
        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-gutter mb-stack-lg"
        data-oid=".1eyng_">

        <div className="glass-panel p-6 rounded-2xl" data-oid="z-_7iz1">
          <div
            className="flex items-center justify-between mb-4"
            data-oid="mth2x:f">

            <p
              className="font-label-sm text-label-sm text-on-surface-variant"
              data-oid=":36qpea">

              {t("page:dashboard.points")}
            </p>
            <div
              className="p-2 bg-yellow-50 rounded-lg text-yellow-600"
              data-oid="td4gz52">

              <Coins size={20} data-oid="nw4dfqx" />
            </div>
          </div>
          <p className="text-3xl font-bold text-on-surface" data-oid="7z.7l1t">
            {profile?.points_balance?.toLocaleString() ?? "-"} P
          </p>
          <Link
            to="/payment"
            className="mt-3 inline-flex items-center gap-1 text-primary text-sm font-medium hover:underline"
            data-oid="_78h3f4">

            <CreditCard size={14} data-oid="9yjdx0:" />{" "}
            {t("page:dashboard.recharge")}
          </Link>
        </div>

        <div className="glass-panel p-6 rounded-2xl" data-oid="558tma_">
          <div
            className="flex items-center justify-between mb-4"
            data-oid="u3625no">

            <p
              className="font-label-sm text-label-sm text-on-surface-variant"
              data-oid="rxejzgn">

              {t("page:dashboard.totalJobs")}
            </p>
            <div
              className="p-2 bg-primary/10 rounded-lg text-primary"
              data-oid="jnr02oy">

              <span className="material-symbols-outlined" data-oid="4933-03">
                task
              </span>
            </div>
          </div>
          <p className="text-3xl font-bold text-on-surface" data-oid="9wrj87.">
            {stats.total}
          </p>
          <p
            className="mt-3 text-sm text-on-surface-variant"
            data-oid="m00ptn9">

            {t("page:dashboard.totalJobsDesc")}
          </p>
        </div>

        <div className="glass-panel p-6 rounded-2xl" data-oid="a4xqfjk">
          <div
            className="flex items-center justify-between mb-4"
            data-oid="pqm83nu">

            <p
              className="font-label-sm text-label-sm text-on-surface-variant"
              data-oid="64:-3ac">

              {t("page:dashboard.completed")}
            </p>
            <div
              className="p-2 bg-green-50 rounded-lg text-green-600"
              data-oid="8jc6pct">

              <span className="material-symbols-outlined" data-oid="ml.owjv">
                check_circle
              </span>
            </div>
          </div>
          <p className="text-3xl font-bold text-on-surface" data-oid="_bzhgif">
            {stats.done}
          </p>
          <p
            className="mt-3 text-sm text-on-surface-variant"
            data-oid="bdc8cw0">

            {t("page:dashboard.completedDesc")}
          </p>
        </div>

        <div className="glass-panel p-6 rounded-2xl" data-oid=":v62upd">
          <div
            className="flex items-center justify-between mb-4"
            data-oid="816rxv8">

            <p
              className="font-label-sm text-label-sm text-on-surface-variant"
              data-oid="sfgm3nz">

              {t("page:dashboard.processedPages")}
            </p>
            <div
              className="p-2 bg-secondary-container rounded-lg text-secondary"
              data-oid="lv_w5tn">

              <span className="material-symbols-outlined" data-oid="7g30z_c">
                description
              </span>
            </div>
          </div>
          <p className="text-3xl font-bold text-on-surface" data-oid="g-z6w37">
            {stats.totalPages.toLocaleString()}
          </p>
          <p
            className="mt-3 text-sm text-on-surface-variant"
            data-oid="-w.zt96">

            {t("page:dashboard.processedPagesDesc")}
          </p>
        </div>
      </div>

      <div
        className="grid grid-cols-1 lg:grid-cols-3 gap-gutter mb-stack-lg"
        data-oid="luldwv5">

        {/* Status breakdown */}
        <div
          className="lg:col-span-2 glass-panel rounded-2xl p-6"
          data-oid="hsm2j.7">

          <h3
            className="font-headline-md text-headline-md text-on-surface mb-6"
            data-oid="0jwplmc">

            {t("page:dashboard.statusBreakdown")}
          </h3>
          <div
            className="grid grid-cols-2 sm:grid-cols-4 gap-4"
            data-oid="1o:yeua">

            {[
            {
              key: "active",
              label: t("page:dashboard.active"),
              value: stats.active
            },
            {
              key: "done",
              label: t("page:dashboard.completed"),
              value: stats.done
            },
            {
              key: "error",
              label: t("page:dashboard.failed"),
              value: stats.error
            },
            {
              key: "pending",
              label: t("page:dashboard.pending"),
              value: jobs.filter((j) => j.status === "pending").length
            }].
            map((item) =>
            <div
              key={item.key}
              className="p-4 bg-surface-container-low rounded-xl border border-outline-variant"
              data-oid="1e4:e7w">

                <p
                className="text-sm text-on-surface-variant mb-1"
                data-oid="9.ymmfi">

                  {item.label}
                </p>
                <p
                className="text-2xl font-bold text-on-surface"
                data-oid="umk.frb">

                  {item.value}
                </p>
              </div>
            )}
          </div>

          <div className="mt-6 space-y-3" data-oid="a5uk1fx">
            {["done", "active", "error", "pending"].map((key) => {
              const value = key === "active" ? stats.active : stats[key];
              const pct = stats.total ?
              Math.round(value / stats.total * 100) :
              0;
              const barColor =
              key === "done" ?
              "bg-green-500" :
              key === "error" ?
              "bg-red-500" :
              key === "pending" ?
              "bg-slate-400" :
              "bg-primary";
              return (
                <div key={key} data-oid="f0j_195">
                  <div
                    className="flex justify-between text-sm mb-1"
                    data-oid="zbeefzz">

                    <span
                      className="text-on-surface-variant"
                      data-oid="0_tidk3">

                      {statusLabel(key)}
                    </span>
                    <span
                      className="font-medium text-on-surface"
                      data-oid="pf:l:-9">

                      {pct}%
                    </span>
                  </div>
                  <div
                    className="w-full bg-outline-variant/30 rounded-full h-2 overflow-hidden"
                    data-oid="45z4y9h">

                    <div
                      className={`${barColor} h-full rounded-full transition-all duration-1000`}
                      style={{ width: `${pct}%` }}
                      data-oid="dobfp-b">
                    </div>
                  </div>
                </div>);

            })}
          </div>
        </div>

        {/* Quick actions */}
        <div className="glass-panel rounded-2xl p-6" data-oid="4c.996x">
          <h3
            className="font-headline-md text-headline-md text-on-surface mb-6"
            data-oid="4cz7khh">

            {t("page:dashboard.quickActions")}
          </h3>
          <div className="space-y-3" data-oid="4p9ioq8">
            <Link
              to="/"
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-primary text-on-primary rounded-xl font-body-md text-body-md font-medium hover:opacity-90 transition-all shadow-sm"
              data-oid="j_yb4kw">

              <Upload size={18} data-oid="ydxzf-b" />
              {t("page:dashboard.uploadNewFiles")}
            </Link>
            <Link
              to="/jobs"
              className="w-full flex items-center justify-between px-4 py-3 bg-surface-container-low rounded-xl border border-outline-variant font-body-md text-body-md text-on-surface hover:bg-surface-container-high transition-colors"
              data-oid="--6g4o5">

              <span className="flex items-center gap-2" data-oid="un597ao">
                <span
                  className="material-symbols-outlined text-on-surface-variant"
                  data-oid="3_vh432">

                  list_alt
                </span>
                {t("page:dashboard.viewAllJobs")}
              </span>
              <ArrowRight
                size={16}
                className="text-outline"
                data-oid="facz0zi" />

            </Link>
            <Link
              to="/developer"
              className="w-full flex items-center justify-between px-4 py-3 bg-surface-container-low rounded-xl border border-outline-variant font-body-md text-body-md text-on-surface hover:bg-surface-container-high transition-colors"
              data-oid="d_91vcu">

              <span className="flex items-center gap-2" data-oid="z8k-tki">
                <span
                  className="material-symbols-outlined text-on-surface-variant"
                  data-oid="rw5qg6j">

                  code
                </span>
                {t("page:dashboard.developerPortal")}
              </span>
              <ArrowRight
                size={16}
                className="text-outline"
                data-oid="pbq5u3h" />

            </Link>
            <Link
              to="/payment"
              className="w-full flex items-center justify-between px-4 py-3 bg-surface-container-low rounded-xl border border-outline-variant font-body-md text-body-md text-on-surface hover:bg-surface-container-high transition-colors"
              data-oid="13m2fg4">

              <span className="flex items-center gap-2" data-oid="15bl4l4">
                <span
                  className="material-symbols-outlined text-on-surface-variant"
                  data-oid="l2esr65">

                  account_balance_wallet
                </span>
                {t("page:dashboard.buyPoints")}
              </span>
              <ArrowRight
                size={16}
                className="text-outline"
                data-oid="-3mgrxh" />

            </Link>
          </div>
        </div>
      </div>

      {/* Recent jobs */}
      <div
        className="glass-panel rounded-2xl overflow-hidden"
        data-oid="p9ir-29">

        <div
          className="p-6 border-b border-outline-variant flex justify-between items-center"
          data-oid="9_2:c3z">

          <h3
            className="font-headline-md text-headline-md text-on-surface"
            data-oid="s86.2:h">

            {t("page:dashboard.recentJobs")}
          </h3>
          <Link
            to="/jobs"
            className="text-primary text-sm font-medium hover:underline flex items-center gap-1"
            data-oid="k7kj3d5">

            {t("page:dashboard.viewAll")}{" "}
            <ArrowRight size={14} data-oid="rqwj.5b" />
          </Link>
        </div>
        <div className="overflow-x-auto custom-scrollbar" data-oid="402.8po">
          <table className="w-full text-left" data-oid="8tfz9r_">
            <thead
              className="bg-surface-container-low/50 text-on-surface-variant font-label-sm text-label-sm uppercase tracking-wider"
              data-oid="2286wug">

              <tr data-oid="-zp:zq5">
                <th className="px-gutter py-4" data-oid="or2wf3k">
                  {t("page:dashboard.fileName")}
                </th>
                <th className="px-gutter py-4" data-oid="c_awav2">
                  {t("page:dashboard.status")}
                </th>
                <th className="px-gutter py-4" data-oid="di9rk5-">
                  {t("page:dashboard.date")}
                </th>
                <th className="px-gutter py-4 text-right" data-oid=".f-9hez">
                  {t("page:dashboard.action")}
                </th>
              </tr>
            </thead>
            <tbody
              className="divide-y divide-outline-variant/50"
              data-oid="n0qfhro">

              {loading ?
              <tr data-oid="a_lru:a">
                  <td
                  colSpan={4}
                  className="text-center py-12"
                  data-oid="plwfugn">

                    <Loader2
                    className="animate-spin mx-auto text-primary"
                    size={24}
                    data-oid="01c.i6q" />

                  </td>
                </tr> :

              stats.recent.map((j) => {
                const chipClass =
                STATUS_COLOR[j.status] || STATUS_COLOR.pending;
                return (
                  <tr
                    key={j.job_id}
                    className="hover:bg-surface-container/30 transition-colors"
                    data-oid="e8jdxr2">

                      <td
                      className="px-gutter py-4 font-body-md text-body-md text-on-surface"
                      data-oid="bhnot4h">

                        {j.filename}
                      </td>
                      <td className="px-gutter py-4" data-oid="y8k-mq8">
                        <span
                        className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border ${chipClass}`}
                        data-oid="t5vsd:h">

                          <span
                          className="material-symbols-outlined text-[14px]"
                          data-oid="gv14c6a">

                            {j.status === "done" ?
                          "check_circle" :
                          j.status === "error" ?
                          "cancel" :
                          "refresh"}
                          </span>
                          {statusLabel(j.status)}
                        </span>
                      </td>
                      <td
                      className="px-gutter py-4 font-body-md text-body-md text-on-surface-variant"
                      data-oid="_h1pdou">

                        {formatDate(j.created_at)}
                      </td>
                      <td
                      className="px-gutter py-4 text-right"
                      data-oid="zrlsvdt">

                        {j.status === "done" ?
                      <Link
                        to={`/jobs/${j.job_id}`}
                        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-surface-container-high text-on-surface hover:text-primary hover:bg-surface-container transition-colors"
                        data-oid="0_-8xlo">

                            <Eye size={14} data-oid="pmv1x1b" />{" "}
                            {t("page:dashboard.view")}
                          </Link> :

                      <span className="text-outline" data-oid="ve7mz50">
                            -
                          </span>
                      }
                      </td>
                    </tr>);

              })
              }
              {!loading && stats.recent.length === 0 &&
              <tr data-oid="0er3t:0">
                  <td
                  colSpan={4}
                  className="text-center py-12 text-on-surface-variant"
                  data-oid="iz7y_nb">

                    <p data-oid="bitpnko">{t("page:dashboard.noRecentJobs")}</p>
                    <Link
                    to="/"
                    className="text-primary hover:underline mt-2 inline-flex items-center gap-1"
                    data-oid="c6d-de5">

                      <Upload size={14} data-oid="mur8vko" />{" "}
                      {t("page:dashboard.firstUpload")}
                    </Link>
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      </div>

      {/* API promo */}
      <div
        className="mt-stack-lg grid grid-cols-1 md:grid-cols-3 gap-gutter"
        data-oid="u1p66au">

        <div
          className="col-span-1 md:col-span-2 glass-surface p-gutter rounded-2xl border border-primary/10 flex items-start gap-4"
          data-oid="jaaioij">

          <div
            className="p-3 rounded-xl bg-primary/10 text-primary"
            data-oid="9_fqive">

            <span className="material-symbols-outlined" data-oid="8o83_tt">
              lightbulb
            </span>
          </div>
          <div data-oid="sexcq-f">
            <h4
              className="font-headline-md text-headline-md text-primary mb-2"
              data-oid="q8eg::7">

              {t("page:dashboard.apiPromoTitle")}
            </h4>
            <p
              className="font-body-md text-body-md text-on-surface-variant max-w-xl"
              data-oid="qgah-oz">

              {t("page:dashboard.apiPromoDesc")}
            </p>
            <Link
              to="/developer"
              className="mt-4 text-primary font-body-md text-body-md font-bold hover:underline inline-flex items-center gap-1"
              data-oid="zyczgtb">

              {t("page:dashboard.apiPromoLink")}{" "}
              <ArrowRight size={16} data-oid="a-9pfv9" />
            </Link>
          </div>
        </div>
      </div>
    </SidebarLayout>);

}