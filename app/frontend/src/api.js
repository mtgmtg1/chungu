// [Flow: Step 1 (access token 획득) -> Step 2 (fetch 래퍼) -> Step 3 (JSON 파싱 + 에러 throw)]
import { supabase } from './supabase.js'
import i18n from './i18n.js'
import { mockRequest } from './dev/mockApi.js'
import { rewritePreviewUrls } from './utils/rewriteSupabaseUrl.js'

let devMockEnabled = false

export function enableDevMock(enabled) {
  devMockEnabled = enabled
}

export async function getToken() {
  // 개발 환경에서 /api/dev/login으로 발급받은 bypass JWT가 있으면 먼저 사용한다.
  // Supabase 엔드포인트가 없는 로컬 개발 환경에서도 API 인증이 정상 동작하게 한다.
  // 디버그 페이지(/dev/debug-*)에서는 production 빌드에서도 dev bypass 토큰을 사용한다.
  const isDebugPage = typeof window !== 'undefined' && window.location.pathname.startsWith('/dev/debug-')
  if (import.meta.env.DEV || isDebugPage) {
    const devToken = localStorage.getItem("dev_access_token");
    if (devToken && devToken.startsWith("eyJ")) {
      console.log("[api.js getToken] dev access token 사용");
      return devToken;
    }
  }
  // 로컬 개발 환경에서 supabase.auth.getSession()이 Supabase 엔드포인트가 없어
  // 토큰 갱신을 시도하며 hang되는 것을 방지하기 위해 타임아웃을 건다.
  const { data } = await Promise.race([
    supabase.auth.getSession(),
    new Promise(resolve => setTimeout(() => resolve({ data: { session: null } }), 2000)),
  ])
  return data.session?.access_token
}

// 개발 환경에서만 기본 dev API key를 사용하고, production에서는 빌드 시 명시적으로
// 주입된 VITE_DEV_API_KEY가 없으면 헤더를 전송하지 않는다 (세션 인증만 사용).
const DEV_API_KEY = import.meta.env.DEV
  ? (import.meta.env.VITE_DEV_API_KEY || 'chu_live_testkey12345')
  : (import.meta.env.VITE_DEV_API_KEY || '')

async function request(path, options = {}) {
  if (devMockEnabled) {
    return mockRequest(path, options)
  }
  const token = await getToken()
  const headers = { ...(options.headers || {}) }
  // JWT 형식의 유효한 access_token일 때만 Bearer 헤더를 추가한다 (mock token은 제외)
  // JWT가 있으면 API key를 보내지 않는다: 백엔드가 API key를 먼저 검사하면
  // 유효한 JWT임에도 불구하고 Invalid API key로 거부될 수 있다.
  if (token && token.startsWith('eyJ')) {
    headers.Authorization = `Bearer ${token}`
  } else if (DEV_API_KEY) {
    headers['X-Api-Key'] = DEV_API_KEY
  }
  if (options.body && !(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }

  const res = await fetch(path, { credentials: 'include', ...options, headers })
  const isJson = (res.headers.get('content-type') || '').includes('application/json')
  const body = isJson ? await res.json() : await res.text()
  if (!res.ok) {
    const detail = isJson ? body.detail : body
    throw new Error(detail || i18n.t('page:errors.requestFailed', { status: res.status }))
  }
  return body
}

async function authenticatedFetch(url, options = {}) {
  const token = await getToken()
  const headers = { ...(options.headers || {}) }
  // JWT 형식의 유효한 access_token일 때만 Bearer 헤더를 추가한다 (mock token은 제외)
  // JWT가 있으면 API key를 보내지 않는다: 백엔드가 API key를 먼저 검사하면
  // 유효한 JWT임에도 불구하고 Invalid API key로 거부될 수 있다.
  if (token && token.startsWith('eyJ')) {
    headers.Authorization = `Bearer ${token}`
  } else if (DEV_API_KEY) {
    headers['X-Api-Key'] = DEV_API_KEY
  }
  if (options.body && !(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }
  return fetch(url, { credentials: 'include', ...options, headers })
}

export const api = {
  // 사용자 인증/프로필
  me: () => request('/api/auth/me'),
  updateLanguage: (payload) =>
    request('/api/auth/language', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  updateAISettings: (payload) =>
    request('/api/auth/ai-settings', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  // 작업
  uploadJob: (formData) => request('/api/jobs/upload', { method: 'POST', body: formData }),
  initJob: (payload) => request('/api/jobs/init', { method: 'POST', body: JSON.stringify(payload) }),
  createJob: (jobId, payload) => request(`/api/jobs/${jobId}/create`, { method: 'POST', body: JSON.stringify(payload) }),
  // 기존 Job 에 파일 추가 (initAddFiles → TUS 업로드 → confirmAddFiles)
  initAddFiles: (jobId, payload) => request(`/api/jobs/${jobId}/init-add-files`, { method: 'POST', body: JSON.stringify(payload) }),
  confirmAddFiles: (jobId, payload) => request(`/api/jobs/${jobId}/confirm-add-files`, { method: 'POST', body: JSON.stringify(payload) }),
  updateJob: (id, payload) => request(`/api/jobs/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  confirmJob: (id) => request(`/api/jobs/${id}/confirm`, { method: 'POST' }),
  getJob: (id) => request(`/api/jobs/${id}`),
  listJobs: () => request('/api/jobs'),
  previewJob: async (id, startPage = 1, endPage = null) => {
    const params = new URLSearchParams()
    params.set('start_page', String(startPage))
    if (endPage) params.set('end_page', String(endPage))
    // 개발 환경에서 브라우저/프록시 캐시로 인해 오래된 preview 응답이 재사용되는 것을 방지
    if (import.meta.env.DEV) params.set('_t', String(Date.now()))
    const data = await request(`/api/jobs/${id}/preview?${params.toString()}`)
    // Supabase 내부 IP나 외부 public URL을 /supabase 상대 경로로 재작성하여
    // 브라우저가 현재 origin의 프록시를 탈 수 있게 한다.
    return rewritePreviewUrls(data)
  },
  previewJobPages: (id) => request(`/api/jobs/${id}/preview/pages`),
  saveResultMarkdown: (id, markdown) =>
    request(`/api/jobs/${id}/result`, { method: 'PUT', body: JSON.stringify({ markdown }) }),
  saveResultFileMarkdowns: (id, fileMarkdowns) =>
    request(`/api/jobs/${id}/result`, { method: 'PUT', body: JSON.stringify({ file_markdowns: fileMarkdowns }) }),
  saveResultPage: (id, pageNum, markdown) =>
    request(`/api/jobs/${id}/result/pages/${pageNum}`, {
      method: 'PATCH',
      body: JSON.stringify({ markdown }),
    }),
  convertJob: (id, format) =>
    request(`/api/jobs/${id}/convert`, { method: 'POST', body: JSON.stringify({ format }) }),
  downloadJob: (id, type) => request(`/api/jobs/${id}/download?type=${type}`),
  xlsxAdvancedAction: (id, action) =>
    request(`/api/jobs/${id}/xlsx-advanced-action`, { method: 'POST', body: JSON.stringify({ action }) }),
  annotateJob: (id, { instruction, mode, commentMode, advanced, pageRange }) =>
    request(`/api/jobs/${id}/annotate`, {
      method: 'POST',
      body: JSON.stringify({ instruction, mode, comment_mode: commentMode, advanced, page_range: pageRange }),
    }),
  annotateJobEdit: (id, { instruction, pageRange }) =>
    request(`/api/jobs/${id}/annotate-edit`, {
      method: 'POST',
      body: JSON.stringify({ instruction, page_range: pageRange }),
    }),
  annotateAction: (id, action, annotationIndex) =>
    request(`/api/jobs/${id}/annotate-action`, {
      method: 'POST',
      body: JSON.stringify({ action, annotation_index: annotationIndex }),
    }),
  cancelAnnotation: (id, annotationIndex) =>
    request(`/api/jobs/${id}/annotate-cancel`, {
      method: 'POST',
      body: JSON.stringify({ annotation_index: annotationIndex }),
    }),
  saveUserAnnotations: (id, { source_index, annotations }) =>
    request(`/api/jobs/${id}/user-annotations`, {
      method: 'POST',
      body: JSON.stringify({ source_index, annotations, input_space: 'device' }),
    }),
  jobAction: (id, action) =>
    request(`/api/jobs/${id}/action`, { method: 'POST', body: JSON.stringify({ action }) }),
  saveEditedXlsx: (id, blob, filename = 'result_edited.xlsx') => {
    const formData = new FormData()
    formData.append('file', blob, filename)
    return request(`/api/jobs/${id}/save-edited-xlsx`, { method: 'POST', body: formData })
  },
  editedXlsxUrl: (id) => request(`/api/jobs/${id}/edited-xlsx-url`),
  downloadUrl: (id, type) => `/api/jobs/${id}/download?type=${type}`,
  deleteJob: (id) => request(`/api/jobs/${id}`, { method: 'DELETE' }),
  deleteSourceFile: (id, kind, index) =>
    request(`/api/jobs/${id}/source-files/${kind}/${index}`, { method: 'DELETE' }),

  // 결제
  getPackages: () => request('/api/payments/packages'),
  createPaddleCheckout: (payload) => request('/api/payments/paddle/checkout', { method: 'POST', body: JSON.stringify(payload) }),
  paymentHistory: () => request('/api/payments/history'),
  // 자동 충전
  getAutoRechargeSettings: () => request('/api/payments/auto-recharge/settings'),
  updateAutoRechargeSettings: (payload) => request('/api/payments/auto-recharge/settings', { method: 'POST', body: JSON.stringify(payload) }),
  getPaymentMethods: () => request('/api/payments/paddle/payment-methods'),
  // 구독 요금제
  getMySubscription: () => request('/api/subscriptions/me'),
  createSubscriptionCheckout: (payload) => request('/api/subscriptions/checkout', { method: 'POST', body: JSON.stringify(payload) }),
  cancelSubscription: () => request('/api/subscriptions/cancel', { method: 'POST' }),

  // 온프레미스 로컬 서버
  submitOnPremiseInquiry: (payload) =>
    request('/api/on-premise/inquiry', { method: 'POST', body: JSON.stringify(payload) }),

  // 관리자
  adminLogin: (email, password, turnstileToken = "") =>
    request('/api/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, turnstile_token: turnstileToken }),
    }),
  adminLogout: () => request('/api/admin/logout', { method: 'POST' }),
  adminMe: () => request('/api/admin/me'),
  getSettings: () => request('/api/admin/settings'),
  saveSettings: (payload) =>
    request('/api/admin/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  testLlm: () => request('/api/admin/settings/test-llm', { method: 'POST' }),
  testSmtp: (to) =>
    request('/api/admin/settings/test-smtp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to }),
    }),
  changePassword: (current_password, new_password) =>
    request('/api/admin/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password, new_password }),
    }),
  adminListJobs: () => request('/api/admin/jobs'),
  adminPaymentHistory: () => request('/api/payments/admin/history'),

  // 개발자 포털 (v1 API)
  devAccount: () => request('/api/v1/account'),
  devPricing: () => request('/api/v1/account/pricing'),
  devTransactions: (limit = 100) => request(`/api/v1/account/transactions?limit=${limit}`),
  devUsage: (days = 30) => request(`/api/v1/account/usage?days=${days}`),
  devPayments: () => request('/api/v1/account/payments'),
  createApiKey: (payload) => request('/api/v1/keys', { method: 'POST', body: JSON.stringify(payload) }),
  listApiKeys: () => request('/api/v1/keys'),
  deleteApiKey: (id) => request(`/api/v1/keys/${id}`, { method: 'DELETE' }),
  rotateApiKey: (id) => request(`/api/v1/keys/${id}/rotate`, { method: 'POST' }),

  // AI 마크다운 에디터 스트리밍
  aiGenerateStream: (url, options) => authenticatedFetch(url, options),

  // Kata Containers 샌드박스 (에이전트 격리 실행 환경)
  createSandbox: (jobId, resourceLimits, denseMode) =>
    request('/api/sandboxes', {
      method: 'POST',
      body: JSON.stringify({ job_id: jobId, resource_limits: resourceLimits, dense_mode: denseMode }),
    }),
  getSandbox: (sandboxId) => request(`/api/sandboxes/${sandboxId}`),
  executeInSandbox: (sandboxId, command, timeout) =>
    request(`/api/sandboxes/${sandboxId}/execute`, {
      method: 'POST',
      body: JSON.stringify({ command, timeout }),
    }),
  listSandboxFiles: (sandboxId, path) =>
    request(`/api/sandboxes/${sandboxId}/files?path=${encodeURIComponent(path)}`),
  readSandboxFile: (sandboxId, path) =>
    request(`/api/sandboxes/${sandboxId}/files/read?path=${encodeURIComponent(path)}`),
  writeSandboxFile: (sandboxId, path, content) =>
    request(`/api/sandboxes/${sandboxId}/files/write`, {
      method: 'POST',
      body: JSON.stringify({ path, content }),
    }),
  commitSandboxChanges: (sandboxId, message) =>
    request(`/api/sandboxes/${sandboxId}/commit`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),
  getSandboxDiff: (sandboxId, cached) =>
    request(`/api/sandboxes/${sandboxId}/diff?cached=${cached}`),
  collectSandboxResults: (sandboxId) =>
    request(`/api/sandboxes/${sandboxId}/collect`, { method: 'POST' }),
  destroySandbox: (sandboxId) => request(`/api/sandboxes/${sandboxId}`, { method: 'DELETE' }),
  getSandboxStats: () => request('/api/sandboxes/stats'),

  // Flow Panel 드로잉/주석 저장
  getFlowDrawings: (jobId) => request(`/api/jobs/${jobId}/flow-drawings`),
  saveFlowDrawings: (jobId, data) =>
    request(`/api/jobs/${jobId}/flow-drawings`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteFlowDrawings: (jobId) =>
    request(`/api/jobs/${jobId}/flow-drawings`, { method: 'DELETE' }),

  // e-Discovery GraphRAG
  getEdiscovery: (jobId) => request(`/api/jobs/${jobId}/ediscovery`),
  extractEdiscoveryGraph: (jobId, params = { auto: true }, { wait = false } = {}) =>
    request(`/api/jobs/${jobId}/ediscovery/extract?wait=${wait}`, {
      method: 'POST',
      body: JSON.stringify(params),
    }),
  adjustGraphThreshold: (jobId, { threshold }, { wait = false } = {}) =>
    request(`/api/jobs/${jobId}/ediscovery/threshold?wait=${wait}`, {
      method: 'POST',
      body: JSON.stringify({ threshold }),
    }),
  saveEdiscoveryGraph: (jobId, graph) =>
    request(`/api/jobs/${jobId}/ediscovery/graph`, {
      method: 'PUT',
      body: JSON.stringify(graph),
    }),

  // Evidence-to-Element Mapper — 요건사실 기반 증거 퍼즐 매퍼
  getLegalElements: (jobId, claimType = '') => {
    const query = claimType ? `?claim_type=${encodeURIComponent(claimType)}` : '';
    return request(`/api/jobs/${jobId}/legal-elements${query}`);
  },
  saveElementMappings: (jobId, data) =>
    request(`/api/jobs/${jobId}/legal-elements/mappings`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  getElementMappings: (jobId) =>
    request(`/api/jobs/${jobId}/legal-elements/mappings`),

  // Issue-Claim-Evidence Tree — 쟁점 → 주장 → 근거 3단계 트리 매퍼
  getLegalIssueTree: (jobId, claimType = '') => {
    const query = claimType ? `?claim_type=${encodeURIComponent(claimType)}` : '';
    return request(`/api/jobs/${jobId}/legal-issue-tree${query}`);
  },
  saveIssueTreeMappings: (jobId, data) =>
    request(`/api/jobs/${jobId}/legal-issue-tree/mappings`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  getIssueTreeMappings: (jobId) =>
    request(`/api/jobs/${jobId}/legal-issue-tree/mappings`),

  // 에이전트 채팅 대화 이력 (DB 영속화)
  listChatConversations: (jobId) =>
    request(`/api/jobs/${jobId}/chat-conversations`),
  getChatConversation: (jobId, conversationId) =>
    request(`/api/jobs/${jobId}/chat-conversations/${conversationId}`),
  saveChatConversation: (jobId, conversationId, data) =>
    request(`/api/jobs/${jobId}/chat-conversations/${conversationId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteChatConversation: (jobId, conversationId) =>
    request(`/api/jobs/${jobId}/chat-conversations/${conversationId}`, {
      method: 'DELETE',
    }),

  // 디버그: 하이라이트 좌표 어긋남 진단 (스캔 PDF searchable 텍스트 레이어)
  debugHighlightCoords: (jobId, { query, page_no, dpi }) => {
    const params = new URLSearchParams({ query, page_no: String(page_no), dpi: String(dpi), _t: String(Date.now()) })
    return request(`/api/jobs/${jobId}/debug/highlight-coords?${params.toString()}`)
  },
}
