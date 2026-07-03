// [Flow: Step 1 (Supabase session 구독) -> Step 2 (로그인/로그아웃/회원가입 함수) -> Step 3 (Context 제공)]
import { createContext, useContext, useEffect, useRef, useState } from "react";
import { supabase } from "./supabase.js";
import { api, enableDevMock } from "./api.js";
import { useLanguage } from "./LanguageContext.jsx";
import { MOCK_DEV_SESSION } from "./dev/mockUser.js";
import DevBypassBanner from "./components/DevBypassBanner.jsx";

const DEV_SESSION_TIMEOUT_MS = 1000;

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => (import.meta.env.DEV ? MOCK_DEV_SESSION.user : null));
  const [session, setSession] = useState(() => (import.meta.env.DEV ? MOCK_DEV_SESSION : null));
  const [loading, setLoading] = useState(true);
  const [devBypassMode, setDevBypassMode] = useState(() => (import.meta.env.DEV ? "mock" : null));
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
      let mode = import.meta.env.DEV ? "mock" : null;

      if (initialSession && import.meta.env.DEV) {
        // 실제 세션이 있으면 mock을 대체합니다.
        mode = null;
        enableDevMock(false);
      } else if (!session && import.meta.env.DEV) {
        // 개발 모드 자동 로그인: 로컬 백엔드 bypass 사용
        try {
          const resp = await fetch(`${window.location.origin}/api/dev/login`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
          });
          if (resp.ok) {
            const devData = await resp.json();
            const { data: sessionData, error } = await supabase.auth.setSession({
              access_token: devData.access_token,
              refresh_token: devData.access_token,
            });
            if (error) {
              console.warn("[DEV auto-login] 세션 설정 실패:", error.message);
            } else {
              session = sessionData.session;
              mode = "backend";
              enableDevMock(false);
              console.log("[DEV auto-login] 성공:", session?.user?.email);
            }
          } else {
            const errText = await resp.text();
            console.warn("[DEV auto-login] 실패:", errText);
          }
        } catch (e) {
          console.warn("[DEV auto-login] 실패:", e.message);
        }

        // 백엔드가 없거나 DEV_BYPASS_AUTH가 비활성화면 mock 사용자로 전환
        if (!session) {
          session = MOCK_DEV_SESSION;
          mode = "mock";
          enableDevMock(true);
          console.log("[DEV mock] 백엔드 없이 mock 사용자로 전환");
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
        if (devBypassModeRef.current === "mock" && !session) return;
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