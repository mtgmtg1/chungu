// [Flow: Step 1 (e-Discovery 그래프에서 evidence 노드 추출) -> Step 2 (claim_type 입력 + 요건사실 추출 API 호출)
//       -> Step 3 (DndContext + closestCenter로 드래그 앤 드롭 인프라 설정) -> Step 4 (드롭 시 요건 슬롯에 증거 append)
//       -> Step 5 (overall_progress_percent 계산 + ProgressBadge 시각화) -> Step 6 (PUT /mappings로 영속화)]
// 요건 사실 기반 증거 퍼즐 매퍼 메인 패널. 청구 원인별 법적 요건사실 슬롯에 증거를 드래그 앤 드롭으로 매핑.
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { Loader2, Play, AlertCircle, Puzzle, Network } from "lucide-react";
import { api } from "../../api.js";
import EvidenceDraggableCard from "./EvidenceDraggableCard.jsx";
import ElementDroppableSlots from "./ElementDroppableSlots.jsx";
import ProgressBadge from "./ProgressBadge.jsx";

/**
 * EvidenceMapperPanel — 요건사실 퍼즐 매퍼. DndContext 최상단 래퍼.
 *
 * @param {Object} props
 * @param {string} props.jobId - Job ID
 * @param {Object} props.job - Job 객체 (ediscovery_graphs, element_mappings 포함)
 */
export default function EvidenceMapperPanel({ jobId, job }) {
  const { t } = useTranslation();
  const [claimType, setClaimType] = useState("");
  const [mappings, setMappings] = useState({ claim_type: "", overall_progress_percent: 0, elements: [] });
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
    for (const el of mappings.elements) {
      for (const ev of el.mapped_evidence || []) {
        ids.add(ev.evidence_id);
      }
    }
    return ids;
  }, [mappings.elements]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
  );

  // [Flow: Step 1 (저장된 element_mappings 로드) -> Step 2 (claim_type 복원)]
  const loadSavedMappings = useCallback(async () => {
    try {
      const data = await api.getElementMappings(jobId);
      if (data?.element_mappings?.elements?.length > 0) {
        setMappings(data.element_mappings);
        setClaimType(data.element_mappings.claim_type || "");
      }
    } catch (err) {
      // 저장된 매핑이 없으면 무시 (빈 상태)
    }
  }, [jobId]);

  useEffect(() => {
    loadSavedMappings();
  }, [loadSavedMappings]);

  // [Flow: Step 1 (claim_type 입력 검증) -> Step 2 (GET /legal-elements API 호출) -> Step 3 (응답으로 mappings 갱신)]
  const handleExtractElements = async () => {
    const trimmed = claimType.trim();
    if (!trimmed) return;
    setLoading(true);
    setError("");
    try {
      const data = await api.getLegalElements(jobId, trimmed);
      if (data?.element_mappings) {
        setMappings(data.element_mappings);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  // [Flow: Step 1 (overall_progress_percent 재계산) -> Step 2 (PUT /mappings API 호출) -> Step 3 (저장 상태 피드백)]
  const persistMappings = useCallback(async (nextMappings) => {
    setSaving(true);
    try {
      await api.saveElementMappings(jobId, nextMappings);
    } catch (err) {
      // 저장 실패는 무시하지 않고 콘솔 로깅 (UI는 낙관적 업데이트 유지)
      console.error("[mapper] save failed:", err);
    } finally {
      setSaving(false);
    }
  }, [jobId]);

  // [Flow: Step 1 (전체 요건 중 1개 이상 증거 매핑된 요건 비율 계산) -> Step 2 (mappings 갱신 + 영속화)]
  const recomputeProgress = (elements) => {
    if (!elements || elements.length === 0) return 0;
    const filled = elements.filter((el) => (el.mapped_evidence || []).length > 0).length;
    return Math.round((filled / elements.length) * 100);
  };

  // [Flow: Step 1 (드래그 소스/드롭 대상 식별) -> Step 2 (해당 요건 슬롯에 증거 append) -> Step 3 (progress 재계산 + 영속화)]
  const handleDragEnd = (event) => {
    const { active, over } = event;
    if (!over) return;
    const evidence = active.data?.current?.evidence;
    const elementId = over.data?.current?.elementId;
    if (!evidence || !elementId) return;

    setMappings((prev) => {
      const elements = prev.elements.map((el) => {
        if (el.id !== elementId) return el;
        // 중복 매핑 방지
        const exists = (el.mapped_evidence || []).some((ev) => ev.evidence_id === evidence.id);
        if (exists) return el;
        return {
          ...el,
          mapped_evidence: [
            ...(el.mapped_evidence || []),
            {
              evidence_id: evidence.id,
              text_snippet: evidence.data?.label || evidence.label || "",
              source_doc: evidence.data?.page ? `P.${evidence.data.page}` : "",
            },
          ],
        };
      });
      const next = {
        ...prev,
        claim_type: prev.claim_type || claimType.trim(),
        elements,
        overall_progress_percent: recomputeProgress(elements),
      };
      persistMappings(next);
      return next;
    });
  };

  // [Flow: Step 1 (요건/증거 ID로 해당 매핑 제거) -> Step 2 (progress 재계산 + 영속화)]
  const handleRemoveEvidence = (elementId, evidenceId) => {
    setMappings((prev) => {
      const elements = prev.elements.map((el) => {
        if (el.id !== elementId) return el;
        return {
          ...el,
          mapped_evidence: (el.mapped_evidence || []).filter((ev) => ev.evidence_id !== evidenceId),
        };
      });
      const next = {
        ...prev,
        elements,
        overall_progress_percent: recomputeProgress(elements),
      };
      persistMappings(next);
      return next;
    });
  };

  const hasElements = mappings.elements.length > 0;
  const hasEvidence = evidenceNodes.length > 0;

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <div className="h-full flex flex-col" data-oid="evidence-mapper-panel">
        {/* 헤더: claim_type 입력 + 요건사실 추출 버튼 */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-outline-variant bg-surface-container-lowest flex-shrink-0">
          <Puzzle size={16} className="text-primary flex-shrink-0" />
          <span className="text-sm font-medium text-on-surface flex-shrink-0">
            {t("page:result.mapperTitle")}
          </span>
          <div className="flex items-center gap-1.5 ml-auto flex-shrink-0">
            <input
              type="text"
              value={claimType}
              onChange={(e) => setClaimType(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleExtractElements()}
              placeholder={t("page:result.mapperClaimTypePlaceholder")}
              disabled={loading}
              className="text-xs px-2 py-1.5 rounded-lg border border-outline-variant bg-surface text-on-surface focus:outline-none focus:ring-1 focus:ring-primary w-[160px]"
              data-oid="mapper-claim-input"
            />
            <button
              onClick={handleExtractElements}
              disabled={loading || !claimType.trim()}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white text-xs font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
              data-oid="mapper-extract-btn"
            >
              {loading ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              {loading ? t("page:result.mapperExtracting") : t("page:result.mapperExtract")}
            </button>
          </div>
        </div>

        {/* 입증 달성도 시각화 */}
        {hasElements && (
          <div className="px-3 py-2 border-b border-outline-variant bg-surface-container-low flex-shrink-0">
            <ProgressBadge percent={mappings.overall_progress_percent} />
            {saving && (
              <span className="text-[10px] text-on-surface-variant ml-2">
                {t("page:result.mapperSaving")}
              </span>
            )}
          </div>
        )}

        {/* 에러 메시지 */}
        {error && (
          <div className="mx-3 my-2 bg-error-container border border-error text-on-error-container px-3 py-2 rounded-lg flex items-start gap-2 text-xs flex-shrink-0" data-oid="mapper-error">
            <AlertCircle size={14} className="flex-shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {/* 본문: 좌측 증거 카드 리스트 + 우측 드롭 슬롯 */}
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

          {/* 우측: 요건사실 드롭 슬롯 */}
          <div className="flex-1 min-h-0 flex flex-col">
            {!hasElements ? (
              <div className="flex-1 flex flex-col items-center justify-center text-on-surface-variant gap-2" data-oid="mapper-empty">
                <Puzzle size={32} className="text-primary/40" />
                <p className="text-xs text-center max-w-xs px-4">
                  {t("page:result.mapperEmpty")}
                </p>
              </div>
            ) : (
              <ElementDroppableSlots
                elements={mappings.elements}
                onRemoveEvidence={handleRemoveEvidence}
              />
            )}
          </div>
        </div>
      </div>
    </DndContext>
  );
}
