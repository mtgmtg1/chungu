import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { I18nextProvider } from "react-i18next";
import "./index.css";
import "./i18n.js";
import i18n from "./i18n.js";
import { AuthProvider } from "./AuthContext.jsx";
import { LanguageProvider } from "./LanguageContext.jsx";
import { enableDevMock } from "./api.js";
import UploadPage from "./pages/UploadPage.jsx";
import AuthPage from "./pages/AuthPage.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import PaymentPage from "./pages/PaymentPage.jsx";
import AdminLogin from "./pages/AdminLogin.jsx";
import AdminDashboard from "./pages/AdminDashboard.jsx";
import DeveloperPage from "./pages/DeveloperPage.jsx";
import JobsPage from "./pages/JobsPage.jsx";
import JobConfirmPage from "./pages/JobConfirmPage.jsx";
import JobResultPage from "./pages/JobResultPage.jsx";
import SettingsPage from "./pages/SettingsPage.jsx";
import LegalTermsPage from "./pages/LegalTermsPage.jsx";
import LegalPrivacyPage from "./pages/LegalPrivacyPage.jsx";
import LegalRefundPage from "./pages/LegalRefundPage.jsx";
import PricePage from "./pages/PricePage.jsx";
import ApiPricingPage from "./pages/ApiPricingPage.jsx";
import CookieConsent from "./components/CookieConsent.jsx";
import ProtectedRoute from "./components/ProtectedRoute.jsx";
import DevEdiscoveryPage from "./pages/DevEdiscoveryPage.jsx";
import DevEdiscoveryTimelinePage from "./pages/DevEdiscoveryTimelinePage.jsx";

// 개발 환경에서 전역 dev mock 활성화 — /dev/* 및 /jobs/:jobId 경로 모두 샘플 데이터로 UI 테스트 가능.
// production 빌드에서는 import.meta.env.DEV가 false이므로 무시된다.
if (import.meta.env.DEV) {
  enableDevMock(true);
}

const rootEl = document.getElementById("root");
ReactDOM.createRoot(rootEl).render(
  <React.StrictMode data-oid="6kqspej">
    <I18nextProvider i18n={i18n} data-oid="53d8vza">
      <LanguageProvider data-oid="1e:x9zs">
        <AuthProvider data-oid="xcbpezj">
          <BrowserRouter data-oid="j3r-hj3">
            <Routes data-oid="sza8yga">
              <Route
                path="/"
                element={<UploadPage data-oid="tyuzd8m" />}
                data-oid="f4q43vu" />


              <Route
                path="/login"
                element={<AuthPage data-oid="fgx:gn0" />}
                data-oid="xouxlfl" />


              <Route
                path="/dashboard"
                element={
                  <ProtectedRoute data-oid="dashboard-protected">
                    <DashboardPage data-oid="_9w:9za" />
                  </ProtectedRoute>
                }
                data-oid="ff86bvq" />


              <Route
                path="/jobs"
                element={
                  <ProtectedRoute data-oid="jobs-protected">
                    <JobsPage data-oid="fclppvc" />
                  </ProtectedRoute>
                }
                data-oid="i8jaj__" />


              <Route
                path="/payment"
                element={
                  <ProtectedRoute data-oid="payment-protected">
                    <PaymentPage data-oid="45vjc9v" />
                  </ProtectedRoute>
                }
                data-oid="oozoys2" />


              <Route
                path="/price"
                element={<PricePage data-oid="price-route" />}
                data-oid="price-route-r" />


              <Route
                path="/api-pricing"
                element={<ApiPricingPage data-oid="api-pricing-route" />}
                data-oid="api-pricing-route-r" />


              <Route
                path="/developer"
                element={
                  <ProtectedRoute data-oid="developer-protected">
                    <DeveloperPage data-oid="vxyzmzt" />
                  </ProtectedRoute>
                }
                data-oid="bomn0fs" />


              <Route
                path="/jobs/:jobId/confirm"
                element={
                  <ProtectedRoute data-oid="jobconfirm-protected">
                    <JobConfirmPage data-oid="tsroq7p" />
                  </ProtectedRoute>
                }
                data-oid="5dy2wet" />


              <Route
                path="/jobs/:jobId"
                element={
                  <ProtectedRoute data-oid="jobresult-protected">
                    <JobResultPage data-oid="rc_ef71" />
                  </ProtectedRoute>
                }
                data-oid="_m5xc0o" />


              <Route
                path="/settings"
                element={
                  <ProtectedRoute data-oid="settings-protected">
                    <SettingsPage data-oid="aw8n85r" />
                  </ProtectedRoute>
                }
                data-oid="2uu7w76" />


              <Route
                path="/admin/login"
                element={<AdminLogin data-oid="iu9rdhq" />}
                data-oid="lgus3p2" />


              <Route
                path="/admin"
                element={<AdminDashboard data-oid="kl1-:.8" />}
                data-oid="3mpq7x5" />

              <Route
                path="/terms"
                element={<LegalTermsPage data-oid="lglterms" />}
                data-oid="lglterms_r" />


              <Route
                path="/privacy"
                element={<LegalPrivacyPage data-oid="lglpriv" />}
                data-oid="lglpriv_r" />


              <Route
                path="/refund-policy"
                element={<LegalRefundPage data-oid="lglrefund" />}
                data-oid="lglrefund_r" />

              {/* 개발 전용 라우트 — production 빌드에서는 접근해도 mock 데이터만 표시됨 */}
              <Route
                path="/dev/ediscovery"
                element={<DevEdiscoveryPage data-oid="dev-ediscovery-route" />}
                data-oid="dev-ediscovery-route-r" />
              <Route
                path="/dev/ediscovery-timeline"
                element={<DevEdiscoveryTimelinePage data-oid="dev-ediscovery-timeline-route" />}
                data-oid="dev-ediscovery-timeline-route-r" />

            </Routes>
          <CookieConsent data-oid="cookie_consent" />
          </BrowserRouter>
        </AuthProvider>
      </LanguageProvider>
    </I18nextProvider>
  </React.StrictMode>
);