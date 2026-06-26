import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { I18nextProvider } from "react-i18next";
import "./index.css";
import "./i18n.js";
import i18n from "./i18n.js";
import { AuthProvider } from "./AuthContext.jsx";
import { LanguageProvider } from "./LanguageContext.jsx";
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

const rootEl = document.getElementById("root");
ReactDOM.createRoot(rootEl).render(
  <React.StrictMode data-oid=":-kd.4e">
    <I18nextProvider i18n={i18n} data-oid="d-jpp:2">
      <LanguageProvider data-oid="y5_agxe">
        <AuthProvider data-oid="wbqnak2">
          <BrowserRouter data-oid="dmoh1tp">
            <Routes data-oid="kd_ocsj">
              <Route
                path="/"
                element={<UploadPage data-oid="d64s-t8" />}
                data-oid="5febmnc"
              />

              <Route
                path="/login"
                element={<AuthPage data-oid="mbkj9pk" />}
                data-oid="c9fw54o"
              />

              <Route
                path="/dashboard"
                element={<DashboardPage data-oid="0d3q6f0" />}
                data-oid="mqbzsq7"
              />

              <Route
                path="/jobs"
                element={<JobsPage data-oid="1.k1tr5" />}
                data-oid="iywmzle"
              />

              <Route
                path="/payment"
                element={<PaymentPage data-oid="orimftl" />}
                data-oid="eowox_u"
              />

              <Route
                path="/developer"
                element={<DeveloperPage data-oid="mfcyt-s" />}
                data-oid="0a9uvxy"
              />

              <Route
                path="/jobs/:jobId/confirm"
                element={<JobConfirmPage data-oid="vg-647f" />}
                data-oid="_9qisqj"
              />

              <Route
                path="/jobs/:jobId"
                element={<JobResultPage data-oid="fv53a--" />}
                data-oid="6bzq4oz"
              />

              <Route
                path="/settings"
                element={<SettingsPage data-oid="m0wxxim" />}
                data-oid="87c325g"
              />

              <Route
                path="/admin/login"
                element={<AdminLogin data-oid="i1wmdh4" />}
                data-oid="a85gt-k"
              />

              <Route
                path="/admin"
                element={<AdminDashboard data-oid="5csncnb" />}
                data-oid="fvmpdnh"
              />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </LanguageProvider>
    </I18nextProvider>
  </React.StrictMode>,
);
