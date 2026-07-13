// [Flow: Step 1 (e-Discovery 그래프에서 evidence 노드 추출) -> Step 2 (claim_type 입력 + 3단계 트리 API 호출)
//       -> Step 3 (DndContext + closestCenter로 드래그 앤 드롭 인프라 설정) -> Step 4 (드롭 시 주장 슬롯에 근거 append + reason 필드 포함)
//       -> Step 5 (overall_progress_percent 계산 + ProgressBadge 시각화) -> Step 6 (PUT /legal-issue-tree/mappings로 영속화)]
// 쟁점(Issue) → 주장(Claim) → 근거(Evidence) 3단계 트리 매퍼 메인 패널.
// 쟁점을 부모, 주장을 자식, 근거를 손자로 하여 계층 UI로 구분한다.
// LLM이 문서를 교차검증하며 쟁점-주장-근거 연결고리를 파악한다.
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { Loader2, Play, AlertCircle, Puzzle, Network, Scale, CheckCircle2 } from "lucide-react";
import { api } from "../../api.js";
import EvidenceDraggableCard from "./EvidenceDraggableCard.jsx";
import ProgressBadge from "./ProgressBadge.jsx";
import IssueTreeView from "./IssueTreeView.jsx";

/**
 * IssueTreeMapperPanel — 3단계 트리 매퍼. DndContext 최상단 래퍼.
 *
 * @param {Object} props
 * @param {string} props.jobId - Job ID
 * @param {Object} props.job - Job 객체 (ediscovery_graphs, issue_tree 포함)
 */
export default function IssueTreeMapperPanel({ jobId, job }) {
  const { t } = useTranslation();
  const [claimType, setClaimType] = useState("");
  const [tree, setTree] = useState({
    claim_type: "",
    overall_progress_percent: 0,
    cross_validated: false,
    issues: [],
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  // e-Discovery 그래프에서 evidence 노드만 추출 (드래그 소스)
  const evidenceNodes = useMemo(() => {
    const graph = job?.ediscovery_graphs || {};
    const nodes = graph.nodes || [];
    return nodes.filter((n) => n.type === "evidence");
  }, [job?.ediscovery_graphs]);

  // 이미 매핑된 증거 ID 집합 (드래그 비활성화용)
  const mappedEvidenceIds = useMemo(() => {
    const ids = new Set();
    for (const issue of tree.issues) {
      for (const claim of issue.claims || []) {
        for (const ev of claim.mapped_evidence || []) {
          ids.add(ev.evidence_id);
        }
      }
    }
    return ids;
  }, [tree.issues]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  // [Flow: Step 1 (저장된 issue_tree 로드) -> Step 2 (claim_type 복원)]
  const loadSavedTree = useCallback(async () => {
    try {
      const data = await api.getIssueTreeMappings(jobId);
      if (data?.issue_tree?.issues?.length > 0) {
        setTree(data.issue_tree);
        setClaimType(data.issue_tree.claim_type || "");
      }
    } catch (err) {
      // 저장된 트리가 없으면 무시 (빈 상태)
    }
  }, [jobId]);

  useEffect(() => {
    loadSavedTree();
  }, [loadSavedTree]);

  // [Flow: Step 1 (claim_type 입력 검증) -> Step 2 (GET /legal-issue-tree API 호출) -> Step 3 (3단계 트리로 tree 갱신)]
  const handleExtractTree = async () => {
    const trimmed = claimType.trim();
    if (!trimmed) return;
    setLoading(true);
    setError("");
    try {
      const data = await api.getLegalIssueTree(jobId, trimmed);
      if (data?.issue_tree) {
        setTree(data.issue_tree);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  // [Flow: Step 1 (overall_progress_percent 재계산) -> Step 2 (PUT /legal-issue-tree/mappings API 호출) -> Step 3 (저장 상태 피드백)]
  const persistTree = useCallback(async (nextTree) => {
    setSaving(true);
    try {
      await api.saveIssueTreeMappings(jobId, nextTree);
    } catch (err) {
      console.error("[issue-tree] save failed:", err);
    } finally {
      setSaving(false);
    }
  }, [jobId]);

  // [Flow: Step 1 (전체 주장 중 1개 이상 근거 매핑된 주장 비율 계산) -> Step 2 (tree 갱신 + 영속화)]
  const recomputeProgress = (issues) => {
    let totalClaims = 0;
    let filledClaims = 0;
    for (const issue of issues || []) {
      for (const claim of issue.claims || []) {
        totalClaims += 1;
        if ((claim.mapped_evidence || []).length > 0) filledClaims += 1;
      }
    }
    if (totalClaims === 0) return 0;
    return Math.round((filledClaims / totalClaims) * 100);
  };

  // [Flow: Step 1 (드래그 소스/드롭 대상 식별) -> Step 2 (해당 주장 슬롯에 근거 append + reason 필드 포함) -> Step 3 (progress 재계산 + 영속화)]
  const handleDragEnd = (event) => {
    const { active, over } = event;
    if (!over) return;
    const evidence = active.data?.current?.evidence;
    const claimId = over.data?.current?.claimId;
    if (!evidence || !claimId) return;

    setTree((prev) => {
      const issues = prev.issues.map((issue) => ({
        ...issue,
        claims: (issue.claims || []).map((claim) => {
          if (claim.id !== claimId) return claim;
          const exists = (claim.mapped_evidence || []).some((ev) => ev.evidence_id === evidence.id);
          if (exists) return claim;
          return {
            ...claim,
            mapped_evidence: [
              ...(claim.mapped_evidence || []),
              {
                evidence_id: evidence.id,
                text_snippet: evidence.data?.label || evidence.label || "",
                source_doc: evidence.data?.page ? `P.${evidence.data.page}` : "",
                reason: "",
              },
            ],
          };
        }),
      }));
      const next = {
        ...prev,
        claim_type: prev.claim_type || claimType.trim(),
        issues,
        overall_progress_percent: recomputeProgress(issues),
      };
      persistTree(next);
      return next;
    });
  };

  // [Flow: Step 1 (issue/claim/evidence ID로 해당 매핑 제거) -> Step 2 (progress 재계산 + 영속화)]
  const handleRemoveEvidence = (claimId, evidenceId) => {
    setTree((prev) => {
      const issues = prev.issues.map((issue) => ({
        ...issue,
        claims: (issue.claims || []).map((claim) => {
          if (claim.id !== claimId) return claim;
          return {
            ...claim,
            mapped_evidence: (claim.mapped_evidence || []).filter((ev) => ev.evidence_id !== evidenceId),
          };
        }),
      }));
      const next = {
        ...prev,
        issues,
        overall_progress_percent: recomputeProgress(issues),
      };
      persistTree(next);
      return next;
    });
  };

  const hasIssues = tree.issues.length > 0;
  const hasEvidence = evidenceNodes.length > 0;

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <div className="h-full flex flex-col" data-oid="issue-tree-panel">
        {/* 헤더: claim_type 입력 + 3단계 트리 추출 버튼 */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-outline-variant bg-surface-container-lowest flex-shrink-0">
          <Scale size={16} className="text-primary flex-shrink-0" />
          <span className="text-sm font-medium text-on-surface flex-shrink-0">
            {t("page:result.issueTreeTitle")}
          </span>
          {tree.cross_validated && (
            <span className="flex items-center gap-1 text-[10px] font-medium text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded-full">
              <CheckCircle2 size={10} />
              {t("page:result.issueTreeCrossValidated")}
            </span>
          )}
          <div className="flex items-center gap-1.5 ml-auto flex-shrink-0">
            <input
              type="text"
              value={claimType}
              onChange={(e) => setClaimType(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleExtractTree()}
              placeholder={t("page:result.mapperClaimTypePlaceholder")}
              disabled={loading}
              className="text-xs px-2 py-1.5 rounded-lg border border-outline-variant bg-surface text-on-surface focus:outline-none focus:ring-1 focus:ring-primary w-[160px]"
              data-oid="issue-tree-claim-input"
            />
            <button
              onClick={handleExtractTree}
              disabled={loading || !claimType.trim()}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white text-xs font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
              data-oid="issue-tree-extract-btn"
            >
              {loading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              {loading ? t("page:result.mapperExtracting") : t("page:result.issueTreeExtract")}
            </button>
          </div>
        </div>

        {/* 입증 달성도 */}
        {hasIssues && (
          <div className="px-3 py-2 border-b border-outline-variant bg-surface-container-low flex-shrink-0">
            <ProgressBadge percent={tree.overall_progress_percent} />
            {saving && (
              <span className="text-[10px] text-on-surface-variant ml-2">
                {t("page:result.mapperSaving")}
              </span>
            )}
          </div>
        )}

        {/* 에러 메시지 */}
        {error && (
          <div className="mx-3 my-2 bg-error-container border border-error text-on-error-container px-3 py-2 rounded-lg flex items-start gap-2 text-xs flex-shrink-0" data-oid="issue-tree-error">
            <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {/* 본문: 좌측 증거 카드 리스트 + 우측 3단계 트리 */}
        <div className="flex-1 min-h-0 flex flex-col md:flex-row gap-2 p-2 overflow-hidden">
          {/* 좌측: 추출된 증거 카드 리스트 (드래그 소스) */}
          <div className="md:w-[280px] flex-shrink-0 flex flex-col min-h-0 border border-outline-variant rounded-lg bg-surface-container-lowest">
            <div className="px-3 py-2 border-b border-outline-variant text-xs font-medium text-on-surface flex items-center gap-1.5 flex-shrink-0">
              <Network size={12} className="text-emerald-600" />
              {t("page:result.mapperEvidenceList")}
              <span className="ml-auto text-on-surface-variant">{evidenceNodes.length}</span>
            </div>
            <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-1.5">
              {!hasEvidence ? (
                <p className="text-xs text-on-surface-variant text-center py-6 px-2">
                  {t("page:result.mapperEmptyEvidence")}
                </p>
              ) : (
                evidenceNodes.map((node) => (
                  <EvidenceDraggableCard
                    key={node.id}
                    evidence={{
                      id: node.id,
                      label: node.data?.label || "",
                      page: node.data?.page,
                      summary: node.data?.summary,
                    }}
                    disabled={mappedEvidenceIds.has(node.id)}
                  />
                ))
              )}
            </div>
          </div>

          {/* 우측: 3단계 트리 뷰 */}
          <div className="flex-1 min-h-0 flex flex-col">
            {!hasIssues ? (
              <div className="flex-1 flex flex-col items-center justify-center text-on-surface-variant gap-2" data-oid="issue-tree-empty">
                <Puzzle size={32} className="text-primary/40" />
                <p className="text-xs text-center max-w-xs px-4">
                  {t("page:result.issueTreeEmpty")}
                </p>
              </div>
            ) : (
              <IssueTreeView issues={tree.issues} onRemoveEvidence={handleRemoveEvidence} />
            )}
          </div>
        </div>
      </div>
    </DndContext>
  );
}
