// [Flow: Step 1 (Supabase session 구독) -> Step 2 (로그인/로그아웃/회원가입 함수) -> Step 3 (Context 제공)]
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { supabase } from "./supabase.js";
import { api, enableDevMock } from "./api.js";
import { useLanguage } from "./LanguageContext.jsx";
import { MOCK_DEV_SESSION } from "./dev/mockUser.js";
import DevBypassBanner from "./components/DevBypassBanner.jsx";

const DEV_SESSION_TIMEOUT_MS = 1000;

const AuthContext = createContext(null);

/** [Flow: 개발 환경에서 localStorage에 저장된 dev bypass session 복원]
    VITE_DEV_BYPASS_EMAIL/PASSWORD가 설정되어 있으면 실제 Supabase Auth를 사용하므로
    저장된 dev bypass 토큰은 무시한다. */
function _loadDevSession() {
  if (!import.meta.env.DEV) return null;
  if (import.meta.env.VITE_DEV_BYPASS_EMAIL && import.meta.env.VITE_DEV_BYPASS_PASSWORD) return null;
  const token = localStorage.getItem("dev_access_token");
  if (!token) return null;
  try {
    const user = JSON.parse(localStorage.getItem("dev_user") || "null");
    return {
      user,
      access_token: token,
      refresh_token: localStorage.getItem("dev_refresh_token") || "",
    };
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const devSession = _loadDevSession();
  const [user, setUser] = useState(() => devSession?.user ?? (import.meta.env.DEV ? MOCK_DEV_SESSION.user : null));
  const [session, setSession] = useState(() => devSession ?? (import.meta.env.DEV ? MOCK_DEV_SESSION : null));
  const [loading, setLoading] = useState(true);
  const [devBypassMode, setDevBypassMode] = useState(() => {
    if (!import.meta.env.DEV) return null;
    return localStorage.getItem("dev_bypass_mode") || "mock";
  });
  const { setLanguage } = useLanguage();

  const devBypassModeRef = useRef(devBypassMode);
  useEffect(() => {
    devBypassModeRef.current = devBypassMode;
  }, [devBypassMode]);

  useEffect(() => {
    let mounted = true;

    const sessionPromise = import.meta.env.DEV
      ? Promise.race([
          supabase.auth.getSession(),
          new Promise((resolve) =>
            setTimeout(() => resolve({ data: { session: null } }), DEV_SESSION_TIMEOUT_MS)
          ),
        ])
      : supabase.auth.getSession();

    sessionPromise.then(async ({ data: { session: initialSession } }) => {
      let session = initialSession;
      let mode = import.meta.env.DEV ? "apikey" : null;

      if (initialSession && import.meta.env.DEV) {
        // 실제 세션이 있으면 mock을 대체합니다.
        mode = null;
        enableDevMock(false);
      } else if (!session && import.meta.env.DEV) {
        console.log("[DEV auto-login] /api/dev/login 개발 bypass 시도");
        // 개발 모드 자동 로그인: 로컬 백엔드 bypass 사용
        try {
          const resp = await fetch(`${window.location.origin}/api/dev/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
          });
          if (resp.ok) {
            const devData = await resp.json();
            // 로컬 개발 환경에서는 Supabase auth 엔드포인트가 없으므로,
            // dev bypass 토큰을 직접 세션처럼 사용하고 API key로 백엔드에 연결한다.
            // api.js의 getToken()이 이 토큰을 Authorization 헤더에 넣을 수 있도록 localStorage에 저장한다.
            localStorage.setItem("dev_access_token", devData.access_token);
            localStorage.setItem("dev_refresh_token", devData.refresh_token);
            localStorage.setItem("dev_user", JSON.stringify(devData.user));
            localStorage.setItem("dev_bypass_mode", "apikey");
            session = {
              user: devData.user,
              access_token: devData.access_token,
              refresh_token: devData.refresh_token,
            };
            mode = "apikey";
            enableDevMock(false);
            console.log("[DEV auto-login] 성공:", devData.user?.email);
          } else {
            const errText = await resp.text();
            console.warn("[DEV auto-login] 실패:", errText);
          }
        } catch (e) {
          console.warn("[DEV auto-login] 실패:", e.message);
        }

        // 백엔드 bypass가 없으면 mock 사용자 + mock API 전환으로 UI 독립 테스트
        if (!session) {
          localStorage.setItem("dev_bypass_mode", "mock");
          session = MOCK_DEV_SESSION;
          mode = "mock";
          enableDevMock(true);
        }
      }

      if (mounted) {
        setSession(session);
        setUser(session?.user ?? null);
        setDevBypassMode(mode);
        devBypassModeRef.current = mode;
        setLoading(false);
      }
    });

    const { data: listener } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        // mock 모드에서는 Supabase의 null 세션(로그아웃) 이벤트만 무시합니다.
        // 수동 로그인 시 실제 세션으로 전환되어야 합니다.
        if ((devBypassModeRef.current === "mock" || devBypassModeRef.current === "apikey") && !session) return;
        setSession(session);
        setUser(session?.user ?? null);
        if (!session) {
          setDevBypassMode(null);
          enableDevMock(false);
        }
      }
    );

    return () => {
      mounted = false;
      listener.subscription.unsubscribe();
    };
  }, []);

  useEffect(() => {
    if (!session?.access_token) return;
    api.
    me().
    then((profile) => {
      if (profile?.language) {
        setLanguage(profile.language);
      }
    }).
    catch(() => {});
  }, [session, setLanguage]);

  const signIn = (email, password, turnstileToken = "") =>
    supabase.auth.signInWithPassword({
      email,
      password,
      options: { captchaToken: turnstileToken },
    });
  const signUp = (email, password, turnstileToken = "") =>
    supabase.auth.signUp({
      email,
      password,
      options: { captchaToken: turnstileToken },
    });
  const signOut = () => supabase.auth.signOut();

  return (
    <AuthContext.Provider
      value={{ user, session, loading, signIn, signUp, signOut, devBypassMode }}
      data-oid="-hsew:k">
      {devBypassMode === "mock" && <DevBypassBanner mode={devBypassMode} />}
      {children}
    </AuthContext.Provider>);

}

export const useAuth = () => useContext(AuthContext);