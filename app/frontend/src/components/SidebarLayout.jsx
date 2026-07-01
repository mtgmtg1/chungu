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
{ icon: "settings", label: t("nav.settings"), href: "/settings" }];


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
      data-oid="yv-nffo">

      {/* Mobile toggle */}
      <button
        onClick={() => setMobileOpen(!mobileOpen)}
        className="md:hidden fixed top-4 left-4 z-50 p-2 bg-surface rounded-lg shadow-sm border border-outline-variant"
        data-oid="qa.mz63">

        {mobileOpen ?
        <X size={20} data-oid="1fxlpkz" /> :

        <Menu size={20} data-oid="x6.c6ax" />
        }
      </button>

      {/* Sidebar */}
      <aside
        className={`h-screen fixed left-0 top-0 bg-surface/90 backdrop-blur-xl border-r border-outline-variant z-40 flex flex-col py-5 px-3 transition-all duration-300 ${sidebarWidth} ${mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}`}
        data-oid=".ej7-3u">

        <div
          className={`flex items-center gap-3 mb-8 px-2 ${expanded ? "" : "justify-center"}`}
          data-oid="c3oet69">

          <div
            className="w-10 h-10 bg-primary rounded-lg flex items-center justify-center shrink-0"
            data-oid="mzxpvts">

            <span
              className="material-symbols-outlined text-white text-xl"
              data-oid="o7duxnm">

              dataset
            </span>
          </div>
          {expanded &&
          <div data-oid="dyteh.z">
              <h1
              className="font-headline-md text-headline-md font-bold text-primary leading-tight"
              data-oid="ejen81n">

                Chungu
              </h1>
              <p
              className="text-[10px] uppercase tracking-widest text-outline"
              data-oid="p30h3dl">

                Precision Data
              </p>
            </div>
          }
        </div>

        <nav className="flex-1 space-y-1" data-oid="92bcezw">
          {navItems.map((item) =>
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
            className={`flex items-center ${expanded ? "gap-3 px-3" : "justify-center px-2"} py-2 rounded-lg transition-colors ${
            isActive(item.href) ?
            "text-primary font-bold border-r-2 border-primary bg-primary-container/5" :
            "text-on-surface-variant hover:bg-primary-container/10"}`
            }
            title={!expanded ? item.label : ""}
            data-oid="9p1orsj">

              <span
              className="material-symbols-outlined text-xl"
              data-oid=".z19ygx">

                {item.icon}
              </span>
              {expanded &&
            <span className="font-body-md text-body-md" data-oid="xgrjj5v">
                  {item.label}
                </span>
            }
            </Link>
          )}
        </nav>

        <div className="mt-auto space-y-3" data-oid="3jg724x">
          <Link
            to="/"
            className={`w-full bg-primary text-on-primary py-2.5 px-3 rounded-xl font-body-md text-body-md font-medium shadow-md hover:opacity-90 active:scale-[0.98] transition-all flex items-center justify-center gap-2 ${expanded ? "" : "px-0"}`}
            data-oid="uu7qmwt">

            <span className="material-symbols-outlined" data-oid="jfz2785">
              add
            </span>
            {expanded && t("nav.newConversion")}
          </Link>

          {expanded && user &&
          <div
            className="p-3 glass-panel rounded-xl border border-primary/10"
            data-oid="0zn5l59">

              <p
              className="font-label-sm text-label-sm text-on-surface-variant mb-2"
              data-oid="5asenqn">

                {t("nav.loggedInAs")}
              </p>
              <p
              className="text-xs text-on-surface truncate"
              data-oid="qqmxnaj">

                {user.email}
              </p>
              <button
              onClick={() => signOut()}
              className="mt-2 w-full flex items-center justify-center gap-1 text-xs text-outline hover:text-error transition-colors"
              data-oid="fy:21t1">

                <LogOut size={14} data-oid=":nvrtmw" />
                {t("nav.logout")}
              </button>
            </div>
          }
        </div>
      </aside>

      {/* Mobile overlay */}
      {mobileOpen &&
      <div
        className="fixed inset-0 bg-black/20 z-30 md:hidden"
        onClick={() => setMobileOpen(false)}
        data-oid="t0.er7." />

      }

      {/* Desktop toggle button */}

      {/* Top header */}
      <header
        className={`fixed top-0 right-0 ${headerWidth} z-30 bg-surface/80 backdrop-blur-md border-b border-outline-variant flex justify-end items-center h-16 px-gutter transition-all duration-300 ${marginLeft}`}
        data-oid="1n8suzb">

        <button
          onClick={() => setExpanded(!expanded)}
          className="hidden md:flex left-4 z-50 w-8 h-8 items-center justify-center rounded-full bg-surface border border-outline-variant shadow-sm hover:bg-surface-container-high transition-colors"
          title={expanded ? t("nav.collapse") : t("nav.expand")}
          data-oid="cp23.9a">

          <span
            className="material-symbols-outlined text-sm text-outline"
            data-oid="6uvj_92">

            {expanded ? "chevron_left" : "chevron_right"}
          </span>
        </button>
        <div className="flex items-center gap-6" data-oid="89yal5:">
          <div
            className="flex items-center gap-4 text-on-surface-variant"
            data-oid="ti42x2k">

            <span
              className="material-symbols-outlined cursor-pointer hover:text-primary transition-colors"
              data-oid="nm0iqy5">

              account_balance_wallet
            </span>
          </div>
          <LanguageSelector data-oid="ezpxm7o" />
          <div
            className="w-8 h-8 rounded-full bg-primary-fixed-dim border border-primary/20 flex items-center justify-center overflow-hidden"
            data-oid="8h7cq3v">

            <span
              className="material-symbols-outlined text-primary text-sm"
              data-oid="zfsr4tc">

              person
            </span>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main
        className={`pt-16 min-h-screen transition-all duration-300 ${marginLeft}`}
        data-oid="h2incux">

        <div
          className="max-w-container-max mx-auto px-margin-desktop py-stack-lg"
          data-oid="6oyeknh">

          {(title || subtitle) &&
          <div
            className="flex flex-col md:flex-row md:items-end justify-between gap-gutter mb-stack-lg"
            data-oid="y8gf8g3">

              <div data-oid="3shaja0">
                {title &&
              <h2
                className="font-headline-lg text-headline-lg text-on-surface mb-2"
                data-oid="q2byt8v">

                    {title}
                  </h2>
              }
                {subtitle &&
              <p
                className="text-on-surface-variant text-body-md"
                data-oid="2x4hg-s">

                    {subtitle}
                  </p>
              }
              </div>
            </div>
          }
          {children}
        </div>
      </main>

      {/* Footer */}
      <footer
        className={`bg-surface border-t border-outline-variant py-stack-md transition-all duration-300 ${marginLeft}`}
        data-oid=":ds20xz">

        <div
          className="max-w-container-max mx-auto flex flex-col md:flex-row justify-between items-center px-margin-desktop"
          data-oid="e7uaoit">

          <p
            className="font-label-sm text-label-sm text-on-surface-variant"
            data-oid="88nq-e_">

            {t("app.copyright")}
          </p>
          <div className="flex gap-6 mt-4 md:mt-0" data-oid=":a7o.4l">
            <a
              href="#"
              className="font-label-sm text-label-sm text-on-surface-variant hover:underline decoration-primary"
              data-oid="pa-i9:r">

              {t("footer.privacy")}
            </a>
            <a
              href="#"
              className="font-label-sm text-label-sm text-on-surface-variant hover:underline decoration-primary"
              data-oid="jv62hqx">

              {t("footer.terms")}
            </a>
            <a
              href="#"
              className="font-label-sm text-label-sm text-on-surface-variant hover:underline decoration-primary"
              data-oid="m1qv9fr">

              {t("footer.apiDocs")}
            </a>
            <a
              href="#"
              className="font-label-sm text-label-sm text-on-surface-variant hover:underline decoration-primary"
              data-oid="x85euse">

              {t("footer.contact")}
            </a>
          </div>
        </div>
      </footer>
    </div>);

}