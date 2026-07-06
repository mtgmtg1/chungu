// [Flow: Step 1 (access token 획득) -> Step 2 (fetch 래퍼) -> Step 3 (JSON 파싱 + 에러 throw)]
import { supabase } from './supabase.js'
import i18n from './i18n.js'
import { mockRequest } from './dev/mockApi.js'

let devMockEnabled = import.meta.env.DEV ?? false

export function enableDevMock(enabled) {
  devMockEnabled = enabled
}

export async function getToken() {
  const { data } = await supabase.auth.getSession()
  return data.session?.access_token
}

async function request(path, options = {}) {
  if (devMockEnabled) {
    return mockRequest(path, options)
  }
  const token = await getToken()
  const headers = { ...(options.headers || {}) }
  if (token) headers.Authorization = `Bearer ${token}`
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
  if (token) headers.Authorization = `Bearer ${token}`
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

  // 작업
  uploadJob: (formData) => request('/api/jobs/upload', { method: 'POST', body: formData }),
  initJob: (payload) => request('/api/jobs/init', { method: 'POST', body: JSON.stringify(payload) }),
  createJob: (jobId, payload) => request(`/api/jobs/${jobId}/create`, { method: 'POST', body: JSON.stringify(payload) }),
  updateJob: (id, payload) => request(`/api/jobs/${id}`, { method: 'PUT', body: JSON.stringify(payload) }),
  confirmJob: (id) => request(`/api/jobs/${id}/confirm`, { method: 'POST' }),
  getJob: (id) => request(`/api/jobs/${id}`),
  listJobs: () => request('/api/jobs'),
  previewJob: (id, startPage = 1, endPage = null) => {
    const params = new URLSearchParams()
    params.set('start_page', String(startPage))
    if (endPage) params.set('end_page', String(endPage))
    return request(`/api/jobs/${id}/preview?${params.toString()}`)
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
      body: JSON.stringify({ source_index, annotations }),
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
}
