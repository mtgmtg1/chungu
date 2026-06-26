// [Flow: Step 1 (i18n init) -> Step 2 (LanguageProvider) -> Step 3 (AuthProvider) -> Step 4 (라우터 구성) -> Step 5 (사용자/관리자 페이지 분기)]
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { I18nextProvider } from 'react-i18next'
import './index.css'
import './i18n.js'
import i18n from './i18n.js'
import { AuthProvider } from './AuthContext.jsx'
import { LanguageProvider } from './LanguageContext.jsx'
import UploadPage from './pages/UploadPage.jsx'
import AuthPage from './pages/AuthPage.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import PaymentPage from './pages/PaymentPage.jsx'
import AdminLogin from './pages/AdminLogin.jsx'
import AdminDashboard from './pages/AdminDashboard.jsx'
import DeveloperPage from './pages/DeveloperPage.jsx'
import JobsPage from './pages/JobsPage.jsx'
import JobConfirmPage from './pages/JobConfirmPage.jsx'
import JobResultPage from './pages/JobResultPage.jsx'
import SettingsPage from './pages/SettingsPage.jsx'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <I18nextProvider i18n={i18n}>
      <LanguageProvider>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/" element={<UploadPage />} />
              <Route path="/login" element={<AuthPage />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/jobs" element={<JobsPage />} />
              <Route path="/payment" element={<PaymentPage />} />
              <Route path="/developer" element={<DeveloperPage />} />
              <Route path="/jobs/:jobId/confirm" element={<JobConfirmPage />} />
              <Route path="/jobs/:jobId" element={<JobResultPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/admin/login" element={<AdminLogin />} />
              <Route path="/admin" element={<AdminDashboard />} />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </LanguageProvider>
    </I18nextProvider>
  </React.StrictMode>,
)
