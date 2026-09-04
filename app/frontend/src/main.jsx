// [Flow: Step 1 (전역 Provider 구성) -> Step 2 (라우트별 lazy 청크 선언) -> Step 3 (Suspense 경계 아래 라우팅)]
//
// 라우트는 랜딩(UploadPage)을 제외하고 모두 React.lazy 로 분리한다.
// 정적 import 로 두면 JobResultPage 가 끌어오는 pdf-viewer / tiptap / flow / ai 벤더 청크가
// 전부 진입 그래프에 포함되어 랜딩 진입만으로 brotli 1.28MB 를 내려받게 된다.
import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { I18nextProvider } from "react-i18next";
import "./i18n.js";
import i18n from "./i18n.js";
import "./index.css";
import { AuthProvider } from "./AuthContext.jsx";
import { LanguageProvider } from "./LanguageContext.jsx";
import { enableDevMock } from "./api.js";
import CookieConsent from "./components/CookieConsent.jsx";
import ProtectedRoute from "./components/ProtectedRoute.jsx";

// 랜딩 라우트는 정적으로 유지한다 — 가장 흔한 진입점에서 청크 왕복을 한 번 더 두지 않기 위함.
// AuthPage 도 ProtectedRoute 가 비로그인 fallback 으로 직접 렌더링하므로 진입 청크에 남는다.
import UploadPage from "./pages/UploadPage.jsx";
import AuthPage from "./pages/AuthPage.jsx";

const DashboardPage = lazy(() => import("./pages/DashboardPage.jsx"));
const PaymentPage = lazy(() => import("./pages/PaymentPage.jsx"));
const AdminLogin = lazy(() => import("./pages/AdminLogin.jsx"));
const AdminDashboard = lazy(() => import("./pages/AdminDashboard.jsx"));
const DeveloperPage = lazy(() => import("./pages/DeveloperPage.jsx"));
const JobsPage = lazy(() => import("./pages/JobsPage.jsx"));
const JobConfirmPage = lazy(() => import("./pages/JobConfirmPage.jsx"));
const JobResultPage = lazy(() => import("./pages/JobResultPage.jsx"));
const SettingsPage = lazy(() => import("./pages/SettingsPage.jsx"));
const LegalTermsPage = lazy(() => import("./pages/LegalTermsPage.jsx"));
const LegalPrivacyPage = lazy(() => import("./pages/LegalPrivacyPage.jsx"));
const LegalRefundPage = lazy(() => import("./pages/LegalRefundPage.jsx"));
const PricePage = lazy(() => import("./pages/PricePage.jsx"));
const ApiPricingPage = lazy(() => import("./pages/ApiPricingPage.jsx"));
const DevEdiscoveryPage = lazy(() => import("./pages/DevEdiscoveryPage.jsx"));
const DevEdiscoveryTimelinePage = lazy(() => import("./pages/DevEdiscoveryTimelinePage.jsx"));
const DebugMarkdownAgentPage = lazy(() => import("./pages/DebugMarkdownAgentPage.jsx"));
const DebugHighlightCoordsPage = lazy(() => import("./pages/DebugHighlightCoordsPage.jsx"));
const DebugPanelTogglePage = lazy(() => import("./pages/DebugPanelTogglePage.jsx"));

// 개발 환경에서 전역 dev mock 활성화 — /dev/* 및 /jobs/:jobId 경로 모두 샘플 데이터로 UI 테스트 가능.
// production 빌드에서는 import.meta.env.DEV가 false이므로 무시된다.
if (import.meta.env.DEV) {
  enableDevMock(true);
}

/** 라우트 청크를 내려받는 동안 표시할 전체 화면 스피너. ProtectedRoute 의 로딩 상태와 형태를 맞춘다. */
function RouteFallback() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center" data-oid="route-loading">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" data-oid="route-spinner"></div>
    </div>);

}

const rootEl = document.getElementById("root");
ReactDOM.createRoot(rootEl).render(
  <React.StrictMode data-oid="6kqspej">
    <I18nextProvider i18n={i18n} data-oid="53d8vza">
      <LanguageProvider data-oid="1e:x9zs">
        <AuthProvider data-oid="xcbpezj">
          <BrowserRouter data-oid="j3r-hj3">
            <Suspense fallback={<RouteFallback data-oid="route-fallback" />} data-oid="route-suspense">
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

              {/* 디버그 전용 라우트 — 에이전트 도구로 마크다운 수정 반영 문제 진단 */}
              <Route
                path="/dev/debug-markdown-agent"
                element={<DebugMarkdownAgentPage data-oid="debug-markdown-agent-route" />}
                data-oid="debug-markdown-agent-route-r" />

              {/* 디버그 전용 라우트 — 스캔 PDF 하이라이트 좌표 어긋남 진단 (로그인 우회) */}
              <Route
                path="/dev/debug-highlight-coords"
                element={<DebugHighlightCoordsPage data-oid="debug-highlight-coords-route" />}
                data-oid="debug-highlight-coords-route-r" />

              {/* 디버그 전용 라우트 — 마크다운 페이지 패널 보이기/숨기기 완전 숨김 문제 진단 (로그인 우회) */}
              <Route
                path="/dev/debug-panel-toggle"
                element={<DebugPanelTogglePage data-oid="debug-panel-toggle-route" />}
                data-oid="debug-panel-toggle-route-r" />

            </Routes>
            </Suspense>
          <CookieConsent data-oid="cookie_consent" />
          </BrowserRouter>
        </AuthProvider>
      </LanguageProvider>
    </I18nextProvider>
  </React.StrictMode>
);
