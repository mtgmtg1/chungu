// [Flow: Step 1 (인증 확인) -> Step 2 (계정/키/결제 데이터 로드) -> Step 3 (탭별 UI 렌더링) -> Step 4 (API key 관리 및 비밀번호 변경)]
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../api.js";
import { useAuth } from "../AuthContext.jsx";
import { supabase } from "../supabase.js";
import i18n from "../i18n.js";
import SidebarLayout from "../components/SidebarLayout.jsx";
import { Skeleton, SkeletonTable, SkeletonCard } from "../components/Skeleton.jsx";
import { AnimatedRow } from "../components/AnimatedList.jsx";

export default function SettingsPage() {
  const { user, loading, signOut } = useAuth();
  const { t } = useTranslation();
  const navigate = useNavigate();

  const tabs = [
  { id: "api", label: t("page:settings.apiKeys"), icon: "key" },
  { id: "billing", label: t("page:settings.billing"), icon: "payments" },
  { id: "rate", label: t("page:settings.rateLimit"), icon: "speed" },
  { id: "account", label: t("page:settings.account"), icon: "person" }];


  const [activeTab, setActiveTab] = useState("api");
  const [account, setAccount] = useState(null);
  const [keys, setKeys] = useState([]);
  const [payments, setPayments] = useState([]);
  const [packages, setPackages] = useState([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [revealedKey, setRevealedKey] = useState(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [dataLoading, setDataLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [pwForm, setPwForm] = useState({ current: "", new: "", confirm: "" });
  const [pwLoading, setPwLoading] = useState(false);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      navigate("/login");
      return;
    }
    loadAll();
  }, [user, loading, navigate]);

  const loadAll = async () => {
    setDataLoading(true);
    try {
      setError("");
      const [acc, k, p, pkg] = await Promise.all([
      api.me(),
      api.listApiKeys(),
      api.paymentHistory(),
      api.getPackages()]
      );
      setAccount(acc);
      setKeys(k);
      setPayments(p);
      setPackages(pkg?.packages || pkg || []);
    } catch (e) {
      setError(e.message || t("page:errors.loadFailed"));
    }
    setDataLoading(false);
  };

  const createKey = async () => {
    if (!newKeyName.trim()) return;
    try {
      setError("");
      const res = await api.createApiKey({ name: newKeyName.trim() });
      setKeys([res, ...keys]);
      setRevealedKey(res);
      setNewKeyName("");
      setShowCreate(false);
      await loadAll();
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    }
  };

  const deleteKey = async (id) => {
    if (!confirm(t("page:settings.deleteConfirm", "Delete this API key?")))
    return;
    try {
      await api.deleteApiKey(id);
      setKeys(keys.filter((k) => k.id !== id));
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    }
  };

  const rotateKey = async (id) => {
    if (!confirm(t("page:settings.rotateConfirm", "Rotate this API key?")))
    return;
    try {
      const res = await api.rotateApiKey(id);
      setKeys(keys.map((k) => k.id === id ? { ...k, is_active: false } : k));
      setRevealedKey(res);
      await loadAll();
    } catch (e) {
      setError(e.message || t("page:errors.unknown"));
    }
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    setMsg(t("page:settings.copied"));
    setTimeout(() => setMsg(""), 2000);
  };

  const changePassword = async (e) => {
    e.preventDefault();
    if (pwForm.new !== pwForm.confirm) {
      setError(t("page:settings.passwordMismatch"));
      return;
    }
    if (pwForm.new.length < 8) {
      setError(t("page:settings.passwordLength"));
      return;
    }
    setPwLoading(true);
    setError("");
    try {
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email: user.email,
        password: pwForm.current
      });
      if (signInError) throw new Error(t("page:settings.currentPasswordWrong"));
      const { error: updateError } = await supabase.auth.updateUser({
        password: pwForm.new
      });
      if (updateError) throw updateError;
      setPwForm({ current: "", new: "", confirm: "" });
      setMsg(t("page:settings.passwordChanged"));
      setTimeout(() => setMsg(""), 3000);
    } catch (e) {
      setError(e.message || t("page:settings.passwordChangeFailed"));
    } finally {
      setPwLoading(false);
    }
  };

  const handleLogout = async () => {
    await signOut();
    navigate("/login");
  };

  const formatDate = (iso) =>
  iso ?
  new Date(iso).toLocaleString(i18n.language, {
    dateStyle: "short",
    timeStyle: "short"
  }) :
  "-";

  if (loading || !user) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center" data-oid="t8x4dwt">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" data-oid="czfzxpp"></div>
      </div>);

  }

  const renderSkeleton = () =>
  <div className="space-y-gutter" data-oid="sk-settings">
      <SkeletonCard rows={2} />
      <SkeletonTable columns={5} rows={3} />
    </div>;

  const renderApiKeys = () =>
  <div className="space-y-gutter" data-oid="2qe4cte">
      <div className="glass-panel p-5 rounded-2xl" data-oid="d2pav9b">
        <div className="flex justify-between items-center mb-3" data-oid="dya03mx">
          <h3 className="font-headline-md text-headline-md text-on-surface" data-oid="z68qa0s">
            {t("page:settings.apiKeys")}
          </h3>
          <button
          onClick={() => setShowCreate(true)}
          className="bg-primary text-on-primary px-4 py-2 rounded-lg flex items-center gap-2 font-body-md hover:bg-primary/90 transition-all" data-oid="zjf7-:4">

            <span className="material-symbols-outlined" data-oid="_nn7wo-">add</span>
            {t("page:settings.newKey")}
          </button>
        </div>
        <div className="overflow-x-auto" data-oid="n-xsppa">
          <table className="w-full text-left" data-oid="_8vc_.i">
            <thead className="bg-surface-container-low text-on-surface-variant font-label-sm text-label-sm uppercase tracking-wider" data-oid="2q3rd3p">
              <tr data-oid="4c6t12w">
                <th className="px-4 py-3" data-oid="lso624u">{t("page:settings.label")}</th>
                <th className="px-4 py-3" data-oid="_u-2ghg">{t("page:settings.prefix")}</th>
                <th className="px-4 py-3 text-right" data-oid="2y9qpq5">
                  {t("page:settings.rate")}
                </th>
                <th className="px-4 py-3 text-right" data-oid="ux7r8:f">
                  {t("page:settings.created")}
                </th>
                <th className="px-4 py-3 text-right" data-oid="pkgve:t">
                  {t("page:settings.actions")}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant text-body-md" data-oid="bg2x9ov">
              {keys.map((k, idx) =>
            <AnimatedRow key={k.id} index={idx}>
            <tr className={k.is_active ? "" : "opacity-50"} data-oid="69kgx9v">
                  <td className="px-4 py-3" data-oid="u51z6p9">{k.name}</td>
                  <td className="px-4 py-3 font-mono text-xs" data-oid="a-vez9_">{k.prefix}</td>
                  <td className="px-4 py-3 text-right" data-oid="_3kfxj0">
                    {k.rate_limit_rpm} RPM
                  </td>
                  <td className="px-4 py-3 text-right" data-oid="y-d985.">
                    {formatDate(k.created_at)}
                  </td>
                  <td className="px-4 py-3 text-right" data-oid="b9am3z7">
                    <button
                  onClick={() => rotateKey(k.id)}
                  className="text-primary text-sm hover:underline mr-3"
                  disabled={!k.is_active} data-oid="minc.w_">

                      {t("page:settings.rotate")}
                    </button>
                    <button
                  onClick={() => deleteKey(k.id)}
                  className="text-error text-sm hover:underline" data-oid="yeqv2ns">

                      {t("page:settings.delete")}
                    </button>
                  </td>
                </tr>
            </AnimatedRow>
            )}
              {keys.length === 0 &&
            <tr data-oid=".j21cpn">
                  <td
                colSpan={5}
                className="px-4 py-8 text-center text-outline" data-oid="5dlbg_0">

                    {t("page:settings.noKeys")}
                  </td>
                </tr>
            }
            </tbody>
          </table>
        </div>
      </div>

      {showCreate &&
    <div className="glass-panel p-5 rounded-2xl" data-oid="2g_q6-q">
          <h3 className="font-headline-md text-headline-md text-on-surface mb-3" data-oid="9onqjjl">
            {t("page:settings.createKey")}
          </h3>
          <div className="flex gap-3" data-oid="d9upb3i">
            <input
          type="text"
          placeholder={t("page:settings.keyName")}
          value={newKeyName}
          onChange={(e) => setNewKeyName(e.target.value)}
          className="flex-1 bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:ring-1 focus:ring-primary focus:outline-none" data-oid="60wrtca" />


            <button
          onClick={createKey}
          className="bg-primary text-on-primary px-4 py-2 rounded-lg font-body-md hover:bg-primary/90" data-oid="ueoicm2">

              {t("page:settings.create")}
            </button>
            <button
          onClick={() => setShowCreate(false)}
          className="border border-outline-variant px-4 py-2 rounded-lg font-body-md text-on-surface hover:bg-surface-container" data-oid="acivx82">

              {t("page:settings.cancel")}
            </button>
          </div>
        </div>
    }

      {revealedKey &&
    <div className="rounded-2xl border border-amber-300 bg-amber-50 p-6" data-oid="-do9kca">
          <p className="text-xs font-semibold text-amber-800 mb-2" data-oid="4wp2fq4">
            {t("page:settings.saveKey")}
          </p>
          <div className="flex gap-2" data-oid="i3a3w5-">
            <pre className="flex-1 rounded bg-white p-3 text-xs break-all text-on-surface" data-oid="pakcgw5">
              {revealedKey.key}
            </pre>
            <button
          onClick={() => copyToClipboard(revealedKey.key)}
          className="bg-amber-700 text-white px-3 py-2 rounded-lg text-sm hover:bg-amber-800" data-oid="6mgjnvz">

              {t("page:settings.copy")}
            </button>
            <button
          onClick={() => setRevealedKey(null)}
          className="bg-slate-200 text-slate-700 px-3 py-2 rounded-lg text-sm hover:bg-slate-300" data-oid="p820zk:">

              {t("page:settings.hide")}
            </button>
          </div>
        </div>
    }
    </div>;


  const renderBilling = () =>
  <div className="space-y-gutter" data-oid="4-uks8s">
      <div className="glass-panel p-5 rounded-2xl" data-oid="q-z26g6">
        <div className="flex items-center justify-between mb-4" data-oid="g986wss">
          <div data-oid="399lxub">
            <p className="text-on-surface-variant text-body-md mb-1" data-oid="kyfb3l8">
              {t("page:settings.pointsBalance")}
            </p>
            <p className="font-headline-lg text-headline-lg text-on-surface" data-oid="454aqs4">
              {(account?.points_balance || 0).toLocaleString()}
              {t("common:points.point")}
            </p>
          </div>
          <button
          onClick={() => navigate("/payment")}
          className="bg-primary text-on-primary px-6 py-3 rounded-xl font-body-md hover:bg-primary/90 transition-all" data-oid="q8zcvdg">

            {t("page:settings.recharge")}
          </button>
        </div>
        <div className="h-px bg-outline-variant/40 mb-6" data-oid="etbfmrz"></div>
        <h3 className="font-headline-md text-headline-md text-on-surface mb-4" data-oid="1-ize60">
          {t("page:settings.paymentHistory")}
        </h3>
        <div className="overflow-x-auto" data-oid="el8:g:m">
          <table className="w-full text-left" data-oid="vq3_yp4">
            <thead className="bg-surface-container-low text-on-surface-variant font-label-sm text-label-sm uppercase tracking-wider" data-oid="slf.ie1">
              <tr data-oid="1bq:fxe">
                <th className="px-4 py-3" data-oid="5cx4kid">{t("page:settings.date")}</th>
                <th className="px-4 py-3" data-oid="a0ofd04">{t("page:settings.provider")}</th>
                <th className="px-4 py-3" data-oid="p8fn2:p">{t("page:settings.amount")}</th>
                <th className="px-4 py-3" data-oid=".q1k5u9">{t("page:settings.points")}</th>
                <th className="px-4 py-3" data-oid="sjrk31y">{t("page:settings.status")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-outline-variant text-body-md" data-oid="wped61_">
              {payments.map((p, idx) => {
              const amount = Number(p.amount) || 0;
              return (
                <AnimatedRow key={p.id} index={idx}>
                <tr data-oid="er3.xtf">
                    <td className="px-4 py-3" data-oid="qa-ku2v">{formatDate(p.created_at)}</td>
                    <td className="px-4 py-3 uppercase" data-oid="fpk8ym7">{p.provider}</td>
                    <td className="px-4 py-3" data-oid="o2ey7qg">
                      {amount.toLocaleString()} {p.currency}
                    </td>
                    <td className="px-4 py-3" data-oid="_ltes1k">
                      {p.points_added?.toLocaleString() || "-"}
                    </td>
                    <td className="px-4 py-3" data-oid="3b5pomm">
                      <span
                      className={`px-2 py-1 rounded text-xs ${p.status === "paid" ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-600"}`} data-oid="05bs4ap">

                        {p.status}
                      </span>
                    </td>
                  </tr>
                </AnimatedRow>);

            })}
              {payments.length === 0 &&
            <tr data-oid="9iwgm28">
                  <td
                colSpan={5}
                className="px-4 py-8 text-center text-outline" data-oid="a74wzoe">

                    {t("page:settings.noPayments")}
                  </td>
                </tr>
            }
            </tbody>
          </table>
        </div>
      </div>

      <div className="glass-panel p-5 rounded-2xl" data-oid="ign7w4w">
        <h3 className="font-headline-md text-headline-md text-on-surface mb-3" data-oid="0-q6tix">
          {t("page:settings.rechargePackages")}
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-gutter" data-oid="h7_mo94">
          {packages.map((pkg, idx) => {
          const points = pkg.points || 0;
          const price = pkg.price || pkg.krw || 0;
          const currency = pkg.currency || "KRW";
          return (
            <AnimatedRow key={pkg.id || `${points}-${price}`} index={idx}>
            <div
              className="border border-outline-variant p-4 flex flex-col" data-oid="nvybcdw">

                <p className="font-headline-md text-headline-md text-on-surface" data-oid="r6sm-4e">
                  {points.toLocaleString()}P
                </p>
                <p className="text-on-surface-variant text-body-md mb-4" data-oid="f-gtlyp">
                  {price.toLocaleString()} {currency}
                </p>
                <button
                onClick={() =>
                navigate("/payment", { state: { selectedPackage: pkg } })
                }
                className="mt-auto w-full bg-primary text-on-primary py-2 rounded-lg font-body-md hover:bg-primary/90" data-oid="wm:b444">

                  {t("page:settings.select")}
                </button>
              </div>
            </AnimatedRow>);

        })}
          {packages.length === 0 &&
        <p className="text-outline col-span-full" data-oid="w00zf-x">
              {t("page:settings.noPackages")}
            </p>
        }
        </div>
      </div>
    </div>;


  const renderRateLimit = () => {
    const limit = account?.rate_limit_rpm || 60;
    const quota = account?.daily_quota;
    const spent = account?.daily_spent_points || 0;
    return (
      <div className="space-y-gutter" data-oid="3jhrpct">
        <div className="glass-panel p-5 rounded-2xl" data-oid="_29zn6c">
          <h3 className="font-headline-md text-headline-md text-on-surface mb-4" data-oid="eya.8mo">
            {t("page:settings.rateLimit")}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-gutter" data-oid="8o1xxr0">
            <div className="bg-surface-container-low rounded-xl p-4" data-oid="io:eh.v">
              <p className="text-on-surface-variant text-label-sm mb-1" data-oid="d1ehxj1">
                {t("page:settings.requestsPerMinute")}
              </p>
              <p className="font-headline-md text-headline-md text-on-surface" data-oid="7m1-y1i">
                {limit}
              </p>
            </div>
            <div className="bg-surface-container-low rounded-xl p-4" data-oid="fcbv0w3">
              <p className="text-on-surface-variant text-label-sm mb-1" data-oid="rno:zf_">
                {t("page:settings.dailyQuota")}
              </p>
              <p className="font-headline-md text-headline-md text-on-surface" data-oid="v6w5t3g">
                {quota ?
                `${quota.toLocaleString()}${t("common:points.point")}` :
                t("page:settings.unlimited")}
              </p>
            </div>
            <div className="bg-surface-container-low rounded-xl p-4" data-oid="e2bbj.:">
              <p className="text-on-surface-variant text-label-sm mb-1" data-oid="ly6gkyd">
                {t("page:settings.dailySpent")}
              </p>
              <p className="font-headline-md text-headline-md text-on-surface" data-oid="jrkt_f.">
                {spent.toLocaleString()}
                {t("common:points.point")}
              </p>
            </div>
          </div>
          {quota &&
          <div className="mt-6" data-oid="hnv0f:w">
              <div className="flex justify-between text-body-md mb-2" data-oid="c1i8tr9">
                <span className="text-on-surface-variant" data-oid="zncnbl4">
                  {t("page:settings.dailyQuotaUsage")}
                </span>
                <span className="text-on-surface" data-oid="veakq2g">
                  {Math.min(100, Math.round(spent / quota * 100))}%
                </span>
              </div>
              <div className="h-2 bg-surface-container-low rounded-full overflow-hidden" data-oid="la:::33">
                <div
                className="h-full bg-primary rounded-full transition-all"
                style={{
                  width: `${Math.min(100, Math.round(spent / quota * 100))}%`
                }} data-oid="luwrgx7">
              </div>
              </div>
            </div>
          }
        </div>
      </div>);

  };

  const renderAccount = () =>
  <div className="space-y-gutter" data-oid="5ah-sa5">
      <div className="glass-panel p-5 rounded-2xl" data-oid="l263bk9">
        <h3 className="font-headline-md text-headline-md text-on-surface mb-3" data-oid="r1wbsvt">
          {t("page:settings.account")}
        </h3>
        <div className="mb-6" data-oid="rjvpra0">
          <p className="text-on-surface-variant text-label-sm mb-1" data-oid="cicps01">
            {t("page:settings.email")}
          </p>
          <p className="text-on-surface text-body-md" data-oid="d9gizo9">{user.email}</p>
        </div>
        <button
        onClick={handleLogout}
        className="border border-outline-variant text-on-surface px-4 py-2 rounded-lg font-body-md hover:bg-surface-container transition-colors" data-oid="628sff.">

          {t("page:settings.logout")}
        </button>
      </div>

      <div className="glass-panel p-5 rounded-2xl" data-oid="mc_4b2z">
        <h3 className="font-headline-md text-headline-md text-on-surface mb-3" data-oid="ijjpmrr">
          {t("page:settings.changePassword")}
        </h3>
        <form onSubmit={changePassword} className="space-y-4 max-w-md" data-oid="jg7k0rs">
          <div data-oid="0l:-ymy">
            <label className="block text-on-surface-variant text-label-sm mb-1" data-oid="to2ygs-">
              {t("page:settings.currentPassword")}
            </label>
            <input
            type="password"
            value={pwForm.current}
            onChange={(e) =>
            setPwForm({ ...pwForm, current: e.target.value })
            }
            required
            className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:ring-1 focus:ring-primary focus:outline-none" data-oid="0k:7h13" />

          </div>
          <div data-oid="1d.57ye">
            <label className="block text-on-surface-variant text-label-sm mb-1" data-oid="b59t2yy">
              {t("page:settings.newPassword")}
            </label>
            <input
            type="password"
            value={pwForm.new}
            onChange={(e) => setPwForm({ ...pwForm, new: e.target.value })}
            required
            minLength={8}
            className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:ring-1 focus:ring-primary focus:outline-none" data-oid="ko-tv86" />

          </div>
          <div data-oid="_tjfj6_">
            <label className="block text-on-surface-variant text-label-sm mb-1" data-oid="qdc.b.w">
              {t("page:settings.confirmPassword")}
            </label>
            <input
            type="password"
            value={pwForm.confirm}
            onChange={(e) =>
            setPwForm({ ...pwForm, confirm: e.target.value })
            }
            required
            minLength={8}
            className="w-full bg-surface-container-low border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:ring-1 focus:ring-primary focus:outline-none" data-oid="z5g2jun" />

          </div>
          <button
          type="submit"
          disabled={pwLoading}
          className="bg-primary text-on-primary px-4 py-2 rounded-lg font-body-md hover:bg-primary/90 disabled:opacity-50" data-oid="x_6567.">

            {pwLoading ?
          t("page:settings.changing") :
          t("page:settings.change")}
          </button>
        </form>
      </div>
    </div>;


  const tabContent = {
    api: renderApiKeys,
    billing: renderBilling,
    rate: renderRateLimit,
    account: renderAccount
  };

  return (
    <SidebarLayout
      title={t("page:settings.title")}
      subtitle={t("page:settings.subtitle")} data-oid="9_cgo-g">

      {(error || msg) &&
      <div
        className={`px-4 py-3 rounded-xl text-sm border mb-8 ${
        error ?
        "bg-error-container text-error border-error/10" :
        "bg-green-50 text-green-700 border-green-200"}`
        } data-oid="fei6g:8">

          {error || msg}
        </div>
      }

      <div className="flex flex-col md:flex-row gap-gutter" data-oid="ci89oi2">
        <nav className="md:w-56 shrink-0 space-y-1" data-oid="d:aw:qt">
          {tabs.map((tab, idx) =>
          <AnimatedRow key={tab.id} index={idx}>
          <button
            onClick={() => setActiveTab(tab.id)}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg text-left font-body-md transition-colors ${
            activeTab === tab.id ?
            "bg-primary-container/10 text-primary font-bold border-r-2 border-primary" :
            "text-on-surface-variant hover:bg-primary-container/10"}`
            } data-oid="7sy7onx">

              <span className="material-symbols-outlined text-xl" data-oid="lsx_k19">
                {tab.icon}
              </span>
              {tab.label}
            </button>
          </AnimatedRow>
          )}
        </nav>

        <div className="flex-1 min-w-0" data-oid="i6u7p60">
          {dataLoading ? renderSkeleton() : tabContent[activeTab]()}
        </div>
      </div>
    </SidebarLayout>);

}