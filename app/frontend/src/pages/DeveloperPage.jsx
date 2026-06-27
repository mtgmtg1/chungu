// [Flow: Step 1 (로그인/개발자 권한 확인) -> Step 2 (계정/키/사용량 데이터 로드) -> Step 3 (키 발급/삭제/복사 UI) -> Step 4 (사용량 차트 + Docs 렌더링)]
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../api.js";
import { useAuth } from "../AuthContext.jsx";
import i18n from "../i18n.js";
import SidebarLayout from "../components/SidebarLayout.jsx";

const baseUrl = typeof window !== "undefined" ? window.location.origin : "";

const curlExample = `curl -X POST ${baseUrl}/api/v1/jobs/upload \\
  -H "X-API-Key: <YOUR_API_KEY>" \\
  -F "files=@document.pdf" \\
  -F "pipeline=vision"`;

export default function DeveloperPage() {
  const { user, loading } = useAuth();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [account, setAccount] = useState(null);
  const [keys, setKeys] = useState([]);
  const [pricing, setPricing] = useState(null);
  const [usage, setUsage] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [revealedKey, setRevealedKey] = useState(null);
  const [error, setError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [period, setPeriod] = useState("7");

  useEffect(() => {
    if (loading) return;
    if (!user) {
      navigate("/login");
      return;
    }
    loadAll();
  }, [user, loading, navigate]);

  useEffect(() => {
    if (!user) return;
    loadUsage();
  }, [user, period]);

  const loadKeys = async () => {
    try {
      const k = await api.listApiKeys();
      setKeys(k);
    } catch (e) {
      console.error("API keys 로드 실패:", e);
      setError((prev) => prev || e.message || t("page:errors.loadFailed"));
    }
  };

  const loadUsage = async () => {
    try {
      const usg = await api.devUsage(parseInt(period, 10));
      setUsage(usg);
    } catch (e) {
      console.error("Usage 로드 실패:", e);
    }
  };

  const loadAll = async () => {
    try {
      setError("");
      const [acc, prc, tx] = await Promise.all([
      api.devAccount(),
      api.devPricing(),
      api.devTransactions(20)]
      );
      setAccount(acc);
      setPricing(prc);
      setTransactions(tx);
    } catch (e) {
      setError(e.message || t("page:errors.loadFailed"));
    }
    await loadKeys();
  };

  const createKey = async () => {
    try {
      setError("");
      const res = await api.createApiKey({ name: newKeyName || "default" });
      setKeys([res, ...keys]);
      setRevealedKey(res);
      setNewKeyName("");
      setShowCreate(false);
      await loadKeys();
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    }
  };

  const deleteKey = async (id) => {
    if (!confirm(t("page:developer.deleteConfirm", "Delete this API key?")))
    return;
    try {
      await api.deleteApiKey(id);
      setKeys(keys.filter((k) => k.id !== id));
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    }
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
  };

  const maxPoints = Math.max(1, ...usage.map((u) => u.points_spent || 0));
  const totalUsage = account?.today_usage?.points_spent || 0;
  const balance = account?.points_balance || 0;
  const limit = 12500;
  const usagePct = Math.min(100, Math.round(totalUsage / limit * 100));

  if (loading || !user) {
    return (
      <div
        className="min-h-screen bg-background flex items-center justify-center"
        data-oid="e4pvewk">

        <div
          className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"
          data-oid="ktavr95">
        </div>
      </div>);

  }

  return (
    <SidebarLayout
      title={t("page:developer.title")}
      subtitle={t("page:developer.subtitle")}
      data-oid="1k5vo7v">

      {/* {error && (
             <div
               className="bg-error-container text-error px-4 py-3 rounded-xl text-sm border border-error/10 mb-8"
               data-oid="3vz:8cn"
             >
               {error}
             </div>
            )} */}

      <div
        className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8"
        data-oid="vq1rj-h">

        <div data-oid="nn3cv5x"></div>
        <button
          onClick={() => setShowCreate(true)}
          className="bg-primary text-white px-6 py-2.5 rounded-lg flex items-center gap-2 font-body-md hover:bg-primary/90 transition-all shadow-sm"
          data-oid="prjwg2j">

          <span
            className="material-symbols-outlined text-xl"
            data-oid="0iv3ato">

            add
          </span>
          {t("page:developer.createKey")}
        </button>
      </div>

      <div
        className="grid grid-cols-1 lg:grid-cols-12 gap-gutter"
        data-oid="ge.yf.c">

        <div className="lg:col-span-8 space-y-gutter" data-oid="h4n16u:">
          <div className="glass-panel p-6 rounded-2xl" data-oid="68mob7w">
            <div
              className="flex justify-between items-center mb-6"
              data-oid="bqgzc_e">

              <h3
                className="font-headline-md text-headline-md text-on-surface"
                data-oid="2tm23tk">

                {t("page:developer.usageAnalytics")}
              </h3>
              <select
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                className="bg-surface-container-low border-none rounded-lg text-label-sm py-1 pl-2 pr-8 focus:ring-1 focus:ring-primary focus:outline-none"
                data-oid="0ep--og">

                <option value="7" data-oid="6se7ua1">
                  {t("page:developer.last7Days")}
                </option>
                <option value="30" data-oid="bp2i97:">
                  {t("page:developer.last30Days")}
                </option>
              </select>
            </div>
            <div
              className="h-64 flex items-end gap-1 px-2 relative"
              data-oid="v8buroa">

              <div
                className="absolute inset-0 flex items-center justify-center opacity-10 pointer-events-none"
                data-oid="xr3cblz">

                <span
                  className="material-symbols-outlined text-9xl"
                  data-oid="2nzkvtl">

                  monitoring
                </span>
              </div>
              {usage.map((u, i) => {
                const pct = Math.round(
                  (u.points_spent || 0) / maxPoints * 100
                );
                return (
                  <div
                    key={u.day || i}
                    className="flex-1 flex flex-col justify-end items-center group h-full"
                    data-oid="_e0ktgi">

                    <div
                      className="w-full bg-primary/20 rounded-t hover:bg-primary/40 transition-all cursor-pointer relative"
                      style={{ height: `${Math.max(4, pct)}%` }}
                      data-oid="eufc_u6">

                      <div
                        className="hidden group-hover:block absolute -top-8 left-1/2 -translate-x-1/2 bg-on-surface text-white text-[10px] py-1 px-2 rounded whitespace-nowrap"
                        data-oid=":noh_e.">

                        {(u.points_spent || 0).toLocaleString()}
                        {t("common:points.point")}
                      </div>
                    </div>
                    <span
                      className="text-[10px] text-outline mt-2"
                      data-oid="e:9x_b-">

                      {u.day ?
                      new Date(u.day).toLocaleDateString(i18n.language, {
                        weekday: "short"
                      }) :
                      "-"}
                    </span>
                  </div>);

              })}
              {usage.length === 0 &&
              <div
                className="absolute inset-0 flex items-center justify-center text-outline text-sm"
                data-oid="uycb-xi">

                  {t("page:developer.noUsage")}
                </div>
              }
            </div>
          </div>

          <div
            className="glass-panel rounded-2xl overflow-hidden"
            data-oid="lix3r_-">

            <div
              className="p-6 border-b border-outline-variant flex justify-between items-center"
              data-oid="mfkii_2">

              <h3
                className="font-headline-md text-headline-md text-on-surface"
                data-oid="ymlrq51">

                {t("page:developer.apiKeys")}
              </h3>
            </div>
            <div className="overflow-x-auto" data-oid="kkfejw8">
              <table className="w-full text-left" data-oid="sp:7h.:">
                <thead
                  className="bg-surface-container-low text-on-surface-variant font-label-sm text-label-sm uppercase tracking-wider"
                  data-oid="21jag4-">

                  <tr data-oid="0hrby0.">
                    <th className="px-6 py-4" data-oid="j5n1_4c">
                      {t("page:developer.apiKey")}
                    </th>
                    <th className="px-6 py-4" data-oid="g9-ozal">
                      {t("page:developer.apiKey")}
                    </th>
                    <th className="px-6 py-4 text-right" data-oid="cuf.wcl">
                      {t("page:developer.rate")}
                    </th>
                    <th className="px-6 py-4 text-right" data-oid="a1frpxt">
                      {t("page:developer.created")}
                    </th>
                    <th className="px-6 py-4 w-10" data-oid="yj4ikdq"></th>
                  </tr>
                </thead>
                <tbody
                  className="divide-y divide-outline-variant text-body-md"
                  data-oid="dk1-96s">

                  {keys.map((k) =>
                  <tr
                    key={k.id}
                    className="hover:bg-primary-container/5 transition-colors"
                    data-oid="e6cr-bn">

                      <td
                      className="px-6 py-4 font-medium text-on-surface"
                      data-oid="u1hmiij">

                        {k.name}
                      </td>
                      <td className="px-6 py-4" data-oid="_5v1w3.">
                        <div
                        className="flex items-center gap-2"
                        data-oid="vaz:iuo">

                          <code
                          className="bg-surface-container-high px-2 py-1 rounded text-primary-container font-mono text-sm"
                          data-oid="lcap4qu">

                            {k.prefix}••••••••••••••••
                          </code>
                          <button
                          onClick={() =>
                          copyToClipboard(k.prefix + "••••••••••••••••")
                          }
                          className="text-outline hover:text-primary transition-colors"
                          title={t("page:developer.copy")}
                          data-oid="7hkfp1m">

                            <span
                            className="material-symbols-outlined text-lg"
                            data-oid="q0ifnej">

                              content_copy
                            </span>
                          </button>
                        </div>
                      </td>
                      <td
                      className="px-6 py-4 text-right text-on-surface-variant"
                      data-oid="d-4jscm">

                        {k.rate_limit_rpm}/min
                      </td>
                      <td
                      className="px-6 py-4 text-right text-on-surface-variant"
                      data-oid="duu4j-j">

                        {k.created_at ?
                      new Date(k.created_at).toLocaleDateString(
                        i18n.language
                      ) :
                      "-"}
                      </td>
                      <td className="px-6 py-4" data-oid="nr-luq-">
                        <button
                        onClick={() => deleteKey(k.id)}
                        className="text-outline hover:text-error transition-colors"
                        title={t("page:developer.delete")}
                        data-oid="pxqfm3u">

                          <span
                          className="material-symbols-outlined text-lg"
                          data-oid="fxrsx1s">

                            delete
                          </span>
                        </button>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="lg:col-span-4 space-y-gutter" data-oid="jfp8v_w">
          <div className="glass-panel p-6 rounded-2xl" data-oid="wqku5pr">
            <div className="flex items-center gap-3 mb-6" data-oid="y-vdrg2">
              <span
                className="material-symbols-outlined text-primary bg-primary/10 p-2 rounded-lg"
                data-oid="gfakadq">

                speed
              </span>
              <h3
                className="font-headline-md text-headline-md text-on-surface"
                data-oid="866zi6g">

                {t("page:developer.rateLimit")}
              </h3>
            </div>
            <div className="space-y-4" data-oid="8yf5k01">
              <div
                className="flex justify-between items-end"
                data-oid="jo15-rb">

                <div data-oid="luljc4k">
                  <p
                    className="text-3xl font-bold text-on-surface"
                    data-oid="egk73d3">

                    {totalUsage.toLocaleString()}
                  </p>
                  <p
                    className="text-on-surface-variant text-label-sm"
                    data-oid="silsajk">

                    {t("page:developer.monthlyCalls")}
                  </p>
                </div>
                <p className="text-outline text-label-sm" data-oid="-sj1mzv">
                  {t("page:developer.limit", { limit: limit.toLocaleString() })}
                </p>
              </div>
              <div
                className="w-full bg-outline-variant/30 rounded-full h-3 overflow-hidden"
                data-oid="f-i9i38">

                <div
                  className="bg-primary h-full rounded-full transition-all duration-1000 ease-out"
                  style={{ width: `${usagePct}%` }}
                  data-oid="7zo3apt">
                </div>
              </div>
              <div
                className="p-3 bg-secondary-container/30 border border-secondary/10 rounded-lg flex items-start gap-2"
                data-oid="q03i9q2">

                <span
                  className="material-symbols-outlined text-secondary text-sm mt-0.5"
                  data-oid="41h3r4l">

                  info
                </span>
                <p
                  className="text-[12px] text-on-secondary-fixed-variant leading-relaxed"
                  data-oid="312i9x1">

                  {t("page:developer.usageResets", {
                    points: balance.toLocaleString()
                  })}
                </p>
              </div>
            </div>
          </div>

          <div
            className="glass-panel rounded-2xl overflow-hidden"
            data-oid="f20d6xz">

            <div
              className="p-6 border-b border-outline-variant"
              data-oid="flupcy-">

              <h3
                className="font-headline-md text-headline-md text-on-surface"
                data-oid="a7.6xkf">

                {t("page:developer.quickStart")}
              </h3>
            </div>
            <div className="p-6 space-y-6" data-oid="wut-6z4">
              <div className="space-y-3" data-oid="bglbo4u">
                <div
                  className="flex justify-between items-center"
                  data-oid="ci84dpk">

                  <span
                    className="text-label-sm font-bold text-outline"
                    data-oid="gvc.ngd">

                    {t("page:developer.endpoint")}
                  </span>
                  <span
                    className="text-label-sm px-2 py-0.5 bg-primary-container text-white rounded uppercase"
                    data-oid="lt8kjpt">

                    POST
                  </span>
                </div>
                <code
                  className="block bg-surface-container-low p-2 rounded font-mono text-sm text-primary"
                  data-oid="67c2e4i">

                  /api/v1/jobs/upload
                </code>
              </div>
              <div className="space-y-4" data-oid="0afgemz">
                <div
                  className="flex border-b border-outline-variant"
                  data-oid="xkpcqi6">

                  <button
                    className="px-4 py-2 text-primary border-b-2 border-primary font-label-sm"
                    data-oid="5bttp04">

                    {t("page:developer.curl")}
                  </button>
                </div>
                <div
                  className="code-block p-4 rounded-xl text-sm overflow-x-auto"
                  data-oid="w89wd.r">

                  <pre data-oid="07e49al">
                    <code data-oid="pixo_zv">{curlExample}</code>
                  </pre>
                </div>
              </div>
              <a
                href={`${baseUrl}/docs`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-primary font-body-md hover:underline"
                data-oid="78b0gtx">

                {t("page:developer.viewFullReference")}
                <span
                  className="material-symbols-outlined text-sm"
                  data-oid="remy85l">

                  arrow_forward
                </span>
              </a>
            </div>
          </div>

          <div className="glass-panel p-6 rounded-2xl" data-oid="arqu6p5">
            <div className="flex items-center gap-3 mb-4" data-oid="gi64:0u">
              <span
                className="material-symbols-outlined text-primary bg-primary/10 p-2 rounded-lg"
                data-oid="v7md:01">

                payments
              </span>
              <h3
                className="font-headline-md text-headline-md text-on-surface"
                data-oid="iwckwjq">

                {t("page:developer.billing")}
              </h3>
            </div>
            <div className="space-y-3" data-oid="cwy.9vw">
              <div
                className="flex justify-between text-body-md"
                data-oid="bmkatem">

                <span className="text-on-surface-variant" data-oid="otbezkk">
                  {t("page:developer.pointsBalance")}
                </span>
                <span className="font-bold text-on-surface" data-oid="__.s234">
                  {balance.toLocaleString()}
                  {t("common:points.point")}
                </span>
              </div>
              <div
                className="flex justify-between text-body-md"
                data-oid="37:nn5z">

                <span className="text-on-surface-variant" data-oid="6avhjyq">
                  {t("page:developer.todayUsage")}
                </span>
                <span className="font-bold text-on-surface" data-oid="s.0pti0">
                  {account?.today_usage?.points_spent?.toLocaleString() || 0}
                  {t("common:points.point")}
                </span>
              </div>
              <div
                className="h-px bg-outline-variant/40 my-2"
                data-oid="8mwn1ez">
              </div>
              <div
                className="space-y-1 text-[12px] text-on-surface-variant"
                data-oid="zmrytu6">

                <p data-oid="twwx4ud">
                  {t("page:developer.pdfPage")}:{" "}
                  {pricing?.rates?.krw_per_page || "-"}
                  {t("common:points.point")}
                </p>
                <p data-oid="ycq0fx:">
                  {t("page:developer.image")}:{" "}
                  {pricing?.rates?.krw_per_image || "-"}
                  {t("common:points.point")}
                </p>
                <p data-oid="o67_hi_">
                  {t("page:developer.audioSec")}:{" "}
                  {pricing?.rates?.krw_per_audio_second || "-"}
                  {t("common:points.point")}
                </p>
                <p data-oid="cx395in">
                  {t("page:developer.videoSec")}:{" "}
                  {pricing?.rates?.krw_per_video_second || "-"}
                  {t("common:points.point")}
                </p>
              </div>
              <button
                onClick={() => navigate("/payment")}
                className="w-full mt-2 bg-primary text-white rounded-lg py-2.5 font-body-md hover:bg-primary/90 transition-colors"
                data-oid="my9rrld">

                {t("page:developer.recharge")}
              </button>
            </div>
          </div>
        </div>
      </div>

      {showCreate &&
      <div
        className="fixed inset-0 z-[60] bg-on-surface/30 backdrop-blur-sm flex items-center justify-center p-4"
        data-oid="c369u1-">

          <div
          className="bg-white rounded-2xl border border-outline-variant shadow-2xl w-full max-w-md p-6"
          data-oid="62jx-_e">

            <h3
            className="font-headline-md text-headline-md text-on-surface mb-4"
            data-oid="-lmh8vy">

              {t("page:developer.createKeyTitle")}
            </h3>
            <input
            type="text"
            placeholder={t("page:developer.keyNamePlaceholder")}
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            className="w-full border border-outline-variant rounded-lg px-3 py-2.5 text-body-md mb-4 focus:ring-1 focus:ring-primary focus:outline-none"
            data-oid="fx8_aw9" />


            {revealedKey &&
          <div
            className="mb-4 rounded-lg border border-amber-300 bg-amber-50 p-3"
            data-oid=":anexyj">

                <p
              className="text-xs font-semibold text-amber-800 mb-2"
              data-oid="o00yjob">

                  {t("page:developer.saveKeyWarning")}
                </p>
                <pre
              className="rounded bg-white p-2 text-xs break-all text-on-surface"
              data-oid="v67:65v">

                  {revealedKey.key}
                </pre>
                <div className="flex gap-2 mt-2" data-oid="rmrf-ze">
                  <button
                onClick={() => copyToClipboard(revealedKey.key)}
                className="rounded bg-amber-700 px-3 py-1 text-xs text-white hover:bg-amber-800"
                data-oid="ybcdbo5">

                    {t("page:developer.copy")}
                  </button>
                  <button
                onClick={() => setRevealedKey(null)}
                className="rounded bg-slate-200 px-3 py-1 text-xs text-slate-700 hover:bg-slate-300"
                data-oid="jabxst7">

                    {t("page:developer.cancel")}
                  </button>
                </div>
              </div>
          }
            <div className="flex gap-3" data-oid="nz93j._">
              <button
              onClick={() => setShowCreate(false)}
              className="flex-1 border border-outline-variant rounded-lg py-2.5 font-body-md text-on-surface hover:bg-surface-container transition-colors"
              data-oid="dm4hr56">

                {t("page:developer.cancel")}
              </button>
              <button
              onClick={createKey}
              className="flex-1 bg-primary text-white rounded-lg py-2.5 font-body-md hover:bg-primary/90 transition-colors"
              data-oid="nn.6bpt">

                {t("page:developer.create")}
              </button>
            </div>
          </div>
        </div>
      }
    </SidebarLayout>);

}