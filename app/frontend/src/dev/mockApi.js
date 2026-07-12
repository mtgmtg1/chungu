// [Flow: Step 1 (개발 모드 mock 핸들러 정의) -> Step 2 (request()에서 devMockEnabled일 때 라우팅)]
import {
  SAMPLE_JOB,
  SAMPLE_EDISCOVERY_GRAPH,
  SAMPLE_EDISCOVERY_METRICS,
  SAMPLE_LEGAL_ELEMENTS,
} from "./ediscoverySampleData.js";

const MOCK_USER = {
  id: "dev-user-001",
  email: "dev@proof.local",
  points_balance: 10000,
  language: "ko",
  is_admin: true,
};

// 개발 페이지 전용 샘플 Job — e-Discovery 필드가 채워진 상태로 반환.
const MOCK_EDISCOVERY_JOB_ID = "dev-ediscovery-sample";

const mockJob = (id) => {
  // e-Discovery 개발 페이지에서 사용하는 샘플 Job은 그래프/메트릭이 포함된 버전을 반환.
  if (id === MOCK_EDISCOVERY_JOB_ID) return SAMPLE_JOB;
  return {
    job_id: id,
    status: "done",
    pipeline: "vision",
    total_pages: 1,
    total_files: 1,
    points_spent: 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    xlsx_basic_converted: false,
    xlsx_advanced_status: "idle",
    xlsx_advanced_converted: false,
    error_message: null,
  };
};

// 메모리 상의 element_mappings 저장소 — 퍼즐 매퍼 드래그 앤 드롭 상태를 시뮬레이션.
let mockElementMappings = {};

const handlers = [
  {
    match: (path, method) => method === "GET" && path === "/api/auth/me",
    response: () => MOCK_USER,
  },
  {
    match: (path, method) => method === "GET" && path === "/api/admin/me",
    response: () => MOCK_USER,
  },
  {
    match: (path, method) => method === "GET" && path === "/api/jobs",
    response: () => [],
  },
  {
    match: (path, method) => method === "GET" && /^\/api\/jobs\/[^/]+$/.test(path),
    response: (path) => mockJob(path.split("/").pop()),
  },
  {
    match: (path, method) => method === "GET" && /^\/api\/jobs\/[^/]+\/preview(?:\?.*)?$/.test(path),
    response: () => ({
      markdown: "# Mock result\n\nDevelopment mode preview.",
      file_markdowns: [],
      image_urls: [],
      source_url: null,
      source_type: "pdf",
      source_files: [
        {
          page_num: 1,
          type: "pdf",
          name: "sample.pdf",
          url: "",
          preview_url: "",
          result_markdown: "",
        },
      ],
    }),
  },
  {
    match: (path, method) => method === "GET" && /^\/api\/jobs\/[^/]+\/preview\/pages(?:\?.*)?$/.test(path),
    response: () => [],
  },
  {
    match: (path, method) => method === "GET" && /^\/api\/jobs\/[^/]+\/download\?/.test(path),
    response: () => "mock-download-url",
  },
  {
    match: (path, method) => method === "GET" && path === "/api/payments/packages",
    response: () => ({ min_amount: 5, max_amount: 500, packages: [] }),
  },
  {
    match: (path, method) => method === "GET" && path === "/api/payments/history",
    response: () => [],
  },
  {
    match: (path, method) => method === "GET" && path === "/api/payments/paddle/payment-methods",
    response: () => [],
  },
  {
    match: (path, method) => method === "GET" && path === "/api/payments/auto-recharge/settings",
    response: () => ({ enabled: false, threshold: 2000, amount: 10, has_payment_method: false, retries: 0 }),
  },
  {
    match: (path, method) => method === "GET" && path === "/api/v1/account",
    response: () => ({
      id: "dev-user-001",
      email: "dev@proof.local",
      points_balance: 10000,
      today_usage: { points_spent: 0 },
      created_at: new Date().toISOString(),
    }),
  },
  {
    match: (path, method) => method === "GET" && path === "/api/v1/account/pricing",
    response: () => ({
      pipeline_pricing: { vision: 5, media: 5 },
      export_pricing: { xlsx_advanced: 3 },
    }),
  },
  {
    match: (path, method) => method === "GET" && /^\/api\/v1\/account\/usage/.test(path),
    response: () => [],
  },
  {
    match: (path, method) => method === "GET" && /^\/api\/v1\/account\/transactions/.test(path),
    response: () => [],
  },
  {
    match: (path, method) => method === "GET" && path === "/api/v1/account/payments",
    response: () => [],
  },
  {
    match: (path, method) => method === "GET" && path === "/api/v1/keys",
    response: () => [],
  },
  {
    match: (path, method) => method === "GET" && path === "/api/admin/settings",
    response: () => ({
      default_ocr_model: "vision",
      docling_refinement_enabled: true,
      paddleocr_fallback_enabled: true,
      paddleocr_fallback_daily_limit: 20000,
      paddleocr_fallback_hourly_quota: 800,
      smtp_host: "",
      smtp_port: 587,
      smtp_user: "",
      smtp_from: "",
      llm_endpoint: "http://localhost:18080/v1",
      llm_model: "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit",
      media_llm_endpoint: "http://localhost:18080/v1",
      media_llm_model: "unsloth/gemma-4-12b-it-GGUF",
    }),
  },
  {
    match: (path, method) => method === "GET" && path === "/api/admin/jobs",
    response: () => [],
  },
  {
    match: (path, method) => method === "GET" && path === "/api/payments/admin/history",
    response: () => [],
  },
  {
    match: (path, method) => method === "GET" && /^\/api\/jobs\/[^/]+\/edited-xlsx-url$/.test(path),
    response: () => ({ url: "" }),
  },
  {
    match: (path, method) => method === "GET" && /^\/api\/jobs\/[^/]+\/result\/pages\/\d+$/.test(path),
    response: () => ({ markdown: "" }),
  },
  {
    match: (path, method) => method === "GET" && /^\/api\/jobs\/[^/]+\/result$/.test(path),
    response: () => ({ markdown: "# Mock result\n\nDevelopment mode preview." }),
  },

  // --- e-Discovery GraphRAG (개발 페이지 전용 샘플) ---
  {
    match: (path, method) => method === "GET" && /^\/api\/jobs\/[^/]+\/ediscovery$/.test(path),
    response: (path) => {
      const jobId = path.split("/")[3];
      if (jobId !== MOCK_EDISCOVERY_JOB_ID) {
        return { job_id: jobId, ediscovery_status: "", graph_data: { nodes: [], edges: [] }, ediscovery_metrics: {} };
      }
      return {
        job_id: jobId,
        ediscovery_status: "done",
        ediscovery_metrics: SAMPLE_EDISCOVERY_METRICS,
        graph_data: SAMPLE_EDISCOVERY_GRAPH,
        ediscovery_error: "",
      };
    },
  },
  {
    match: (path, method) =>
      method === "GET" && /^\/api\/jobs\/[^/]+\/legal-elements$/.test(path),
    response: (path) => {
      const jobId = path.split("/")[3];
      const url = new URL(path, "http://localhost");
      const claimType = url.searchParams.get("claim_type") || "사기죄";
      // 캐시된 매핑이 있으면 반환, 없으면 샘플 요건사실 반환.
      if (mockElementMappings.elements?.length > 0 && mockElementMappings.claim_type === claimType) {
        return { job_id: jobId, element_mappings: mockElementMappings };
      }
      return { job_id: jobId, element_mappings: { ...SAMPLE_LEGAL_ELEMENTS, claim_type: claimType } };
    },
  },
  {
    match: (path, method) =>
      method === "GET" && /^\/api\/jobs\/[^/]+\/legal-elements\/mappings$/.test(path),
    response: (path) => {
      const jobId = path.split("/")[3];
      return { job_id: jobId, element_mappings: mockElementMappings };
    },
  },
  {
    match: (path, method) =>
      method === "PUT" && /^\/api\/jobs\/[^/]+\/legal-elements\/mappings$/.test(path),
    response: (path, _method, options) => {
      const jobId = path.split("/")[3];
      const body = options.body ? JSON.parse(options.body) : {};
      mockElementMappings = body;
      return { job_id: jobId, element_mappings: mockElementMappings };
    },
  },
  // 모든 쓰기/변형 요청은 성공처럼 처리합니다.
  {
    match: () => true,
    response: () => ({}),
  },
];

/** 개발 mock 응답을 반환합니다. */
export async function mockRequest(path, options = {}) {
  const method = options.method || "GET";
  const handler = handlers.find((h) => h.match(path, method));
  const result = handler ? handler.response(path, method, options) : {};
  return Promise.resolve(result);
}
