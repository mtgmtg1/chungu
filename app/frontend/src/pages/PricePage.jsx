// [Flow: Step 1 (헤더 렌더링) -> Step 2 (정적 플랜 데이터 설정) -> Step 3 (월간/연간 토글) -> Step 4 (구독 요금제 카드 렌더링) -> Step 5 (모든 요금제 공통 혜택 안내) -> Step 6 (API 가격 페이지 링크 안내) -> Step 7 (푸터)]
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, FileSpreadsheet, Mail, Shield, FileUp } from "lucide-react";
import { api } from "../api.js";
import GlobalFooter from "../components/GlobalFooter.jsx";
import { useAuth } from "../AuthContext.jsx";
import { SkeletonCard } from "../components/Skeleton.jsx";
import PlanCard from "../components/PlanCard.jsx";

/** UI에 표시할 구독 요금제 정적 데이터 (/api/subscriptions/plans 제거 대체) */
const STATIC_PLANS = [
  {
    key: "free",
    name: "Free",
    monthly_usd: 0,
    yearly_usd: 0,
    limits: { basic_pages: 1000, premium_pages: 500, media_seconds: 9000 },
  },
  {
    key: "pro",
    name: "Pro",
    monthly_usd: 20,
    yearly_usd: 200,
    limits: { basic_pages: 10000, premium_pages: 5000, media_seconds: 90000 },
  },
  {
    key: "max",
    name: "Max",
    monthly_usd: 100,
    yearly_usd: 1000,
    limits: { basic_pages: 60000, premium_pages: 30000, media_seconds: 540000 },
  },
];

/** 모든 요금제에 포함된 공통 혜택 아이콘 매핑 */
const INCLUDED_FEATURES = [
  { icon: FileSpreadsheet, key: "includedFeature1" },
  { icon: FileUp, key: "includedFeature2" },
  { icon: Mail, key: "includedFeature3" },
  { icon: Shield, key: "includedFeature4" },
];

/**
 * 가격 정책 페이지를 렌더링합니다.
 * 구독 요금제를 메인 콘텐츠로 표시하고, API 개발자용 가격 안내는 하단 링크로 제공합니다.
 * @returns {JSX.Element} 가격 페이지 전체 UI
 */
export default function PricePage() {
  const { user } = useAuth();
  const { t } = useTranslation();
  const nav = useNavigate();
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
      setPlans(STATIC_PLANS);
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

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 via-blue-50/30 to-white" data-oid="price-page">
      <header className="border-b border-slate-200/80 bg-white/80 backdrop-blur" data-oid="price-header">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center gap-3" data-oid="price-header-inner">
          <button
            onClick={() => nav(-1)}
            className="p-2 rounded-lg text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors"
            data-oid="price-back"
          >
            <ArrowLeft size={20} />
          </button>
          <h1 className="text-xl font-bold text-slate-900" data-oid="price-title">
            {t("page:price.title")}
          </h1>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-margin-mobile md:px-6 py-8 md:py-16" data-oid="price-main">
        <div className="text-center mb-8 md:mb-10" data-oid="price-hero">
          <h2
            className="text-3xl md:text-4xl lg:text-5xl font-bold text-slate-900 mb-4 tracking-tight"
            data-oid="price-hero-title"
          >
            {t("page:plans.heroTitle")}
          </h2>
          <p className="text-base md:text-lg lg:text-xl text-slate-600 max-w-2xl mx-auto leading-relaxed" data-oid="price-hero-desc">
            {t("page:plans.heroDesc")}
          </p>
        </div>

        <div className="flex justify-center mb-12">
          <div className="inline-flex bg-white rounded-full p-1.5 border border-slate-200 shadow-sm">
            <button
              onClick={() => setCycle("monthly")}
              className={`px-6 py-2.5 rounded-full text-sm font-semibold transition-all ${
                cycle === "monthly" ? "bg-blue-600 text-white shadow-md" : "text-slate-600 hover:text-slate-900"
              }`}
              data-oid="price-cycle-monthly"
            >
              {t("page:plans.monthly")}
            </button>
            <button
              onClick={() => setCycle("yearly")}
              className={`px-6 py-2.5 rounded-full text-sm font-semibold transition-all ${
                cycle === "yearly" ? "bg-blue-600 text-white shadow-md" : "text-slate-600 hover:text-slate-900"
              }`}
              data-oid="price-cycle-yearly"
            >
              {t("page:plans.yearly")}
            </button>
          </div>
        </div>

        {error && <p className="text-center text-red-600 text-sm mb-6">{error}</p>}
        {success && <p className="text-center text-blue-600 text-sm mb-6">{success}</p>}

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-16">
            <SkeletonCard rows={5} />
            <SkeletonCard rows={5} />
            <SkeletonCard rows={5} />
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-stretch mb-16">
              {plans.map((plan) => (
                <PlanCard
                  key={plan.key}
                  plan={plan}
                  cycle={cycle}
                  selected={mySubscription?.plan === plan.key}
                  recommended={plan.key === "pro"}
                  onSelect={handleSelect}
                  disabled={checkingOut}
                  dataOid={`price-card-${plan.key}`}
                />
              ))}
            </div>

            <div
              className="bg-white border border-slate-200 rounded-3xl p-5 md:p-8 lg:p-10 shadow-lg mb-12"
              data-oid="price-included"
            >
              <h3 className="text-center text-2xl font-bold text-slate-900 mb-8">
                {t("page:plans.includedInAllPlans")}
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-6">
                {INCLUDED_FEATURES.map(({ icon: Icon, key }) => (
                  <div key={key} className="flex flex-col items-center text-center gap-3">
                    <div className="w-12 h-12 rounded-full bg-blue-50 flex items-center justify-center">
                      <Icon className="text-blue-600" size={24} />
                    </div>
                    <p className="text-sm font-medium text-slate-700">{t(`page:plans.${key}`)}</p>
                  </div>
                ))}
              </div>
            </div>

            <div
              className="bg-gradient-to-br from-blue-50 to-blue-100/50 border border-blue-100 rounded-2xl p-6 md:p-8 text-center"
              data-oid="price-api-notice"
            >
              <p className="text-blue-900 text-base font-medium mb-3">{t("page:plans.apiPricingNotice")}</p>
              <Link
                to="/api-pricing"
                className="inline-flex items-center gap-1 text-blue-700 hover:text-blue-800 font-semibold hover:underline"
                data-oid="price-to-api-link"
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
