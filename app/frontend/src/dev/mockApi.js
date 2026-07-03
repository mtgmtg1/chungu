// [Flow: Step 1 (개발 모드 mock 핸들러 정의) -> Step 2 (request()에서 devMockEnabled일 때 라우팅)]
const MOCK_USER = {
  id: "dev-user-001",
  email: "dev@proof.local",
  points_balance: 10000,
  language: "ko",
  is_admin: true,
};

const mockJob = (id) => ({
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
});

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
    match: (path, method) => method === "GET" && /^\/api\/jobs\/[^/]+\/preview$/.test(path),
    response: () => ({
      markdown: "# Mock result\n\nDevelopment mode preview.",
      file_markdowns: [],
      image_urls: [],
      source_url: null,
      source_type: "pdf",
    }),
  },
  {
    match: (path, method) => method === "GET" && /^\/api\/jobs\/[^/]+\/preview\/pages$/.test(path),
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
  // 모든 쓰기/변형 요청은 성공처럼 처리합니다.
  {
    match: () => true,
    response: (path, method, options) => {
      console.warn(`[DEV MOCK] ${method} ${path}`, options);
      return {};
    },
  },
];

/** 개발 mock 응답을 반환합니다. */
export async function mockRequest(path, options = {}) {
  const method = options.method || "GET";
  const handler = handlers.find((h) => h.match(path, method));
  const result = handler ? handler.response(path, method, options) : {};
  return Promise.resolve(result);
}
