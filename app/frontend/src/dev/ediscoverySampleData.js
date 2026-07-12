// [Flow: Step 1 (샘플 e-Discovery 그래프 정의 — 스윔레인 스키마) -> Step 2 (샘플 요건사실 정의)
//       -> Step 3 (샘플 Job 객체 조립) -> Step 4 (개발 페이지에서 EDiscoveryViewer로 렌더링)]
// 로컬 개발 모드에서 e-Discovery UI를 백엔드 없이 미리보기하기 위한 샘플 데이터.
// 백엔드 pipeline_ediscovery.assemble_graph 출력 스키마와 동일한 구조를 따른다.

/**
 * 샘플 e-Discovery 그래프 — 사기죄 사건 타임라인.
 * 4개 스윔레인(원고/피고/제3자/쟁점) + 시간순 노드 + 모순(anomaly) 엣지.
 * 노드/엣지 스키마는 backend core/pipeline_ediscovery.py assemble_graph 출력과 일치.
 */
export const SAMPLE_EDISCOVERY_GRAPH = {
  nodes: [
    // --- 스윔레인 최상위 노드 ---
    { id: "swimlane_plaintiff", type: "swimlane", data: { label: "원고", entity: "plaintiff" } },
    { id: "swimlane_defendant", type: "swimlane", data: { label: "피고", entity: "defendant" } },
    { id: "swimlane_third_party", type: "swimlane", data: { label: "제3자", entity: "third_party" } },
    { id: "swimlane_issue", type: "swimlane", data: { label: "쟁점", entity: "issue" } },

    // --- 쟁점(issue) 노드 ---
    {
      id: "issue-1",
      type: "issue",
      parentId: "swimlane_issue",
      data: {
        label: "피고가 원고에게 허위 사실을 고지했는지 여부",
        page: 3,
        confidence: 0.95,
        entity: "issue",
        date: "2023-03-10",
        summary: "원고가 주장하는 사기죄의 핵심 요건인 허위사실 고지의 성립 여부가 주된 쟁점이다.",
        issue: "피고가 원고에게 허위 사실을 고지했는지 여부",
      },
    },
    {
      id: "issue-2",
      type: "issue",
      parentId: "swimlane_issue",
      data: {
        label: "원고의 처분행위와 피고의 기말행위 사이 인과관계",
        page: 7,
        confidence: 0.88,
        entity: "issue",
        date: "2023-03-15",
        summary: "피고의 기말행위가 원고의 재산처분 결정에 영향을 미쳤는지 인과관계가 다투어지고 있다.",
        issue: "원고의 처분행위와 피고의 기말행위 사이 인과관계",
      },
    },

    // --- 원고(plaintiff) 노드 — 진술 ---
    {
      id: "plaintiff-1",
      type: "plaintiff",
      parentId: "swimlane_plaintiff",
      data: {
        label: "원고 진술: 피고가 수익률 30%를 보장한다고 말했다",
        page: 5,
        confidence: 0.92,
        entity: "plaintiff",
        date: "2023-03-10",
        summary: "원고는 피고가 투자금에 대해 연 30% 수익을 보장한다고 설명했다고 진술한다.",
        issue: "피고가 원고에게 허위 사실을 고지했는지 여부",
      },
    },
    {
      id: "plaintiff-2",
      type: "plaintiff",
      parentId: "swimlane_plaintiff",
      data: {
        label: "원고 진술: 보장 수익을 믿고 5천만원을 투자했다",
        page: 6,
        confidence: 0.9,
        entity: "plaintiff",
        date: "2023-03-12",
        summary: "원고는 피고의 보장 발언을 신뢰하여 5,000만원을 이체했다고 진술한다.",
        issue: "원고의 처분행위와 피고의 기말행위 사이 인과관계",
      },
    },

    // --- 피고(defendant) 노드 — 진술 ---
    {
      id: "defendant-1",
      type: "defendant",
      parentId: "swimlane_defendant",
      data: {
        label: "피고 진술: 수익 보장을 한 적이 없다",
        page: 9,
        confidence: 0.85,
        entity: "defendant",
        date: "2023-03-10",
        summary: "피고는 원고에게 구체적 수익률을 보장한 사실이 없다고 부인한다.",
        issue: "피고가 원고에게 허위 사실을 고지했는지 여부",
      },
    },
    {
      id: "defendant-2",
      type: "defendant",
      parentId: "swimlane_defendant",
      data: {
        label: "피고 진술: 투자금은 사업 자금으로 사용했다",
        page: 11,
        confidence: 0.8,
        entity: "defendant",
        date: "2023-03-20",
        summary: "피고는 수령한 투자금을 부동산 사업 운영 자금으로 사용했다고 진술한다.",
        issue: "원고의 처분행위와 피고의 기말행위 사이 인과관계",
      },
    },

    // --- 제3자(third_party) 노드 — 증인/감정인 ---
    {
      id: "witness-1",
      type: "plaintiff",
      parentId: "swimlane_third_party",
      data: {
        label: "증인 김씨: 피고가 보장 수익을 언급하는 것을 들었다",
        page: 14,
        confidence: 0.78,
        entity: "third_party",
        date: "2023-03-10",
        summary: "거래 당일 동석했던 증인 김씨가 피고의 수익 보장 발언을 목격했다고 증언한다.",
        issue: "피고가 원고에게 허위 사실을 고지했는지 여부",
      },
    },

    // --- 증거(evidence) 노드 — 객관적 자료 ---
    {
      id: "evidence-1",
      type: "evidence",
      parentId: "swimlane_plaintiff",
      data: {
        label: "녹음 파일: 피고의 수익 보장 발언이 포함된 대화 녹음",
        page: 18,
        confidence: 0.97,
        entity: "plaintiff",
        date: "2023-03-10",
        summary: "원고가 제출한 녹음 파일에는 피고가 '연 30% 수익은 확정적이다'라고 말하는 내용이 포함되어 있다.",
        issue: "피고가 원고에게 허위 사실을 고지했는지 여부",
      },
    },
    {
      id: "evidence-2",
      type: "evidence",
      parentId: "swimlane_plaintiff",
      data: {
        label: "이체 내역: 원고 계좌에서 피고 계좌로 5,000만원 송금",
        page: 20,
        confidence: 0.99,
        entity: "plaintiff",
        date: "2023-03-12",
        summary: "은행 이체 내역에 따라 2023-03-12 원고 계좌에서 피고 계좌로 5,000만원이 이체되었다.",
        issue: "원고의 처분행위와 피고의 기말행위 사이 인과관계",
      },
    },
    {
      id: "evidence-3",
      type: "evidence",
      parentId: "swimlane_defendant",
      data: {
        label: "부동산 등기부: 피고 명의 부동산 매매 계약서",
        page: 22,
        confidence: 0.91,
        entity: "defendant",
        date: "2023-03-25",
        summary: "피고가 투자금 수령 후 타인 명의 부동산을 매수한 계약서가 등기부등본과 함께 제출되었다.",
        issue: "원고의 처분행위와 피고의 기말행위 사이 인과관계",
      },
    },
    {
      id: "evidence-4",
      type: "evidence",
      parentId: "swimlane_third_party",
      data: {
        label: "감정서: 피고 사업 수익 예측 보고서의 허위성 입증",
        page: 25,
        confidence: 0.86,
        entity: "third_party",
        date: "2023-04-02",
        summary: "회계감정 결과 피고가 제시한 사업 수익 예측 보고서의 핵심 수치가 과장되었음이 확인되었다.",
        issue: "피고가 원고에게 허위 사실을 고지했는지 여부",
      },
    },
  ],
  edges: [
    // --- 같은 스윔레인 내 시간순 smoothstep 엣지 (타임라인 흐름) ---
    { id: "edge-issue-1-issue-2", source: "issue-1", target: "issue-2", type: "smoothstep" },
    { id: "edge-plaintiff-1-plaintiff-2", source: "plaintiff-1", target: "plaintiff-2", type: "smoothstep" },
    { id: "edge-plaintiff-2-evidence-1", source: "plaintiff-2", target: "evidence-1", type: "smoothstep" },
    { id: "edge-evidence-1-evidence-2", source: "evidence-1", target: "evidence-2", type: "smoothstep" },
    { id: "edge-defendant-1-defendant-2", source: "defendant-1", target: "defendant-2", type: "smoothstep" },
    { id: "edge-defendant-2-evidence-3", source: "defendant-2", target: "evidence-3", type: "smoothstep" },
    { id: "edge-witness-1-evidence-4", source: "witness-1", target: "evidence-4", type: "smoothstep" },

    // --- anomaly 엣지 — 진술 vs 증거 모순 ---
    {
      id: "anomaly-defendant-1-evidence-1",
      source: "defendant-1",
      target: "evidence-1",
      type: "anomaly",
      data: {
        conflict_reason:
          "피고는 수익 보장 발언을 한 적이 없다고 부인하지만, 원고가 제출한 녹음 파일에 피고의 보장 발언이 명확히 녹음되어 있어 진술과 증거가 직접 충돌한다.",
      },
    },
    {
      id: "anomaly-defendant-2-evidence-3",
      source: "defendant-2",
      target: "evidence-3",
      type: "anomaly",
      data: {
        conflict_reason:
          "피고는 투자금을 사업 운영 자금으로 사용했다고 진술하나, 매수한 부동산이 타인 명의로 등기되어 사업 자금 사용 주장과 배치된다.",
      },
    },
  ],
};

/**
 * 샘플 e-Discovery 메트릭 — GraphCanvas 상단 패널에 표시.
 */
export const SAMPLE_EDISCOVERY_METRICS = {
  total_docs: 1,
  processed_chunks: 28,
  threshold: 0.7,
  anomalies_detected: 2,
};

/**
 * 샘플 요건사실 응답 — 사기죄 청구 원인.
 * backend core/legal_elements.py _parse_legal_elements 출력 스키마와 동일.
 * 빈 슬롯(mapped_evidence:[])을 포함해 퍼즐 매퍼에 드래그 앤 드롭할 수 있다.
 */
export const SAMPLE_LEGAL_ELEMENTS = {
  claim_type: "사기죄",
  overall_progress_percent: 0,
  elements: [
    {
      id: "element_1",
      name: "기망행위 (허위 사실의 고지)",
      description: "피고가 원고에게 허위 사실을 고지하거나 기망 행위를 하였는지 여부",
      mapped_evidence: [],
    },
    {
      id: "element_2",
      name: "처분행위 (재산의 교부)",
      description: "원고가 기망에 의해 착오에 빠져 재산을 처분(교부)하였는지 여부",
      mapped_evidence: [],
    },
    {
      id: "element_3",
      name: "인과관계 (기망 → 처분)",
      description: "피고의 기망행위와 원고의 재산 처분 사이에 인과관계가 존재하는지 여부",
      mapped_evidence: [],
    },
    {
      id: "element_4",
      name: "재산상 이익 취득/손실 발생",
      description: "피고가 재산상 이익을 취득하거나 원고에게 재산상 손실을 발생시켰는지 여부",
      mapped_evidence: [],
    },
  ],
};

/**
 * 샘플 Job 객체 — EDiscoveryViewer에 prop으로 전달.
 * backend db/models.py Job의 ediscovery_* 필드를 모방.
 */
export const SAMPLE_JOB = {
  job_id: "dev-ediscovery-sample",
  status: "done",
  pipeline: "vision",
  total_pages: 28,
  total_files: 1,
  points_spent: 0,
  created_at: "2023-04-05T10:00:00.000Z",
  updated_at: "2023-04-05T10:30:00.000Z",
  original_filename: "사기죄_소송기록_샘플.pdf",
  filename: "사기죄_소송기록_샘플.pdf",
  ediscovery_status: "done",
  ediscovery_graphs: SAMPLE_EDISCOVERY_GRAPH,
  ediscovery_metrics: SAMPLE_EDISCOVERY_METRICS,
  element_mappings: {},
};
