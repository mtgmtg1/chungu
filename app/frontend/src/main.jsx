// [Flow: Step 1 (AuthProvider) -> Step 2 (라우터 구성) -> Step 3 (사용자/관리자 페이지 분기)]
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import './index.css'
import { AuthProvider } from './AuthContext.jsx'
import UploadPage from './pages/UploadPage.jsx'
import AuthPage from './pages/AuthPage.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import PaymentPage from './pages/PaymentPage.jsx'
import AdminLogin from './pages/AdminLogin.jsx'
import AdminDashboard from './pages/AdminDashboard.jsx'
import DeveloperPage from './pages/DeveloperPage.jsx'
import JobConfirmPage from './pages/JobConfirmPage.jsx'
import JobResultPage from './pages/JobResultPage.jsx'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/login" element={<AuthPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/payment" element={<PaymentPage />} />
          <Route path="/developer" element={<DeveloperPage />} />
          <Route path="/jobs/:jobId/confirm" element={<JobConfirmPage />} />
          <Route path="/jobs/:jobId" element={<JobResultPage />} />
          <Route path="/admin/login" element={<AdminLogin />} />
          <Route path="/admin" element={<AdminDashboard />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  </React.StrictMode>,
)
