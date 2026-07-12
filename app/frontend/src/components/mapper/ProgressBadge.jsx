// [Flow: Step 1 (overall_progress_percent 수신) -> Step 2 (프로그레스 바 너비 계산) -> Step 3 (도넛 차트 stroke-dasharray 계산) -> Step 4 (두 시각화 동시 렌더링)]
// 요건사실 퍼즐 매퍼의 입증 달성도를 프로그레스 바 + 도넛 차트 뱃지로 시각화.
// shadcn/ui 없이 Tailwind 유틸리티와 SVG로만 구현.
import { useTranslation } from "react-i18next";

/**
 * ProgressBadge — 전체 요건 중 1개 이상 증거가 매핑된 요건의 비율(%)을 시각화.
 *
 * @param {Object} props
 * @param {number} props.percent - 입증 달성도 (0~100)
 */
export default function ProgressBadge({ percent }) {
  const { t } = useTranslation();
  const clamped = Math.max(0, Math.min(100, Math.round(percent || 0)));
  // 도넛 차트용 stroke-dasharray 계산 (원둘레 = 2πr, r=16 → 둘레 ≈ 100.53)
  const radius = 16;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - clamped / 100);

  return (
    <div className="flex items-center gap-3" data-oid="mapper-progress-badge">
      {/* 도넛 차트 뱃지 */}
      <div className="relative flex-shrink-0" data-oid="mapper-donut">
        <svg width="40" height="40" viewBox="0 0 40 40" className="-rotate-90">
          <circle
            cx="20"
            cy="20"
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth="4"
            className="text-surface-container-high"
          />
          <circle
            cx="20"
            cy="20"
            r={radius}
            fill="none"
            stroke="currentColor"
            strokeWidth="4"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            className="text-blue-600 transition-all duration-500"
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-on-surface">
          {clamped}%
        </span>
      </div>

      {/* 프로그레스 바 */}
      <div className="flex-1 min-w-[120px]" data-oid="mapper-progress-bar">
        <div className="flex items-center justify-between text-xs text-on-surface-variant mb-1">
          <span>{t("page:result.mapperProgress")}</span>
          <span className="font-medium text-on-surface">{clamped}%</span>
        </div>
        <div className="h-2 bg-surface-container-high rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-600 rounded-full transition-all duration-500"
            style={{ width: `${clamped}%` }}
            data-oid="mapper-progress-fill"
          />
        </div>
      </div>
    </div>
  );
}
