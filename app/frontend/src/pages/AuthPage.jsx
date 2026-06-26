// [Flow: Step 1 (이메일/비번 입력) -> Step 2 (Supabase 로그인/회원가입) -> Step 3 (성공 시 루트 이동)]
import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Mail, Lock, Loader2, UserPlus, LogIn } from "lucide-react";
import { useAuth } from "../AuthContext.jsx";

export default function AuthPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const nav = useNavigate();
  const { t } = useTranslation();
  const { signIn, signUp } = useAuth();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (isSignUp) {
        const { error } = await signUp(email, password);
        if (error) throw error;
        setError(t("page:auth.checkEmail"));
      } else {
        const { error } = await signIn(email, password);
        if (error) throw error;
        nav("/");
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center bg-slate-50"
      data-oid="xl0d0nw"
    >
      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-xl shadow-sm border p-8 w-full max-w-sm space-y-5"
        data-oid="k1_sr7o"
      >
        <div className="text-center" data-oid="1sg10ao">
          {isSignUp ? (
            <UserPlus
              className="mx-auto text-blue-600 mb-2"
              data-oid="knh3-tg"
            />
          ) : (
            <LogIn className="mx-auto text-blue-600 mb-2" data-oid="il8dqy_" />
          )}
          <h1 className="text-lg font-bold" data-oid="dhzanyk">
            {isSignUp ? t("page:auth.signupTitle") : t("page:auth.loginTitle")}
          </h1>
          <p className="text-sm text-slate-500 mt-1" data-oid="e3eo.sm">
            {t("page:auth.loginSubtitle")}
          </p>
        </div>

        <div className="relative" data-oid="b1cenl6">
          <Mail
            className="absolute left-3 top-2.5 text-slate-400"
            size={18}
            data-oid="vs-1orz"
          />

          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={t("page:auth.emailPlaceholder")}
            className="w-full border rounded-lg pl-10 pr-3 py-2"
            required
            data-oid="8uv4y67"
          />
        </div>
        <div className="relative" data-oid="x.-i-3k">
          <Lock
            className="absolute left-3 top-2.5 text-slate-400"
            size={18}
            data-oid="n6vpg36"
          />

          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={t("page:auth.passwordPlaceholder")}
            className="w-full border rounded-lg pl-10 pr-3 py-2"
            required
            data-oid="wahv_09"
          />
        </div>

        {error && (
          <p className="text-red-600 text-sm" data-oid="prmb4kn">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 text-white rounded-lg py-2.5 font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2"
          data-oid="zpyirg6"
        >
          {loading ? (
            <Loader2 className="animate-spin" size={18} data-oid="wtb_28i" />
          ) : isSignUp ? (
            t("page:auth.signupButton")
          ) : (
            t("page:auth.loginButton")
          )}
        </button>

        <div className="text-center text-sm text-slate-500" data-oid="z5jmavg">
          {isSignUp ? t("page:auth.haveAccount") : t("page:auth.noAccount")}{" "}
          <button
            type="button"
            onClick={() => setIsSignUp(!isSignUp)}
            className="text-blue-600 hover:underline"
            data-oid="ocohejv"
          >
            {isSignUp ? t("page:auth.loginLink") : t("page:auth.signupLink")}
          </button>
        </div>

        <p className="text-xs text-center text-slate-400" data-oid="c2hy9s.">
          <Link
            to="/admin/login"
            className="hover:underline"
            data-oid="00zkvu5"
          >
            {t("page:auth.adminLogin")}
          </Link>
        </p>
      </form>
    </div>
  );
}
