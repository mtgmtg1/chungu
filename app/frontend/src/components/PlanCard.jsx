// [Flow: Step 1 (플랜 정보 수신) -> Step 2 (Free/유료 구분 및 선택 상태 표시) -> Step 3 (한도 목록 및 구독 버튼 렌더링)]
import { useTranslation } from "react-i18next";
import { Check, Loader2, Sparkles, Zap, Crown } from "lucide-react";

function formatDuration(seconds) {
  if (!seconds) return "0";
  return Math.round(seconds / 60).toLocaleString();
}

/**
 * 구독 요금제 카드 하나를 렌더링합니다.
 * @param {Object} props - React props
 * @param {Object} props.plan - 플랜 객체 (key, name, limits, monthly_usd, yearly_usd)
 * @param {string} props.cycle - "monthly" | "yearly"
 * @param {boolean} props.selected - 현재 사용자의 플랜인지 여부
 * @param {Function} props.onSelect - 플랜 선택 핸들러
 * @param {boolean} props.disabled - 버튼 비활성화 여부
 * @param {string} props.dataOid - QA 테스트용 data-oid 식별자
 * @returns {JSX.Element} 구독 요금제 카드
 */
export default function PlanCard({ plan, cycle, selected, onSelect, disabled, dataOid }) {
  const { t } = useTranslation();
  const limits = plan.limits;
  const isFree = plan.monthly_usd === 0;
  const price = cycle === "monthly" ? plan.monthly_usd : plan.yearly_usd;

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
        <p className="text-4xl font-extrabold text-slate-900 mb-1">${price}</p>
        <p className="text-sm text-slate-500">
          /{cycle === "monthly" ? t("page:plans.month") : t("page:plans.year")}
        </p>
      </div>
      <ul className="space-y-3 mb-8 flex-grow">
        <li className="flex items-start gap-2 text-sm text-slate-600">
          <Check size={16} className="text-emerald-500 mt-0.5 flex-shrink-0" />
          <span>{t("page:plans.basicPages", { count: limits.basic_pages.toLocaleString() })}</span>
        </li>
        <li className="flex items-start gap-2 text-sm text-slate-600">
          <Check size={16} className="text-emerald-500 mt-0.5 flex-shrink-0" />
          <span>{t("page:plans.premiumPages", { count: limits.premium_pages.toLocaleString() })}</span>
        </li>
        <li className="flex items-start gap-2 text-sm text-slate-600">
          <Check size={16} className="text-emerald-500 mt-0.5 flex-shrink-0" />
          <span>{t("page:plans.mediaMinutes", { count: formatDuration(limits.media_seconds) })}</span>
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
