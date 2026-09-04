// [Flow: Step 1 (로그인 확인) -> Step 2 (중앙 UploadWidget 렌더링) -> Step 3 (UploadWidget에서 init -> TUS 업로드 -> create) -> Step 4 (비용 확인 페이지 이동)]
import { Suspense, lazy, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Loader2, LogIn } from "lucide-react";
import { useAuth } from "../AuthContext.jsx";
import { api } from "../api.js";
import GlobalFooter from "../components/GlobalFooter.jsx";
import Logo from "../components/Logo.jsx";
import UploadWidget from "../components/UploadWidget.jsx";

// 배경 장식용 WebGL 애니메이션. three + postprocessing 으로 brotli 141KB 라 정적 import 하면
// 랜딩 첫 페인트를 막는다. 콘텐츠와 무관한 장식이므로 lazy 로 분리하고 fallback 은 두지 않는다.
const GridScan = lazy(() => import("../components/GridScan.jsx"));

export default function UploadPage() {
  const { user, loading: authLoading } = useAuth();
  const { t } = useTranslation();
  const nav = useNavigate();
  const [profile, setProfile] = useState(null);

  useEffect(() => {
    if (!user) return;
    api.me().then(setProfile).catch(() => {});
  }, [user]);

  // [Flow: document capture 단계에서 드래그 기본 동작 차단 -> drop zone 밖/안 모두 브라우저가 파일 열지 않도록 설정]
  useEffect(() => {
    const preventDefault = (e) => { e.preventDefault(); };
    document.addEventListener("dragover", preventDefault, true);
    document.addEventListener("drop", preventDefault, true);
    return () => {
      document.removeEventListener("dragover", preventDefault, true);
      document.removeEventListener("drop", preventDefault, true);
    };
  }, []);

  function handleComplete(jobId) {
    nav(`/jobs/${jobId}/confirm`);
  }

  if (authLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center" data-oid="fb1q5zd">
        <Loader2 className="animate-spin text-primary" size={32} data-oid="ohz8:m:" />
      </div>);

  }

  return (
    <div className="min-h-screen bg-background text-on-background flex flex-col overflow-x-hidden" data-oid="23_u4l8">
      <nav className="w-full bg-transparent" data-oid="i7-y4-o">
        <div className="max-w-container-max mx-auto flex justify-between items-center h-16 md:h-20 px-margin-mobile md:px-gutter" data-oid="2gdjtc9">
          <div className="flex items-center gap-2" data-oid="ro0013g">
            <Logo height="44px" data-oid="9p74bh1" />
          </div>
          <div className="flex items-center gap-3 md:gap-6" data-oid="azbdxm0">
            <Link
              to="/price"
              className="text-body-md text-on-surface-variant hover:text-primary transition-colors font-medium"
              data-oid="upload-price-link"
            >
              {t("page:upload.price")}
            </Link>
            {user ?
            <>
                <Link
                to="/dashboard"
                className="text-body-md text-on-surface-variant hover:text-primary transition-colors font-medium hidden sm:inline" data-oid="hxfwqj4">

                  {t("page:upload.myJobs")}
                </Link>
                <Link
                to="/price"
                className="text-body-md flex items-center gap-1 text-primary hover:underline font-medium" data-oid="j8k1rq5">
                  {profile?.subscription?.plan?.toUpperCase() ?? "Free"}{" "}
                  <span className="hidden sm:inline">{t("page:upload.plan")}</span>
                </Link>
              </> :

            <Link
              to="/login"
              className="text-body-md flex items-center gap-1 text-on-surface-variant hover:text-primary transition-colors font-medium" data-oid="4bqhh5q">

                <LogIn size={18} data-oid="n24csz4" /> <span className="hidden sm:inline">{t("common:auth.login")}</span>
              </Link>
            }
          </div>
        </div>
      </nav>

      <main className="flex-grow flex flex-col items-center justify-center relative pb-20 overflow-hidden" data-oid="hukjmb5">
        <div className="absolute inset-0 z-0" data-oid="6iwhhjt">
          <Suspense fallback={null} data-oid="gridscan-suspense">
          <GridScan
            sensitivity={0.55}
            lineThickness={1}
            linesColor="#2f293a"
            gridScale={0.1}
            lineJitter={0}
            scanColor="#3b82f6"
            scanOpacity={0.4}
            scanGlow={0.5}
            scanSoftness={2}
            enablePost={false}
            chromaticAberration={0.002}
            noiseIntensity={0.01} data-oid="8h972jn" />

          </Suspense>
        </div>

        <div className="w-full max-w-3xl px-margin-mobile md:px-gutter text-center relative z-10" data-oid="t:1j9cg">
          <h1 className="text-3xl md:text-display font-display text-on-surface mb-4 tracking-tight" data-oid="icit2z9">
            <span className="text-primary" data-oid="9zubavq">{t("page:upload.title")}</span>
          </h1>
          <p className="text-body-md md:text-body-lg text-on-surface-variant mb-8 md:mb-12 opacity-80" data-oid="0lczkhk">
            {t("page:upload.subtitle")}
          </p>

          <UploadWidget onComplete={handleComplete} data-oid="upload-page-widget" />

          <div className="mt-8 flex flex-col md:flex-row justify-center gap-4 md:gap-8 text-label-sm text-outline font-medium uppercase tracking-widest opacity-60" data-oid="10-kc.x">
            <span className="flex items-center gap-1.5" data-oid="dtoqnz9">
              <span className="text-sm" data-oid="bqnxyd_">{t("page:upload.badgeSecurity")}</span>{" "}
              {t("page:upload.badgeEncrypted")}
            </span>
            <span className="flex items-center gap-1.5" data-oid="1ob4op1">
              <span className="text-sm" data-oid="mfc0llf">{t("page:upload.badgeInstant")}</span>{" "}
              {t("page:upload.badgeProcessing")}
            </span>
            <span className="flex items-center gap-1.5" data-oid="q6ff538">
              {" "}
              {t("page:upload.badgeLanguages")}
            </span>
          </div>
        </div>
      </main>

      <GlobalFooter />
    </div>);

}