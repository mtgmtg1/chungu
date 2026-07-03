// [Flow: Step 1 (잔액/충전 한도 조회) -> Step 2 (자유 금액 입력) -> Step 3 (Paddle 결제) -> Step 4 (자동 충전 설정)]
import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Coins,
  CreditCard,
  ArrowLeft,
  Loader2,
  CheckCircle2,
  Zap,
  Settings2,
  Server } from
"lucide-react";
import { api } from "../api.js";
import { useAuth } from "../AuthContext.jsx";
import { SkeletonCard } from "../components/Skeleton.jsx";

/** milli-USD를 USD 달러 문자열로 변환 */
function mdToUsd(md) {
  if (md == null) return "-";
  return `$${(md / 1000).toFixed(2)}`;
}

export default function PaymentPage() {
  const { user } = useAuth();
  const { t } = useTranslation();
  const [profile, setProfile] = useState(null);
  const [limits, setLimits] = useState({ min_amount: 5, max_amount: 500 });
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");
  const [agreePayment, setAgreePayment] = useState(false);
  const [chargeAmount, setChargeAmount] = useState(10);

  // 자동 충전
  const [autoRecharge, setAutoRecharge] = useState({ enabled: false, threshold: 2000, amount: 10, has_payment_method: false, retries: 0 });
  const [autoSaving, setAutoSaving] = useState(false);
  const [autoMsg, setAutoMsg] = useState("");
  const nav = useNavigate();

  useEffect(() => {
    if (!user) return;
    load();
  }, [user]);

  async function load() {
    try {
      const [pkg, me, ar] = await Promise.all([api.getPackages(), api.me(), api.getAutoRechargeSettings()]);
      setLimits({ min_amount: pkg.min_amount || 5, max_amount: pkg.max_amount || 500 });
      setProfile(me);
      setAutoRecharge(ar);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function payWithPaddle() {
    setPaying(true);
    setError("");
    setSuccess(false);
    try {
      const checkout = await api.createPaddleCheckout({ amount: chargeAmount });
      window.open(checkout.checkout_url, "_blank");
      setSuccess(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setPaying(false);
    }
  }

  async function saveAutoRecharge() {
    setAutoSaving(true);
    setAutoMsg("");
    try {
      const result = await api.updateAutoRechargeSettings({
        enabled: autoRecharge.enabled,
        threshold: autoRecharge.threshold,
        amount: autoRecharge.amount,
      });
      setAutoRecharge({ ...autoRecharge, ...result });
      setAutoMsg(t("page:payment.autoRechargeSaved"));
    } catch (e) {
      setAutoMsg(e.message);
    } finally {
      setAutoSaving(false);
    }
  }

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center" data-oid="mjx7mna">
        <div className="text-center" data-oid="t.p7jw0">
          <p data-oid="sh:71dz">{t("page:payment.loginRequired")}</p>
          <button
            onClick={() => nav("/login")}
            className="bg-blue-600 text-white px-4 py-2 rounded-lg mt-4" data-oid="f7tjrz_">
            {t("page:payment.login")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50" data-oid="ti5b7jd">
      <header className="border-b bg-white" data-oid="u5:vv96">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between" data-oid="1c44p8h">
          <div className="flex items-center gap-2" data-oid="wunuvs3">
            <Link to="/dashboard" className="text-slate-500 hover:text-slate-800" data-oid="q2-gs61">
              <ArrowLeft size={20} data-oid="84tplgv" />
            </Link>
            <h1 className="text-xl font-bold" data-oid="vx2ugc2">{t("page:payment.title")}</h1>
          </div>
          <div className="flex items-center gap-2 text-sm" data-oid="o1fv93u">
            <Coins size={18} className="text-yellow-500" data-oid="5qemmsy" />
            <span data-oid="xkf9k4_">
              {t("page:payment.balanceUsd", { usd: mdToUsd(profile?.points_balance) })}
            </span>
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8" data-oid="re0ndhu">
        {success && (
          <div className="bg-green-50 text-green-700 rounded-lg p-4 mb-6 flex items-center gap-2" data-oid="uky.q5p">
            <CheckCircle2 size={20} data-oid="9pf.6q0" /> {t("page:payment.rechargeComplete")}
          </div>
        )}
        {error && <p className="text-red-600 text-sm mb-6" data-oid="kqiknzg">{error}</p>}

        {loading ? (
          <SkeletonCard rows={4} />
        ) : (
          <>
            {/* 자유 금액 충전 카드 */}
            <div className="bg-white border rounded-xl p-6 mb-6" data-oid="charge-card">
              <h2 className="text-lg font-bold mb-4 flex items-center gap-2" data-oid="charge-title">
                <CreditCard size={20} data-oid="charge-icon" /> {t("page:payment.chargeTitle")}
              </h2>
              <div className="space-y-4" data-oid="charge-body">
                <div data-oid="amount-input-wrap">
                  <label className="block text-sm text-slate-600 mb-1" data-oid="amount-label">
                    {t("page:payment.chargeAmount")}
                  </label>
                  <div className="flex items-center gap-2" data-oid="amount-input-row">
                    <span className="text-2xl font-bold text-slate-700" data-oid="dollar-sign">$</span>
                    <input
                      type="number"
                      min={limits.min_amount}
                      max={limits.max_amount}
                      step="1"
                      value={chargeAmount}
                      onChange={(e) => setChargeAmount(Math.max(1, parseInt(e.target.value) || 0))}
                      className="w-32 border rounded-lg px-3 py-2 text-lg font-semibold"
                      data-oid="amount-input"
                    />
                    <span className="text-sm text-slate-400" data-oid="amount-hint">
                      ({t("page:payment.chargeLimits", { min: limits.min_amount, max: limits.max_amount })})
                    </span>
                  </div>
                </div>
                <button
                  onClick={payWithPaddle}
                  disabled={paying || !agreePayment || chargeAmount < limits.min_amount || chargeAmount > limits.max_amount}
                  className="w-full bg-blue-600 text-white py-3 font-medium hover:bg-blue-700 disabled:opacity-50 rounded-lg flex items-center justify-center gap-2"
                  data-oid="pay-btn"
                >
                  {paying ? (
                    <Loader2 className="animate-spin" size={18} data-oid="pay-spinner" />
                  ) : (
                    <>
                      <CreditCard size={18} data-oid="pay-card-icon" />
                      {t("page:payment.chargeButton", { amount: chargeAmount })}
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* 자동 충전 설정 카드 */}
            <div className="bg-white border rounded-xl p-6 mb-6" data-oid="auto-card">
              <h2 className="text-lg font-bold mb-4 flex items-center gap-2" data-oid="auto-title">
                <Zap size={20} className="text-amber-500" data-oid="auto-icon" />
                {t("page:payment.autoRechargeTitle")}
              </h2>

              {!autoRecharge.has_payment_method && (
                <p className="text-sm text-slate-500 mb-3" data-oid="no-pm-notice">
                  {t("page:payment.autoRechargeNoMethod")}
                </p>
              )}

              <div className="space-y-4" data-oid="auto-body">
                {/* 활성화 토글 */}
                <label className="flex items-center justify-between" data-oid="auto-toggle-wrap">
                  <span className="text-sm font-medium" data-oid="auto-toggle-label">
                    {t("page:payment.autoRechargeEnable")}
                  </span>
                  <button
                    onClick={() => setAutoRecharge({ ...autoRecharge, enabled: !autoRecharge.enabled })}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${autoRecharge.enabled ? "bg-blue-600" : "bg-slate-300"}`}
                    data-oid="auto-toggle"
                  >
                    <span className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${autoRecharge.enabled ? "translate-x-6" : "translate-x-1"}`} />
                  </button>
                </label>

                {/* 임계값 입력 */}
                <div data-oid="threshold-wrap">
                  <label className="block text-sm text-slate-600 mb-1" data-oid="threshold-label">
                    {t("page:payment.autoRechargeThreshold")}
                  </label>
                  <div className="flex items-center gap-2" data-oid="threshold-row">
                    <span className="text-lg font-bold text-slate-700" data-oid="threshold-dollar">$</span>
                    <input
                      type="number"
                      min="0.5"
                      step="0.5"
                      value={autoRecharge.threshold / 1000}
                      onChange={(e) => setAutoRecharge({ ...autoRecharge, threshold: Math.round((parseFloat(e.target.value) || 0) * 1000) })}
                      className="w-24 border rounded-lg px-3 py-1.5"
                      data-oid="threshold-input"
                    />
                  </div>
                </div>

                {/* 충전 금액 입력 */}
                <div data-oid="auto-amount-wrap">
                  <label className="block text-sm text-slate-600 mb-1" data-oid="auto-amount-label">
                    {t("page:payment.autoRechargeAmount")}
                  </label>
                  <div className="flex items-center gap-2" data-oid="auto-amount-row">
                    <span className="text-lg font-bold text-slate-700" data-oid="auto-amount-dollar">$</span>
                    <input
                      type="number"
                      min="5"
                      max="500"
                      step="1"
                      value={autoRecharge.amount}
                      onChange={(e) => setAutoRecharge({ ...autoRecharge, amount: Math.max(1, parseInt(e.target.value) || 0) })}
                      className="w-24 border rounded-lg px-3 py-1.5"
                      data-oid="auto-amount-input"
                    />
                  </div>
                </div>

                {autoRecharge.retries > 0 && (
                  <p className="text-sm text-amber-600" data-oid="retry-notice">
                    {t("page:payment.autoRechargeRetries", { count: autoRecharge.retries })}
                  </p>
                )}

                {autoMsg && <p className="text-sm text-blue-600" data-oid="auto-msg">{autoMsg}</p>}

                <button
                  onClick={saveAutoRecharge}
                  disabled={autoSaving}
                  className="w-full bg-slate-800 text-white py-2 font-medium hover:bg-slate-900 disabled:opacity-50 rounded-lg flex items-center justify-center gap-2"
                  data-oid="auto-save-btn"
                >
                  {autoSaving ? (
                    <Loader2 className="animate-spin" size={16} data-oid="auto-save-spinner" />
                  ) : (
                    <>
                      <Settings2 size={16} data-oid="auto-save-icon" />
                      {t("page:payment.autoRechargeSave")}
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* 온프레미스 로컬 서버 프로모션 카드 */}
            <div className="bg-white border rounded-xl p-6 mb-6" data-oid="onprem-card">
              <h2 className="text-lg font-bold mb-2 flex items-center gap-2" data-oid="onprem-card-title">
                <Server size={20} className="text-blue-600" data-oid="onprem-card-icon" /> {t("page:onPremise.title")}
              </h2>
              <p className="text-sm text-slate-600 mb-4" data-oid="onprem-card-desc">
                {t("page:onPremise.subtitle")}
              </p>
              <ul className="text-sm text-slate-600 mb-4 space-y-1" data-oid="onprem-card-features">
                <li className="flex items-center gap-2"><span className="text-blue-600">✓</span> {t("page:onPremise.featureUnlimited")}</li>
                <li className="flex items-center gap-2"><span className="text-blue-600">✓</span> {t("page:onPremise.featureSecure")}</li>
                <li className="flex items-center gap-2"><span className="text-blue-600">✓</span> {t("page:onPremise.featureUpdates")}</li>
                <li className="flex items-center gap-2"><span className="text-blue-600">✓</span> {t("page:onPremise.featureSupport")}</li>
              </ul>
              <Link
                to="/on-premise"
                className="inline-block text-sm font-medium text-blue-600 hover:underline"
                data-oid="onprem-card-link"
              >
                {t("page:onPremise.formTitle")} →
              </Link>
            </div>
          </>
        )}
      </main>

      <div className="max-w-3xl mx-auto px-6 pb-8" data-oid="pay-consent-wrap">
        <div className="mb-4 space-y-1 text-sm text-slate-500" data-oid="pay-legal-info">
          <p data-oid="pay-refund-summary">↩ {t("legal.consent.refundSummary")}</p>
          <p data-oid="pay-tax-notice">↩ {t("legal.consent.taxNotice")}</p>
        </div>
        <label className="flex items-start gap-2 text-sm text-slate-600" data-oid="pay-consent">
          <input
            type="checkbox"
            checked={agreePayment}
            onChange={(e) => setAgreePayment(e.target.checked)}
            className="mt-0.5"
            data-oid="chk-pay-consent"
          />
          <span>
            <Link to="/terms" target="_blank" className="text-blue-600 hover:underline" data-oid="lnk-pay-terms">
              {t("legal.consent.agreePayment")}
            </Link>
          </span>
        </label>
      </div>
    </div>
  );
}