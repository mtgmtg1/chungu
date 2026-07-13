// [Flow: Step 1 (플랜 정보 수신) -> Step 2 (Free/유료/추천 상태 결정) -> Step 3 (한도 목록 및 구독 버튼 렌더링)]
import { useTranslation } from "react-i18next";
import { Check, Loader2, Sparkles, Zap, Crown } from "lucide-react";

/**
 * 구독 요금제 카드 하나를 렌더링합니다.
 * @param {Object} props - React props
 * @param {Object} props.plan - 플랜 객체 (key, name, monthly_credits, monthly_usd, yearly_usd)
 * @param {string} props.cycle - "monthly" | "yearly"
 * @param {boolean} props.selected - 현재 사용자의 플랜인지 여부
 * @param {boolean} props.recommended - 추천 플랜 여부 (Pro)
 * @param {Function} props.onSelect - 플랜 선택 핸들러
 * @param {boolean} props.disabled - 버튼 비활성화 여부
 * @param {string} props.dataOid - QA 테스트용 data-oid 식별자
 * @returns {JSX.Element} 구독 요금제 카드
 */
export default function PlanCard({ plan, cycle, selected, recommended, onSelect, disabled, dataOid }) {
  const { t } = useTranslation();
  const monthlyCredits = plan.monthly_credits;
  const isFree = plan.monthly_usd === 0;
  const price = cycle === "monthly" ? plan.monthly_usd : plan.yearly_usd;

  const accentByPlan = {
    free: { iconBg: "bg-slate-100", iconText: "text-slate-600", badge: null },
    pro: { iconBg: "bg-blue-100", iconText: "text-blue-600", badge: t("page:plans.mostPopular") },
    max: { iconBg: "bg-purple-100", iconText: "text-purple-600", badge: null },
  };
  const accent = accentByPlan[plan.key] || accentByPlan.free;

  return (
    <div
      className={`relative bg-white rounded-3xl p-7 flex flex-col transition-all duration-200 ${
        selected || recommended
          ? "border-2 border-blue-500 shadow-xl shadow-blue-500/10 scale-[1.02]"
          : "border border-slate-200 shadow-lg hover:shadow-xl hover:-translate-y-1"
      } ${plan.key === "max" && !selected && !recommended ? "border-purple-200" : ""}`}
      data-oid={dataOid}
    >
      {(selected || recommended) && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-blue-600 text-white text-xs font-bold px-3 py-1 rounded-full shadow-sm">
          {selected ? t("page:plans.currentPlan") : accent.badge}
        </div>
      )}

      <div className="flex flex-col items-center text-center mb-6">
        <div className={`w-16 h-16 rounded-2xl ${accent.iconBg} flex items-center justify-center mb-4 shadow-sm`}>
          {plan.key === "free" && <Sparkles className={accent.iconText} size={32} />}
          {plan.key === "pro" && <Zap className={accent.iconText} size={32} />}
          {plan.key === "max" && <Crown className={accent.iconText} size={32} />}
        </div>
        <h3 className="text-xl font-bold text-slate-900">{plan.name}</h3>
      </div>

      <div className="text-center mb-6">
        <p className="text-4xl font-extrabold text-slate-900 mb-1">${price}</p>
        <p className="text-sm text-slate-500">
          /{cycle === "monthly" ? t("page:plans.month") : t("page:plans.year")}
        </p>
      </div>

      <ul className="space-y-3 mb-8 flex-grow">
        <li className="flex items-start gap-2 text-sm text-slate-600">
          <Check size={16} className="text-emerald-500 mt-0.5 flex-shrink-0" />
          <span>{t("page:plans.monthlyCredits", { count: monthlyCredits.toLocaleString() })}</span>
        </li>
      </ul>

      <button
        onClick={() => onSelect(plan.key, cycle)}
        disabled={disabled}
        className={`w-full py-3 rounded-xl font-semibold transition-all flex items-center justify-center gap-2 ${
          isFree
            ? "bg-slate-100 text-slate-700 hover:bg-slate-200"
            : plan.key === "max"
            ? "bg-gradient-to-r from-purple-600 to-indigo-600 text-white hover:from-purple-700 hover:to-indigo-700 disabled:opacity-50"
            : "bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
        }`}
        data-oid={`${dataOid}-btn`}
      >
        {disabled ? <Loader2 className="animate-spin" size={18} /> : t(isFree ? "page:plans.freeButton" : "page:plans.subscribeButton")}
      </button>
    </div>
  );
}
