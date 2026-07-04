// [Flow: Step 1 (플랜 목록 로드) -> Step 2 (월간/연간 토글) -> Step 3 (Paddle Checkout 열기) -> Step 4 (현재 구독 상태 표시)]
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Check, Loader2, Sparkles, Zap, Crown } from "lucide-react";
import { api } from "../api.js";
import GlobalFooter from "../components/GlobalFooter.jsx";
import { useAuth } from "../AuthContext.jsx";
import { SkeletonCard } from "../components/Skeleton.jsx";

function formatDuration(seconds) {
  if (!seconds) return "0";
  return Math.round(seconds / 60).toLocaleString();
}

function PlanCard({ plan, cycle, price, selected, onSelect, disabled, dataOid }) {
  const { t } = useTranslation();
  const limits = plan.limits;
  const isFree = plan.monthly_usd === 0;

  return (
    <div
      className={`relative bg-white rounded-3xl p-7 shadow-lg border flex flex-col ${
        selected ? "border-blue-500 ring-2 ring-blue-500/20" : "border-slate-200"
      }`}
      data-oid={dataOid}
    >
      {selected && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-blue-600 text-white text-xs font-bold px-3 py-1 rounded-full shadow-sm">
          {t("page:plans.currentPlan")}
        </div>
      )}
      <div className="flex flex-col items-center text-center mb-6">
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-100 to-cyan-50 flex items-center justify-center mb-4 shadow-sm">
          {plan.key === "free" && <Sparkles className="text-blue-600" size={32} />}
          {plan.key === "pro" && <Zap className="text-amber-500" size={32} />}
          {plan.key === "max" && <Crown className="text-purple-600" size={32} />}
        </div>
        <h3 className="text-xl font-bold text-slate-900">{plan.name}</h3>
      </div>
      <div className="text-center mb-6">
        <p className="text-4xl font-extrabold text-slate-900 mb-1">
          ${price}
        </p>
        <p className="text-sm text-slate-500">
          /{cycle === "monthly" ? t("page:plans.month") : t("page:plans.year")}
        </p>
      </div>
      <ul className="space-y-3 mb-8 flex-grow">
        <li className="flex items-start gap-2 text-sm text-slate-600">
          <Check size={16} className="text-emerald-500 mt-0.5 flex-shrink-0" />
          <span>
            {t("page:plans.basicPages", { count: limits.basic_pages.toLocaleString() })}
          </span>
        </li>
        <li className="flex items-start gap-2 text-sm text-slate-600">
          <Check size={16} className="text-emerald-500 mt-0.5 flex-shrink-0" />
          <span>
            {t("page:plans.premiumPages", { count: limits.premium_pages.toLocaleString() })}
          </span>
        </li>
        <li className="flex items-start gap-2 text-sm text-slate-600">
          <Check size={16} className="text-emerald-500 mt-0.5 flex-shrink-0" />
          <span>
            {t("page:plans.mediaMinutes", { count: formatDuration(limits.media_seconds) })}
          </span>
        </li>
      </ul>
      <button
        onClick={() => onSelect(plan.key, cycle)}
        disabled={disabled}
        className={`w-full py-3 rounded-xl font-semibold transition-all flex items-center justify-center gap-2 ${
          isFree
            ? "bg-slate-100 text-slate-700 hover:bg-slate-200"
            : "bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
        }`}
        data-oid={`${dataOid}-btn`}
      >
        {disabled ? (
          <Loader2 className="animate-spin" size={18} />
        ) : (
          t(isFree ? "page:plans.freeButton" : "page:plans.subscribeButton")
        )}
      </button>
    </div>
  );
}

export default function PlansPage() {
  const { user } = useAuth();
  const { t } = useTranslation();
  const [plans, setPlans] = useState([]);
  const [mySubscription, setMySubscription] = useState(null);
  const [cycle, setCycle] = useState("monthly");
  const [loading, setLoading] = useState(true);
  const [checkingOut, setCheckingOut] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    if (window.Paddle) {
      window.Paddle.Initialize({ token: "live_7809a123ef46120bc1f57e7aba5" });
    }
  }, []);

  useEffect(() => {
    load();
  }, [user]);

  async function load() {
    try {
      const plansData = await api.getSubscriptionPlans();
      setPlans(plansData.plans || []);
      if (user) {
        const sub = await api.getMySubscription();
        setMySubscription(sub);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleSelect(planKey, selectedCycle) {
    if (!user) {
      setError(t("page:plans.loginRequired"));
      return;
    }
    if (planKey === "free") {
      setSuccess(t("page:plans.freeSelected"));
      return;
    }
    setCheckingOut(true);
    setError("");
    setSuccess("");
    try {
      const checkout = await api.createSubscriptionCheckout({
        plan: planKey,
        cycle: selectedCycle,
      });
      if (window.Paddle && checkout.transaction_id) {
        window.Paddle.Checkout.open({ transactionId: checkout.transaction_id });
      } else if (checkout.checkout_url) {
        window.open(checkout.checkout_url, "_blank");
      } else {
        throw new Error("No checkout URL or transaction ID returned");
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setCheckingOut(false);
    }
  }

  async function handleCancel() {
    if (!window.confirm(t("page:plans.cancelConfirm"))) return;
    setCheckingOut(true);
    setError("");
    try {
      await api.cancelSubscription();
      setSuccess(t("page:plans.cancelScheduled"));
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setCheckingOut(false);
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50/60 to-rose-50/40">
      <header className="border-b bg-white/80 backdrop-blur">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center gap-2">
          <Link to="/" className="text-slate-500 hover:text-slate-800">
            <ArrowLeft size={20} />
          </Link>
          <h1 className="text-xl font-bold">{t("page:plans.title")}</h1>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10">
        <div className="text-center mb-8">
          <h2 className="text-3xl font-bold text-slate-900 mb-3">
            {t("page:plans.heroTitle")}
          </h2>
          <p className="text-lg text-slate-600 max-w-2xl mx-auto">
            {t("page:plans.heroDesc")}
          </p>
        </div>

        <div className="flex justify-center mb-10">
          <div className="inline-flex bg-white rounded-full p-1 border border-slate-200 shadow-sm">
            <button
              onClick={() => setCycle("monthly")}
              className={`px-5 py-2 rounded-full text-sm font-medium transition-all ${
                cycle === "monthly"
                  ? "bg-blue-600 text-white"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              {t("page:plans.monthly")}
            </button>
            <button
              onClick={() => setCycle("yearly")}
              className={`px-5 py-2 rounded-full text-sm font-medium transition-all ${
                cycle === "yearly"
                  ? "bg-blue-600 text-white"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              {t("page:plans.yearly")}
            </button>
          </div>
        </div>

        {error && (
          <p className="text-center text-red-600 text-sm mb-6">{error}</p>
        )}
        {success && (
          <p className="text-center text-blue-600 text-sm mb-6">{success}</p>
        )}

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <SkeletonCard rows={5} />
            <SkeletonCard rows={5} />
            <SkeletonCard rows={5} />
          </div>
        ) : (
          <>
            {mySubscription && (
              <div className="bg-white border border-slate-200 rounded-2xl p-5 mb-8 shadow-sm">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <p className="text-sm text-slate-500 mb-1">
                      {t("page:plans.currentPlan")}
                    </p>
                    <p className="text-lg font-bold text-slate-900">
                      {mySubscription.plan} — {mySubscription.status}
                    </p>
                    <p className="text-sm text-slate-500">
                      {t("page:plans.remainingBasic", { count: mySubscription.remaining.basic_pages })}
                      {" · "}
                      {t("page:plans.remainingPremium", { count: mySubscription.remaining.premium_pages })}
                      {" · "}
                      {t("page:plans.remainingMedia", { count: formatDuration(mySubscription.remaining.media_seconds) })}
                    </p>
                  </div>
                  {mySubscription.status === "active" && (
                    <button
                      onClick={handleCancel}
                      disabled={checkingOut}
                      className="text-sm text-slate-500 hover:text-red-600 underline"
                    >
                      {t("page:plans.cancelSubscription")}
                    </button>
                  )}
                </div>
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-12">
              {plans.map((plan) => {
                const price = cycle === "monthly" ? plan.monthly_usd : plan.yearly_usd;
                const isCurrent = mySubscription?.plan === plan.key;
                return (
                  <PlanCard
                    key={plan.key}
                    plan={plan}
                    cycle={cycle}
                    price={price}
                    selected={isCurrent}
                    onSelect={handleSelect}
                    disabled={checkingOut}
                    dataOid={`plans-${plan.key}-card`}
                  />
                );
              })}
            </div>

            <div className="text-center">
              <p className="text-sm text-slate-500 mb-2">
                {t("page:plans.apiPricingNotice")}
              </p>
              <Link
                to="/price"
                className="inline-flex items-center gap-1 text-blue-600 hover:underline font-medium"
              >
                {t("page:plans.apiPricingLink")}
              </Link>
            </div>
          </>
        )}
      </main>
      <GlobalFooter />
    </div>
  );
}
