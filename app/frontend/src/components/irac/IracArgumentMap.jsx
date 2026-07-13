// [Flow: Step 1 (Job ID 수신) -> Step 2 (저장된 issue_tree 로드) -> Step 3 (트리가 없으면 claim_type 입력 UI)
//       -> Step 4 (추출 시 getLegalIssueTree 호출) -> Step 5 (이슈별로 원고/피고 주장 분류)
//       -> Step 6 (3열 행렬 렌더링: 좌측 원고, 중앙 다툼의 지점, 우측 피고)
//       -> Step 7 (증거/주장/쟁점 클릭 시 우측 슬라이드 인 상세 패널) -> Step 8 (원본 PDF 보기 버튼으로 onNodeClick 호출)]
// JobResultPage의 IRAC 뷰 모드에서 사용하는 adversarial argument map 컴포넌트.
// /legal-issue-tree API의 쟁점-주장-근거 트리를 좌우 공방 행렬로 시각화한다.
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  AlertCircle,
  CheckCircle2,
  Eye,
  FileText,
  Loader2,
  Play,
  Scale,
  X,
} from "lucide-react";
import { api } from "../../api.js";
import ProgressBadge from "../mapper/ProgressBadge.jsx";

/**
 * Issue tree 데이터의 기본 형태.
 */
const EMPTY_TREE = {
  claim_type: "",
  overall_progress_percent: 0,
  cross_validated: false,
  issues: [],
};

/**
 * 원고/피고 키워드 분류.
 * party 문자열에 포함된 키워드로 좌우 컬럼을 결정한다.
 *
 * @param {string} party - "원고", "피고" 등 주체 문자열
 * @param {number} index - 분류 실패 시 fallback으로 사용할 인덱스
 * @returns {"plaintiff" | "defendant"}
 */
function classifyParty(party, index) {
  const p = String(party || "").toLowerCase();
  const plaintiffKeywords = [
    "원고", "검사", "의뢰인", "고소인", "원고인", "피해자",
    "plaintiff", "prosecutor", "petitioner", "client", "claimant", "appellant",
  ];
  const defendantKeywords = [
    "피고", "피고인", "상대방", "피의자", "피청구인",
    "defendant", "accused", "respondent", "opponent", "appellee",
  ];
  const isPlaintiff = plaintiffKeywords.some((k) => p.includes(k));
  const isDefendant = defendantKeywords.some((k) => p.includes(k));
  if (isPlaintiff && !isDefendant) return "plaintiff";
  if (isDefendant && !isPlaintiff) return "defendant";
  if (isPlaintiff && isDefendant) return "plaintiff";
  // 분류 불가 시 첫 번째 주장은 원고, 나머지는 피고로 fallback
  return index === 0 ? "plaintiff" : "defendant";
}

/**
 * 주장의 증거 개수에 따라 상태(Proven/Contested/Weak)와 색상을 결정한다.
 *
 * @param {Object} claim - issue_tree의 claim 객체
 * @param {Function} t - i18n translate 함수
 * @returns {{key: string, label: string, color: string}}
 */
function getClaimStatus(claim, t) {
  const count = (claim.mapped_evidence || []).length;
  if (count >= 2) {
    return {
      key: "proven",
      label: t("page:result.iracStatusProven"),
      color: "emerald",
    };
  }
  if (count === 1) {
    return {
      key: "contested",
      label: t("page:result.iracStatusContested"),
      color: "amber",
    };
  }
  return {
    key: "weak",
    label: t("page:result.iracStatusWeak"),
    color: "rose",
  };
}

/**
 * source_doc 문자열에서 페이지 번호를 추출한다.
 *
 * @param {string} sourceDoc - "P.5", "p.5", "Page 5" 등
 * @returns {number} 추출된 페이지 번호, 실패 시 0
 */
function parsePageFromSourceDoc(sourceDoc) {
  if (!sourceDoc) return 0;
  const match = String(sourceDoc).match(/\d+/);
  return match ? parseInt(match[0], 10) : 0;
}

/**
 * EvidenceCard — 단일 증거 항목을 카드 형태로 렌더링.
 *
 * @param {Object} props
 * @param {Object} props.evidence - { evidence_id, text_snippet, source_doc, reason }
 * @param {"plaintiff" | "defendant"} props.side - 어느 측 증거인지
 * @param {Function} props.onClick - 클릭 콜백
 */
function EvidenceCard({ evidence, side, onClick }) {
  const isPlaintiff = side === "plaintiff";
  const iconBg = isPlaintiff ? "bg-primary-fixed-dim" : "bg-secondary-container";
  const iconColor = isPlaintiff ? "text-primary" : "text-on-secondary-container";
  const badgeColor = isPlaintiff
    ? "text-emerald-600 bg-emerald-50 border-emerald-100"
    : "text-amber-600 bg-amber-50 border-amber-100";
  const code = evidence.evidence_id || "";
  const badgeText = evidence.source_doc || code.slice(0, 12) || "-";

  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onClick(evidence);
      }}
      className="w-full flex items-center justify-between bg-surface-container-low p-2 rounded border border-outline-variant hover:border-primary cursor-pointer transition-colors text-left"
      data-oid="irac-evidence-card"
    >
      <div className="flex items-center gap-2 min-w-0">
        <div className={`w-6 h-6 rounded ${iconBg} flex items-center justify-center ${iconColor} flex-shrink-0`}>
          <FileText size={14} />
        </div>
        <div className="flex flex-col min-w-0">
          <span className="font-mono text-[10px] text-on-surface truncate max-w-[120px]">
            {code.length > 24 ? `${code.slice(0, 24)}…` : code}
          </span>
          <span className="text-[11px] text-on-surface-variant line-clamp-2 leading-snug">
            {evidence.text_snippet || "-"}
          </span>
        </div>
      </div>
      <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border ${badgeColor} flex-shrink-0 ml-1`}>
        {badgeText}
      </span>
    </button>
  );
}

/**
 * ClaimCard — 단일 주장 카드. 상태 뱃지, 설명, 증거 리스트를 포함.
 *
 * @param {Object} props
 * @param {Object} props.claim - issue_tree의 claim 객체
 * @param {"plaintiff" | "defendant"} props.side - 좌우 구분
 * @param {Function} props.onClaimClick - 주장 클릭 콜백
 * @param {Function} props.onEvidenceClick - 증거 클릭 콜백
 * @param {Function} props.t - i18n translate
 */
function ClaimCard({ claim, side, onClaimClick, onEvidenceClick, t }) {
  const isPlaintiff = side === "plaintiff";
  const status = getClaimStatus(claim, t);
  const evidence = claim.mapped_evidence || [];
  const headerColor = isPlaintiff ? "text-primary" : "text-secondary";
  const borderColor = isPlaintiff ? "border-l-blue-400" : "border-l-amber-400";

  return (
    <div
      className={`bg-surface-container-low p-3 rounded-lg border border-outline-variant border-l-4 ${borderColor} flex flex-col gap-2`}
      data-oid="irac-claim-card"
    >
      <button
        onClick={() => onClaimClick(claim)}
        className="w-full text-left flex flex-col gap-1 group"
        data-oid="irac-claim-header"
      >
        <div className="flex items-center justify-between gap-2">
          <h4 className={`text-[10px] font-bold uppercase tracking-wide ${headerColor}`}>
            {claim.party || (isPlaintiff ? t("page:result.iracPlaintiff") : t("page:result.iracDefendant"))}
          </h4>
          <span className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium border bg-${status.color}-100 text-${status.color}-800 border-${status.color}-200`}>
            <span className={`w-1.5 h-1.5 rounded-full bg-${status.color}-500`} />
            {status.label}
          </span>
        </div>
        <p className="text-sm font-semibold text-on-surface leading-snug group-hover:text-primary transition-colors">
          {claim.name}
        </p>
        {claim.description ? (
          <p className="text-xs text-on-surface-variant line-clamp-3">
            {claim.description}
          </p>
        ) : null}
      </button>

      <div className="flex flex-col gap-1.5 mt-1">
        <h5 className="text-[10px] font-bold uppercase tracking-wide text-on-surface-variant">
          {t("page:result.iracEvidence")}
        </h5>
        {evidence.length === 0 ? (
          <p className="text-[10px] text-on-surface-variant text-center py-2 border border-dashed border-outline-variant rounded">
            {t("page:result.iracNoEvidence")}
          </p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {evidence.map((ev) => (
              <EvidenceCard
                key={ev.evidence_id || ev.text_snippet}
                evidence={ev}
                side={side}
                onClick={() => onEvidenceClick(ev, claim)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * ClaimColumn — 한쪽(plaintiff/defendant)의 주장 카드들을 렌더링.
 *
 * @param {Object} props
 * @param {Array} props.claims - claim 객체 배열
 * @param {"plaintiff" | "defendant"} props.side - 측
 * @param {Function} props.onClaimClick - 주장 클릭
 * @param {Function} props.onEvidenceClick - 증거 클릭
 * @param {Function} props.t - i18n translate
 */
function ClaimColumn({ claims, side, onClaimClick, onEvidenceClick, t }) {
  const isPlaintiff = side === "plaintiff";
  const headerColor = isPlaintiff ? "text-primary" : "text-secondary";

  return (
    <div className="p-4 bg-surface-container-lowest flex flex-col" data-oid={`irac-column-${side}`}>
      <div className="flex items-center justify-between mb-3">
        <h4 className={`text-[10px] font-bold uppercase tracking-wide ${headerColor}`}>
          {isPlaintiff ? t("page:result.iracPlaintiff") : t("page:result.iracDefendant")}
        </h4>
        <span className="text-[10px] text-on-surface-variant">{claims.length}</span>
      </div>
      <div className="flex flex-col gap-3">
        {claims.length === 0 ? (
          <p className="text-xs text-on-surface-variant text-center py-6">
            {t("page:result.iracNoClaims")}
          </p>
        ) : (
          claims.map((claim) => (
            <ClaimCard
              key={claim.id}
              claim={claim}
              side={side}
              onClaimClick={onClaimClick}
              onEvidenceClick={onEvidenceClick}
              t={t}
            />
          ))
        )}
      </div>
    </div>
  );
}

/**
 * IssueRow — 단일 쟁점을 3열 행렬(원고 / 다툼의 지점 / 피고)로 렌더링.
 *
 * @param {Object} props
 * @param {Object} props.issue - issue 객체
 * @param {number} props.index - 1-based 인덱스
 * @param {Function} props.onIssueClick - 쟁점 클릭
 * @param {Function} props.onClaimClick - 주장 클릭
 * @param {Function} props.onEvidenceClick - 증거 클릭
 * @param {Function} props.t - i18n translate
 */
function IssueRow({ issue, index, onIssueClick, onClaimClick, onEvidenceClick, t }) {
  const resolved = (issue.claims || []).map((claim, idx) => ({
    ...claim,
    __side: classifyParty(claim.party, idx),
  }));
  const plaintiffClaims = resolved.filter((c) => c.__side === "plaintiff");
  const defendantClaims = resolved.filter((c) => c.__side === "defendant");
  const contention = issue.description || issue.name || t("page:result.iracContentionEmpty");

  return (
    <div
      className="bg-surface rounded-xl border border-outline-variant shadow-sm overflow-hidden flex flex-col transition-shadow hover:shadow-md"
      data-oid="irac-issue-row"
    >
      <button
        onClick={() => onIssueClick(issue)}
        className="px-4 py-3 bg-surface-container border-b border-outline-variant flex items-center gap-2 text-left w-full group"
        data-oid="irac-issue-header"
      >
        <Scale size={16} className="text-primary flex-shrink-0" />
        <h3 className="text-sm font-bold text-on-surface group-hover:text-primary transition-colors">
          {t("page:result.iracSubIssue", { index, name: issue.name })}
        </h3>
      </button>

      <div className="p-0 grid grid-cols-1 lg:grid-cols-3 divide-y lg:divide-y-0 lg:divide-x divide-outline-variant">
        <ClaimColumn
          claims={plaintiffClaims}
          side="plaintiff"
          onClaimClick={(claim) => onClaimClick(claim, issue)}
          onEvidenceClick={(evidence, claim) => onEvidenceClick(evidence, claim, issue)}
          t={t}
        />

        <div className="p-4 bg-surface-container-low flex flex-col items-center text-center relative justify-center min-h-[120px]">
          <div className="absolute inset-y-0 w-px bg-outline-variant/30 left-1/2 -translate-x-1/2 hidden lg:block" />
          <div className="relative z-10 flex flex-col items-center w-full">
            <Scale size={16} className="text-on-surface-variant mb-2" />
            <h4 className="text-[10px] font-bold uppercase tracking-wide text-on-surface-variant mb-2">
              {t("page:result.iracContention")}
            </h4>
            <p className="text-xs text-on-surface bg-surface p-2 rounded border border-outline-variant shadow-sm w-full">
              {contention}
            </p>
          </div>
        </div>

        <ClaimColumn
          claims={defendantClaims}
          side="defendant"
          onClaimClick={(claim) => onClaimClick(claim, issue)}
          onEvidenceClick={(evidence, claim) => onEvidenceClick(evidence, claim, issue)}
          t={t}
        />
      </div>
    </div>
  );
}

/**
 * DetailPanel — 선택된 쟁점/주장/증거의 상세 정보를 우측 슬라이드 인으로 표시.
 *
 * @param {Object} props
 * @param {Object|null} props.selected - { type, issue?, claim?, evidence?, nodeData? }
 * @param {Function} props.onClose - 닫기 콜백
 * @param {Function} props.onViewSource - 원본 PDF 보기 콜백
 * @param {Function} props.t - i18n translate
 */
function DetailPanel({ selected, onClose, onViewSource, t }) {
  const isOpen = !!selected;

  const renderContent = () => {
    if (!selected) {
      return (
        <div className="flex-1 flex flex-col items-center justify-center text-on-surface-variant gap-2 px-6 text-center">
          <Scale size={32} className="text-primary/30" />
          <p className="text-xs">{t("page:result.iracDetailSelect")}</p>
        </div>
      );
    }

    if (selected.type === "evidence") {
      const ev = selected.evidence;
      const nodeData = selected.nodeData;
      const canViewSource = !!nodeData?.page;
      return (
        <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3" data-oid="irac-detail-evidence">
          <div className="flex items-start justify-between gap-2">
            <span className="text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded bg-primary text-on-primary">
              {t("page:result.iracEvidenceLabel")}
            </span>
            <button
              onClick={onClose}
              className="p-1 hover:bg-surface-container-high rounded text-on-surface-variant"
              aria-label={t("page:result.ediscoveryClose")}
            >
              <X size={14} />
            </button>
          </div>
          <h3 className="text-sm font-bold text-on-surface">{ev.text_snippet || ev.evidence_id}</h3>
          <div className="grid grid-cols-[auto_1fr] gap-y-2 gap-x-3 text-xs">
            <span className="text-on-surface-variant">{t("page:result.iracId")}</span>
            <span className="text-on-surface font-mono break-all">{ev.evidence_id}</span>
            <span className="text-on-surface-variant">{t("page:result.ediscoveryPage")}</span>
            <span className="text-on-surface">{ev.source_doc || nodeData?.page || "-"}</span>
          </div>
          {ev.reason ? (
            <div className="bg-surface-container-low rounded-lg p-3 border border-outline-variant">
              <h4 className="text-[10px] font-bold uppercase tracking-wide text-on-surface-variant mb-1">
                {t("page:result.mapperReason")}
              </h4>
              <p className="text-xs text-on-surface leading-relaxed">{ev.reason}</p>
            </div>
          ) : null}
          {canViewSource && (
            <button
              onClick={onViewSource}
              className="mt-auto flex items-center justify-center gap-1.5 px-3 py-2 bg-primary text-on-primary rounded-lg text-xs font-medium hover:opacity-90 transition-opacity"
            >
              <Eye size={14} />
              {t("page:result.ediscoveryViewSource")}
            </button>
          )}
        </div>
      );
    }

    if (selected.type === "claim") {
      const claim = selected.claim;
      return (
        <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3" data-oid="irac-detail-claim">
          <div className="flex items-start justify-between gap-2">
            <span className="text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded bg-secondary text-on-secondary">
              {t("page:result.iracClaimLabel")}
            </span>
            <button
              onClick={onClose}
              className="p-1 hover:bg-surface-container-high rounded text-on-surface-variant"
              aria-label={t("page:result.ediscoveryClose")}
            >
              <X size={14} />
            </button>
          </div>
          <h3 className="text-sm font-bold text-on-surface">{claim.name}</h3>
          <p className="text-xs text-on-surface-variant">{claim.description || "-"}</p>
          <div className="bg-surface-container-low rounded-lg p-3 border border-outline-variant text-xs">
            <span className="text-on-surface-variant">{t("page:result.iracEvidenceCount")}</span>
            <span className="ml-2 font-semibold text-on-surface">{(claim.mapped_evidence || []).length}</span>
          </div>
        </div>
      );
    }

    if (selected.type === "issue") {
      const issue = selected.issue;
      return (
        <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-3" data-oid="irac-detail-issue">
          <div className="flex items-start justify-between gap-2">
            <span className="text-[10px] font-bold uppercase tracking-wide px-2 py-0.5 rounded bg-error text-on-error">
              {t("page:result.iracIssueLabel")}
            </span>
            <button
              onClick={onClose}
              className="p-1 hover:bg-surface-container-high rounded text-on-surface-variant"
              aria-label={t("page:result.ediscoveryClose")}
            >
              <X size={14} />
            </button>
          </div>
          <h3 className="text-sm font-bold text-on-surface">{issue.name}</h3>
          <p className="text-xs text-on-surface-variant">{issue.description || "-"}</p>
          <div className="bg-surface-container-low rounded-lg p-3 border border-outline-variant text-xs">
            <span className="text-on-surface-variant">{t("page:result.iracClaimCount")}</span>
            <span className="ml-2 font-semibold text-on-surface">{(issue.claims || []).length}</span>
          </div>
        </div>
      );
    }

    return null;
  };

  return (
    <div
      className={`absolute top-0 right-0 h-full w-full sm:w-80 bg-surface border-l border-outline-variant shadow-2xl z-30 transform transition-transform duration-300 flex flex-col ${
        isOpen ? "translate-x-0" : "translate-x-full"
      }`}
      data-oid="irac-detail-panel"
    >
      <div className="p-3 border-b border-outline-variant bg-surface-container-lowest flex items-center justify-between flex-shrink-0">
        <h2 className="text-sm font-bold text-on-surface">{t("page:result.iracDetailTitle")}</h2>
        <button
          onClick={onClose}
          className="p-1 hover:bg-surface-container-high rounded text-on-surface-variant"
          aria-label={t("page:result.ediscoveryClose")}
        >
          <X size={16} />
        </button>
      </div>
      {renderContent()}
    </div>
  );
}

/**
 * IracArgumentMap — IRAC argument map 메인 컴포넌트.
 *
 * @param {Object} props
 * @param {string} props.jobId - Job ID
 * @param {Object} props.job - Job 객체 (ediscovery_graphs 포함)
 * @param {Function} [props.onNodeClick] - 원본 PDF 스크롤 콜백 (node) => void
 */
export default function IracArgumentMap({ jobId, job, onNodeClick }) {
  const { t } = useTranslation();
  const [claimType, setClaimType] = useState("");
  const [tree, setTree] = useState(EMPTY_TREE);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);

  // e-Discovery graph에서 evidence_id로 노드를 찾기 위한 맵
  const evidenceById = useMemo(() => {
    const graph = job?.ediscovery_graphs || {};
    const nodes = (graph.nodes || []).filter((n) => n.type === "evidence");
    const map = new Map();
    for (const node of nodes) map.set(node.id, node);
    return map;
  }, [job?.ediscovery_graphs]);

  /**
   * [Flow: Step 1 (evidence_id로 e-Discovery 노드 조회) -> Step 2 (page/source_file 추출)
   *       -> Step 3 (노드가 없으면 source_doc에서 페이지 파싱) -> Step 4 (onNodeClick용 nodeData 반환)]
   */
  const resolveEvidenceNodeData = useCallback(
    (evidence) => {
      const node = evidenceById.get(evidence.evidence_id);
      if (node) {
        const d = node.data || {};
        const page = d.original_page || d.page || 0;
        return { page, original_page: page, source_file: d.source_file || "" };
      }
      const page = parsePageFromSourceDoc(evidence.source_doc);
      return { page, original_page: page, source_file: "" };
    },
    [evidenceById]
  );

  /**
   * [Flow: Step 1 (저장된 issue_tree 조회) -> Step 2 (claim_type 입력란 복원)]
   */
  const loadSavedTree = useCallback(async () => {
    try {
      const data = await api.getIssueTreeMappings(jobId);
      const saved = data?.issue_tree;
      if (saved?.issues?.length > 0) {
        setTree(saved);
        setClaimType(saved.claim_type || "");
      }
    } catch (err) {
      // 저장된 트리가 없으면 무시
    }
  }, [jobId]);

  useEffect(() => {
    loadSavedTree();
  }, [loadSavedTree]);

  /**
   * [Flow: Step 1 (claim_type 입력 검증) -> Step 2 (getLegalIssueTree 호출) -> Step 3 (tree 상태 갱신)]
   */
  const handleExtract = async () => {
    const trimmed = claimType.trim();
    if (!trimmed) return;
    setLoading(true);
    setError("");
    try {
      const data = await api.getLegalIssueTree(jobId, trimmed);
      if (data?.issue_tree) {
        setTree(data.issue_tree);
        setClaimType(data.issue_tree.claim_type || trimmed);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleIssueClick = (issue) => {
    setSelected({ type: "issue", issue });
  };

  const handleClaimClick = (claim, issue) => {
    setSelected({ type: "claim", claim, issue });
  };

  const handleEvidenceClick = (evidence, claim, issue) => {
    const nodeData = resolveEvidenceNodeData(evidence);
    setSelected({ type: "evidence", evidence, claim, issue, nodeData });
  };

  const handleViewSource = () => {
    if (!selected?.nodeData?.page || !onNodeClick) return;
    onNodeClick({ data: selected.nodeData });
  };

  const hasIssues = tree.issues.length > 0;

  return (
    <div className="h-full flex flex-col" data-oid="irac-panel">
      {/* 헤더: 제목 + claim_type 입력 + 추출 버튼 + 진행도 */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-outline-variant bg-surface-container-lowest flex-shrink-0 flex-wrap">
        <Scale size={16} className="text-primary flex-shrink-0" />
        <span className="text-sm font-medium text-on-surface flex-shrink-0">
          {t("page:result.iracTitle")}
        </span>
        {tree.cross_validated && (
          <span className="flex items-center gap-1 text-[10px] font-medium text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded-full">
            <CheckCircle2 size={10} />
            {t("page:result.issueTreeCrossValidated")}
          </span>
        )}
        <div className="flex items-center gap-2 ml-auto flex-shrink-0">
          {hasIssues && (
            <div className="hidden sm:flex items-center flex-shrink-0">
              <ProgressBadge percent={tree.overall_progress_percent} />
            </div>
          )}
          <div className="flex items-center gap-1.5 flex-shrink-0">
            <input
              type="text"
              value={claimType}
              onChange={(e) => setClaimType(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleExtract()}
              placeholder={t("page:result.iracClaimTypePlaceholder")}
              disabled={loading}
              className="text-xs px-2 py-1.5 rounded-lg border border-outline-variant bg-surface text-on-surface focus:outline-none focus:ring-1 focus:ring-primary w-[160px]"
              data-oid="irac-claim-input"
            />
            <button
              onClick={handleExtract}
              disabled={loading || !claimType.trim()}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white text-xs font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
              data-oid="irac-extract-btn"
            >
              {loading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              {loading ? t("page:result.mapperExtracting") : t("page:result.iracExtract")}
            </button>
          </div>
        </div>
      </div>

      {/* 에러 메시지 */}
      {error && (
        <div className="mx-3 my-2 bg-error-container border border-error text-on-error-container px-3 py-2 rounded-lg flex items-start gap-2 text-xs flex-shrink-0" data-oid="irac-error">
          <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* 본문 */}
      <div className="flex-1 relative overflow-hidden" data-oid="irac-main">
        {!hasIssues ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-on-surface-variant gap-2 p-6 text-center">
            <Scale size={32} className="text-primary/30" />
            <p className="text-xs max-w-xs">{t("page:result.iracEmpty")}</p>
          </div>
        ) : (
          <>
            <div className="absolute inset-0 overflow-y-auto p-4" data-oid="irac-scroll">
              <div className="max-w-6xl mx-auto flex flex-col gap-4 pb-4">
                {tree.issues.map((issue, idx) => (
                  <IssueRow
                    key={issue.id || `issue-${idx}`}
                    issue={issue}
                    index={idx + 1}
                    onIssueClick={handleIssueClick}
                    onClaimClick={handleClaimClick}
                    onEvidenceClick={handleEvidenceClick}
                    t={t}
                  />
                ))}
              </div>
            </div>
            <DetailPanel
              selected={selected}
              onClose={() => setSelected(null)}
              onViewSource={handleViewSource}
              t={t}
            />
          </>
        )}
      </div>
    </div>
  );
}
