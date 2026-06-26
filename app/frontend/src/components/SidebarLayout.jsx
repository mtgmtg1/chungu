// [Flow: Step 1 (현재 경로 확인) -> Step 2 (사이드바 토글 상태) -> Step 3 (네비게이션 렌더링) -> Step 4 (메인/푸터 콘텐츠 렌더링)]
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Menu, X, LogOut } from "lucide-react";
import { useAuth } from "../AuthContext.jsx";
import LanguageSelector from "./LanguageSelector.jsx";

const getNavItems = (t) => [
  { icon: "dashboard", label: t("nav.dashboard"), href: "/dashboard" },
  { icon: "list_alt", label: t("nav.jobs"), href: "/jobs" },
  { icon: "code", label: t("nav.developer"), href: "/developer" },
  { icon: "settings", label: t("nav.settings"), href: "/settings" },
];

export default function SidebarLayout({ children, title, subtitle }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { user, signOut } = useAuth();
  const { t } = useTranslation();
  const navItems = getNavItems(t);
  const [expanded, setExpanded] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 768) {
        setExpanded(false);
        setMobileOpen(false);
      } else {
        setExpanded(true);
      }
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const sidebarWidth = expanded ? "w-64" : "w-20";
  const marginLeft = expanded ? "ml-64" : "ml-20";
  const headerWidth = expanded ? "w-[calc(100%-16rem)]" : "w-[calc(100%-5rem)]";

  function isActive(href) {
    if (href === "#") return false;
    return pathname === href || pathname.startsWith(`${href}/`);
  }

  return (
    <div
      className="min-h-screen bg-background text-on-background"
      data-oid="753fvgs"
    >
      {/* Mobile toggle */}
      <button
        onClick={() => setMobileOpen(!mobileOpen)}
        className="md:hidden fixed top-4 left-4 z-50 p-2 bg-surface rounded-lg shadow-sm border border-outline-variant"
        data-oid="6q9910b"
      >
        {mobileOpen ? (
          <X size={20} data-oid="3fp_vil" />
        ) : (
          <Menu size={20} data-oid="g:nw01q" />
        )}
      </button>

      {/* Sidebar */}
      <aside
        className={`h-screen fixed left-0 top-0 bg-surface/90 backdrop-blur-xl border-r border-outline-variant z-40 flex flex-col py-6 px-4 transition-all duration-300 ${sidebarWidth} ${mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}`}
        data-oid="midi.61"
      >
        <div
          className={`flex items-center gap-3 mb-10 px-2 ${expanded ? "" : "justify-center"}`}
          data-oid="ppczdj4"
        >
          <div
            className="w-10 h-10 bg-primary rounded-lg flex items-center justify-center shrink-0"
            data-oid="uriebet"
          >
            <span
              className="material-symbols-outlined text-white text-xl"
              data-oid="l:2o0-f"
            >
              dataset
            </span>
          </div>
          {expanded && (
            <div data-oid="oj8_5e0">
              <h1
                className="font-headline-md text-headline-md font-bold text-primary leading-tight"
                data-oid="l6:0dxe"
              >
                Chungu
              </h1>
              <p
                className="text-[10px] uppercase tracking-widest text-outline"
                data-oid="y16.mk2"
              >
                Precision Data
              </p>
            </div>
          )}
        </div>

        <nav className="flex-1 space-y-1" data-oid=":zmuf-7">
          {navItems.map((item) => (
            <Link
              key={item.label}
              to={item.href}
              onClick={(e) => {
                if (item.href === "#") {
                  e.preventDefault();
                  return;
                }
                setMobileOpen(false);
              }}
              className={`flex items-center ${expanded ? "gap-3 px-3" : "justify-center px-2"} py-2.5 rounded-lg transition-colors ${
                isActive(item.href)
                  ? "text-primary font-bold border-r-2 border-primary bg-primary-container/5"
                  : "text-on-surface-variant hover:bg-primary-container/10"
              }`}
              title={!expanded ? item.label : ""}
              data-oid="s03277k"
            >
              <span
                className="material-symbols-outlined text-xl"
                data-oid="v0va-gq"
              >
                {item.icon}
              </span>
              {expanded && (
                <span className="font-body-md text-body-md" data-oid="tyv97:d">
                  {item.label}
                </span>
              )}
            </Link>
          ))}
        </nav>

        <div className="mt-auto space-y-3" data-oid="qoyfcao">
          <Link
            to="/"
            className={`w-full bg-primary text-on-primary py-3 px-4 rounded-xl font-body-md text-body-md font-medium shadow-md hover:opacity-90 active:scale-[0.98] transition-all flex items-center justify-center gap-2 ${expanded ? "" : "px-0"}`}
            data-oid="j1s28d_"
          >
            <span className="material-symbols-outlined" data-oid="ekg0.7:">
              add
            </span>
            {expanded && t("nav.newConversion")}
          </Link>

          {expanded && user && (
            <div
              className="p-4 glass-panel rounded-xl border border-primary/10"
              data-oid="-kobtwx"
            >
              <p
                className="font-label-sm text-label-sm text-on-surface-variant mb-2"
                data-oid="ufa:dal"
              >
                {t("nav.loggedInAs")}
              </p>
              <p
                className="text-xs text-on-surface truncate"
                data-oid="v.fnv0e"
              >
                {user.email}
              </p>
              <button
                onClick={() => signOut()}
                className="mt-2 w-full flex items-center justify-center gap-1 text-xs text-outline hover:text-error transition-colors"
                data-oid="pc:j_41"
              >
                <LogOut size={14} data-oid="t6fs.3r" />
                {t("nav.logout")}
              </button>
            </div>
          )}
        </div>
      </aside>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/20 z-30 md:hidden"
          onClick={() => setMobileOpen(false)}
          data-oid="q:99yo7"
        />
      )}

      {/* Desktop toggle button */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="hidden md:flex fixed bottom-6 left-4 z-50 w-8 h-8 items-center justify-center rounded-full bg-surface border border-outline-variant shadow-sm hover:bg-surface-container-high transition-colors"
        title={expanded ? t("nav.collapse") : t("nav.expand")}
        data-oid="jr0a4-s"
      >
        <span
          className="material-symbols-outlined text-sm text-outline"
          data-oid="l5w.jra"
        >
          {expanded ? "chevron_left" : "chevron_right"}
        </span>
      </button>

      {/* Top header */}
      <header
        className={`fixed top-0 right-0 ${headerWidth} z-30 bg-surface/80 backdrop-blur-md border-b border-outline-variant flex justify-end items-center h-16 px-gutter transition-all duration-300 ${marginLeft}`}
        data-oid="mi46pcs"
      >
        <div className="flex items-center gap-6" data-oid="4fa1dqn">
          <div
            className="flex items-center gap-4 text-on-surface-variant"
            data-oid="l616:4m"
          >
            <span
              className="material-symbols-outlined cursor-pointer hover:text-primary transition-colors"
              data-oid="74n3_0v"
            >
              account_balance_wallet
            </span>
          </div>
          <LanguageSelector data-oid="o3yu0x8" />
          <div
            className="w-8 h-8 rounded-full bg-primary-fixed-dim border border-primary/20 flex items-center justify-center overflow-hidden"
            data-oid="-q7zoqr"
          >
            <span
              className="material-symbols-outlined text-primary text-sm"
              data-oid=":99awl:"
            >
              person
            </span>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main
        className={`pt-16 min-h-screen transition-all duration-300 ${marginLeft}`}
        data-oid="1qpp_xs"
      >
        <div
          className="max-w-container-max mx-auto px-margin-desktop py-stack-lg"
          data-oid="f2mshjx"
        >
          {(title || subtitle) && (
            <div
              className="flex flex-col md:flex-row md:items-end justify-between gap-gutter mb-stack-lg"
              data-oid="o:4l5bk"
            >
              <div data-oid="-e-_dy.">
                {title && (
                  <h2
                    className="font-headline-lg text-headline-lg text-on-surface mb-2"
                    data-oid="77ggpk6"
                  >
                    {title}
                  </h2>
                )}
                {subtitle && (
                  <p
                    className="text-on-surface-variant text-body-md"
                    data-oid="6mc8znn"
                  >
                    {subtitle}
                  </p>
                )}
              </div>
            </div>
          )}
          {children}
        </div>
      </main>

      {/* Footer */}
      <footer
        className={`bg-surface border-t border-outline-variant py-stack-md transition-all duration-300 ${marginLeft}`}
        data-oid="jipo8u2"
      >
        <div
          className="max-w-container-max mx-auto flex flex-col md:flex-row justify-between items-center px-margin-desktop"
          data-oid="9:r6-xs"
        >
          <p
            className="font-label-sm text-label-sm text-on-surface-variant"
            data-oid="q74cva4"
          >
            {t("app.copyright")}
          </p>
          <div className="flex gap-6 mt-4 md:mt-0" data-oid="tvo3ycw">
            <a
              href="#"
              className="font-label-sm text-label-sm text-on-surface-variant hover:underline decoration-primary"
              data-oid="g9st204"
            >
              {t("footer.privacy")}
            </a>
            <a
              href="#"
              className="font-label-sm text-label-sm text-on-surface-variant hover:underline decoration-primary"
              data-oid="fhgvfmb"
            >
              {t("footer.terms")}
            </a>
            <a
              href="#"
              className="font-label-sm text-label-sm text-on-surface-variant hover:underline decoration-primary"
              data-oid="wgqqfpx"
            >
              {t("footer.apiDocs")}
            </a>
            <a
              href="#"
              className="font-label-sm text-label-sm text-on-surface-variant hover:underline decoration-primary"
              data-oid="als.blu"
            >
              {t("footer.contact")}
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
