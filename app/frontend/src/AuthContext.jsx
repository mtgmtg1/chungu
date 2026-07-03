// [Flow: Step 1 (Supabase session 구독) -> Step 2 (로그인/로그아웃/회원가입 함수) -> Step 3 (Context 제공)]
import { createContext, useContext, useEffect, useState } from "react";
import { supabase } from "./supabase.js";
import { api } from "./api.js";
import { useLanguage } from "./LanguageContext.jsx";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const { setLanguage } = useLanguage();

  useEffect(() => {
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      if (!session && import.meta.env.DEV) {
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
              console.log("[DEV auto-login] 성공:", session?.user?.email);
            }
          } else {
            const errText = await resp.text();
            console.warn("[DEV auto-login] 실패:", errText);
          }
        } catch (e) {
          console.warn("[DEV auto-login] 실패:", e.message);
        }
      }
      setSession(session);
      setUser(session?.user ?? null);
      setLoading(false);
    });

    const { data: listener } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        setSession(session);
        setUser(session?.user ?? null);
      }
    );

    return () => listener.subscription.unsubscribe();
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
      value={{ user, session, loading, signIn, signUp, signOut }}
      data-oid="-hsew:k">

      {children}
    </AuthContext.Provider>);

}

export const useAuth = () => useContext(AuthContext);