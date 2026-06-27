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
  <React.StrictMode data-oid="6kqspej">
    <I18nextProvider i18n={i18n} data-oid="53d8vza">
      <LanguageProvider data-oid="1e:x9zs">
        <AuthProvider data-oid="xcbpezj">
          <BrowserRouter data-oid="j3r-hj3">
            <Routes data-oid="sza8yga">
              <Route
                path="/"
                element={<UploadPage data-oid="tyuzd8m" />}
                data-oid="f4q43vu"
              />

              <Route
                path="/login"
                element={<AuthPage data-oid="fgx:gn0" />}
                data-oid="xouxlfl"
              />

              <Route
                path="/dashboard"
                element={<DashboardPage data-oid="_9w:9za" />}
                data-oid="ff86bvq"
              />

              <Route
                path="/jobs"
                element={<JobsPage data-oid="fclppvc" />}
                data-oid="i8jaj__"
              />

              <Route
                path="/payment"
                element={<PaymentPage data-oid="45vjc9v" />}
                data-oid="oozoys2"
              />

              <Route
                path="/developer"
                element={<DeveloperPage data-oid="vxyzmzt" />}
                data-oid="bomn0fs"
              />

              <Route
                path="/jobs/:jobId/confirm"
                element={<JobConfirmPage data-oid="tsroq7p" />}
                data-oid="5dy2wet"
              />

              <Route
                path="/jobs/:jobId"
                element={<JobResultPage data-oid="rc_ef71" />}
                data-oid="_m5xc0o"
              />

              <Route
                path="/settings"
                element={<SettingsPage data-oid="aw8n85r" />}
                data-oid="2uu7w76"
              />

              <Route
                path="/admin/login"
                element={<AdminLogin data-oid="iu9rdhq" />}
                data-oid="lgus3p2"
              />

              <Route
                path="/admin"
                element={<AdminDashboard data-oid="kl1-:.8" />}
                data-oid="3mpq7x5"
              />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </LanguageProvider>
    </I18nextProvider>
  </React.StrictMode>,
);
