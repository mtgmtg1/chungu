// [Flow: Step 1 (분류된 노드 목록 수신) -> Step 2 (주장/증거 섹션 분리 렌더링)
//       -> Step 3 (카드 클릭 시 상세 패널 콜백 호출) -> Step 4 (쟁점 필터 디밍 적용)]
// 재판정 레이아웃의 좌(원고) / 우(피고) 컬럼을 담당하는 스크롤 가능 노드 카드 리스트.

import { useTranslation } from "react-i18next";
import { AlertTriangle, FileText, MessageSquare, Scale } from "lucide-react";

/**
 * CourtroomColumn — 원고 또는 피고 측의 주장과 증거를 스크롤 가능한 카드 리스트로 표시.
 *
 * @param {Object} props
 * @param {string} props.side - "plaintiff" | "defendant"
 * @param {string} [props.headerKey] - 컬럼 헤더에 사용할 i18n 키 (기본값: side별 기본 키)
 * @param {Array<Object>} props.claims - 주장 노드 배열 (type: plaintiff/defendant)
 * @param {Array<Object>} props.evidence - 증거 노드 배열 (type: evidence)
 * @param {Function} props.onNodeClick - 카드 클릭 콜백 (node) => void
 */
export default function CourtroomColumn({ side, headerKey, claims, evidence, onNodeClick }) {
  const { t } = useTranslation();

  const isPlaintiff = side === "plaintiff";
  const defaultHeaderKey = isPlaintiff
    ? "page:result.ediscoveryCourtroomPlaintiff"
    : "page:result.ediscoveryCourtroomDefendant";
  const resolvedHeaderKey = headerKey || defaultHeaderKey;
  const headerColor = isPlaintiff ? "text-blue-700" : "text-amber-700";
  const headerBg = isPlaintiff ? "bg-blue-50" : "bg-amber-50";
  const headerBorder = isPlaintiff ? "border-blue-200" : "border-amber-200";
  const accentBar = isPlaintiff ? "bg-blue-500" : "bg-amber-500";

  return (
    <div className="h-full flex flex-col min-h-0" data-oid={`courtroom-column-${side}`}>
      {/* 컬럼 헤더 — 주체명 */}
      <div className={`flex items-center gap-2 px-3 py-2 border-b ${headerBorder} ${headerBg} flex-shrink-0`}>
        <Scale size={14} className={headerColor} />
        <span className={`text-sm font-bold ${headerColor}`}>{t(resolvedHeaderKey)}</span>
        <span className="ml-auto text-[10px] text-on-surface-variant">
          {claims.length + evidence.length}건
        </span>
      </div>

      {/* 스크롤 가능 본문 */}
      <div className="flex-1 overflow-y-auto px-2 py-2 flex flex-col gap-3 min-h-0">
        {/* 주장 섹션 */}
        {claims.length > 0 && (
          <Section
            title={t("page:result.ediscoveryCourtroomClaims")}
            icon={<MessageSquare size={11} />}
            accentBar={accentBar}
          >
            {claims.map((node) => (
              <NodeCard
                key={node.id}
                node={node}
                side={side}
                category="claim"
                onClick={() => onNodeClick(node)}
              />
            ))}
          </Section>
        )}

        {/* 증거 · 증인 섹션 */}
        {evidence.length > 0 && (
          <Section
            title={t("page:result.ediscoveryCourtroomEvidence")}
            icon={<FileText size={11} />}
            accentBar={accentBar}
          >
            {evidence.map((node) => (
              <NodeCard
                key={node.id}
                node={node}
                side={side}
                category="evidence"
                onClick={() => onNodeClick(node)}
              />
            ))}
          </Section>
        )}

        {/* 빈 상태 */}
        {claims.length === 0 && evidence.length === 0 && (
          <div className="flex items-center justify-center h-20 text-xs text-on-surface-variant">
            데이터 없음
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Section — 섹션 제목 + 카드 리스트 래퍼.
 *
 * @param {Object} props
 * @param {string} props.title - 섹션 제목
 * @param {React.ReactNode} props.icon - 섹션 아이콘
 * @param {string} props.accentBar - 상단 강조바 CSS 클래스
 * @param {React.ReactNode} props.children - 카드 리스트
 */
function Section({ title, icon, accentBar, children }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-1.5 px-1">
        <span className={`inline-block w-1 h-3 rounded-full ${accentBar}`} />
        <span className="text-[10px] font-bold uppercase tracking-wide text-on-surface-variant flex items-center gap-1">
          {icon}
          {title}
        </span>
      </div>
      <div className="flex flex-col gap-1.5">{children}</div>
    </div>
  );
}

/**
 * NodeCard — 개별 노드 카드. 클릭 시 상세 패널 열기.
 *
 * @param {Object} props
 * @param {Object} props.node - 노드 데이터
 * @param {string} props.side - "plaintiff" | "defendant"
 * @param {string} props.category - "claim" | "evidence"
 * @param {Function} props.onClick - 클릭 콜백
 */
function NodeCard({ node, side, category, onClick }) {
  const data = node.data || {};
  const dimmed = data.dimmed;
  const hasAnomaly = data.anomalyEdgeIds?.length > 0;

  const isPlaintiff = side === "plaintiff";
  const cardBorder = category === "evidence"
    ? (isPlaintiff ? "border-l-blue-400" : "border-l-amber-400")
    : (isPlaintiff ? "border-l-blue-500" : "border-l-amber-500");

  return (
    <button
      onClick={onClick}
      className={`text-left w-full bg-surface-container-lowest border border-outline-variant border-l-2 ${cardBorder} rounded-r-lg px-2.5 py-2 hover:shadow-sm transition-all ${
        dimmed ? "opacity-25 grayscale" : "opacity-100"
      }`}
      style={{ transition: "opacity 300ms, filter 300ms" }}
      data-oid={`courtroom-card-${node.id}`}
    >
      <div className="flex items-start gap-1.5">
        {hasAnomaly && (
          <AlertTriangle size={12} className="text-red-600 flex-shrink-0 mt-0.5" />
        )}
        <div className="flex-1 min-w-0">
          <p className="text-[11px] font-medium text-on-surface leading-snug line-clamp-3">
            {data.label || node.id}
          </p>
          <div className="flex items-center gap-1.5 mt-1 text-[10px] text-on-surface-variant">
            {data.date && <span>{data.date}</span>}
            {data.page != null && <span>· p.{data.page}</span>}
          </div>
        </div>
      </div>
    </button>
  );
}
