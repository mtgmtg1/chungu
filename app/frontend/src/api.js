// [Flow: Step 1 (access token 획득) -> Step 2 (fetch 래퍼) -> Step 3 (JSON 파싱 + 에러 throw)]
import { supabase } from './supabase.js'
import i18n from './i18n.js'

async function getToken() {
  const { data } = await supabase.auth.getSession()
  return data.session?.access_token
}

async function request(path, options = {}) {
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
  saveResultPage: (id, pageNum, markdown) =>
    request(`/api/jobs/${id}/result/pages/${pageNum}`, {
      method: 'PATCH',
      body: JSON.stringify({ markdown }),
    }),
  convertJob: (id, format) =>
    request(`/api/jobs/${id}/convert`, { method: 'POST', body: JSON.stringify({ format }) }),
  downloadJob: (id, type) => request(`/api/jobs/${id}/download?type=${type}`),
  downloadUrl: (id, type) => `/api/jobs/${id}/download?type=${type}`,
  deleteJob: (id) => request(`/api/jobs/${id}`, { method: 'DELETE' }),

  // 결제
  getPackages: () => request('/api/payments/packages'),
  createTossOrder: (payload) => request('/api/payments/toss/order', { method: 'POST', body: JSON.stringify(payload) }),
  verifyToss: (payload) => request('/api/payments/toss/success', { method: 'POST', body: JSON.stringify(payload) }),
  createPaddleCheckout: (payload) => request('/api/payments/paddle/checkout', { method: 'POST', body: JSON.stringify(payload) }),
  paymentHistory: () => request('/api/payments/history'),

  // 관리자
  adminLogin: (email, password) =>
    request('/api/admin/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
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
}
