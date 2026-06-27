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
    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session);
      setUser(session?.user ?? null);
      setLoading(false);
    });

    const { data: listener } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        setSession(session);
        setUser(session?.user ?? null);
      },
    );

    return () => listener.subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (!session?.access_token) return;
    api
      .me()
      .then((profile) => {
        if (profile?.language) {
          setLanguage(profile.language);
        }
      })
      .catch(() => {});
  }, [session, setLanguage]);

  const signIn = (email, password) =>
    supabase.auth.signInWithPassword({ email, password });
  const signUp = (email, password) => supabase.auth.signUp({ email, password });
  const signOut = () => supabase.auth.signOut();

  return (
    <AuthContext.Provider
      value={{ user, session, loading, signIn, signUp, signOut }}
      data-oid="-hsew:k"
    >
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
