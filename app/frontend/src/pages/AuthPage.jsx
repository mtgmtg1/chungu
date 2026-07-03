// [Flow: Step 1 (이메일/비번 입력 + 비밀번호 강도 표시) -> Step 2 (Turnstile 검증) -> Step 3 (Supabase 로그인/회원가입) -> Step 4 (성공 시 루트 이동)]
import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Mail, Lock, Loader2, UserPlus, LogIn } from "lucide-react";
import { useAuth } from "../AuthContext.jsx";

const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || "";
const TURNSTILE_WORKER_URL = import.meta.env.VITE_TURNSTILE_WORKER_URL || "";

/**
 * Spin Worker 경유 Turnstile 토큰 검증.
 * 반환: true = 검증 통과, false = 검증 실패.
 */
async function verifyTurnstileWithWorker(token) {
  if (!TURNSTILE_WORKER_URL || !token) return true;
  try {
    const resp = await fetch(TURNSTILE_WORKER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    const data = await resp.json();
    return data.success === true;
  } catch {
    return false;
  }
}

/**
 * 비밀번호 강도 계산 함수.
 * 반환: {score: 0-4, label: "weak"|"medium"|"strong"}
 */
function calcPasswordStrength(password) {
  if (!password) return { score: 0, label: "" };
  let score = 0;
  if (password.length >= 8) score++;
  if (password.length >= 12) score++;
  const hasLower = /[a-z]/.test(password);
  const hasUpper = /[A-Z]/.test(password);
  const hasDigit = /\d/.test(password);
  const hasSpecial = /[^a-zA-Z0-9]/.test(password);
  const types = [hasLower, hasUpper, hasDigit, hasSpecial].filter(Boolean).length;
  if (types >= 3) score++;
  if (types >= 4) score++;
  const label = score < 2 ? "weak" : score < 3 ? "medium" : "strong";
  return { score: Math.min(score, 4), label };
}

/**
 * Cloudflare Turnstile 위젯 컴포넌트.
 * onVerify 콜백으로 토큰을 전달, 만료 시 자동 갱신.
 */
function TurnstileWidget({ onVerify }) {
  const containerRef = useRef(null);
  const widgetIdRef = useRef(null);
  const callbackRef = useRef(onVerify);
  callbackRef.current = onVerify;

  const renderWidget = useCallback(() => {
    if (!containerRef.current || !window.turnstile) return;
    containerRef.current.innerHTML = "";
    widgetIdRef.current = window.turnstile.render(containerRef.current, {
      sitekey: TURNSTILE_SITE_KEY,
      action: "turnstile-spin-v1",
      callback: (token) => callbackRef.current(token),
      "expired-callback": () => callbackRef.current(""),
      "error-callback": () => callbackRef.current(""),
      theme: "light",
    });
  }, []);

  useEffect(() => {
    if (!TURNSTILE_SITE_KEY) {
      onVerify("");
      return;
    }
    if (window.turnstile) {
      renderWidget();
    } else {
      const script = document.createElement("script");
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      script.async = true;
      script.defer = true;
      script.onload = () => renderWidget();
      document.head.appendChild(script);
    }
    return () => {
      if (widgetIdRef.current && window.turnstile) {
        window.turnstile.remove(widgetIdRef.current);
      }
    };
  }, [renderWidget, onVerify]);

  if (!TURNSTILE_SITE_KEY) return null;
  return <div ref={containerRef} className="flex justify-center" data-oid="ts-w1" />;
}

export default function AuthPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [signupSuccess, setSignupSuccess] = useState(false);
  const [turnstileToken, setTurnstileToken] = useState("");
  const nav = useNavigate();
  const { t } = useTranslation();
  const { signIn, signUp } = useAuth();

  const strength = calcPasswordStrength(password);
  const strengthColors = { weak: "bg-red-500", medium: "bg-yellow-500", strong: "bg-green-500" };
  const strengthLabels = { weak: t("page:auth.passwordWeak"), medium: t("page:auth.passwordMedium"), strong: t("page:auth.passwordStrong") };
  const canSubmit = !isSignUp || strength.score >= 2;

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const verified = await verifyTurnstileWithWorker(turnstileToken);
      if (!verified) {
        setError(t("page:auth.captchaFailed"));
        return;
      }
      if (isSignUp) {
        const { error } = await signUp(email, password, turnstileToken);
        if (error) throw error;
        setSignupSuccess(true);
      } else {
        const { error } = await signIn(email, password, turnstileToken);
        if (error) throw error;
        nav("/");
      }
    } catch (e) {
      // 429 Too Many Requests / 403 CAPTCHA / 남은 시도 횟수 처리
      const msg = e?.message || "";
      const remaining = e?.remaining_attempts ?? e?.context?.remaining_attempts;
      if (msg.includes("too_many_attempts") || msg.includes("429")) {
        setError(t("page:auth.tooManyAttempts"));
      } else if (msg.includes("captcha_failed") || msg.includes("403")) {
        setError(t("page:auth.captchaFailed"));
      } else if (remaining != null && remaining <= 7) {
        setError(t("page:auth.loginFailedWithRemaining", { remaining }));
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center bg-slate-50"
      data-oid="yel_p-w">

      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-xl shadow-sm border p-6 w-full max-w-sm space-y-4"
        data-oid="xpfks5y">

        <div className="text-center" data-oid="d46vz5f">
          {isSignUp ?
          <UserPlus
            className="mx-auto text-blue-600 mb-2"
            data-oid="kfkwh8:" /> :


          <LogIn className="mx-auto text-blue-600 mb-2" data-oid="2p:4802" />
          }
          <h1 className="text-base font-bold" data-oid="pr:mnop">
            {isSignUp ? t("page:auth.signupTitle") : t("page:auth.loginTitle")}
          </h1>
          <p className="text-sm text-slate-500 mt-1" data-oid="q2apom4">
            {t("page:auth.loginSubtitle")}
          </p>
        </div>

        <div className="relative" data-oid="vw6ih8y">
          <Mail
            className="absolute left-3 top-2 text-slate-400"
            size={16}
            data-oid="pksi5kx" />


          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={t("page:auth.emailPlaceholder")}
            className="w-full border rounded-lg pl-10 pr-3 py-2"
            required
            data-oid="li.23zo" />

        </div>
        <div className="relative" data-oid="xlxabbb">
          <Lock
            className="absolute left-3 top-2 text-slate-400"
            size={16}
            data-oid="ggti-5r" />


          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={t("page:auth.passwordPlaceholder")}
            className="w-full border rounded-lg pl-10 pr-3 py-1.5"
            required
            data-oid="q683z2v" />

        </div>

        {isSignUp && password && (
          <div className="space-y-1" data-oid="pw-str">
            <div className="flex gap-1" data-oid="pw-bar">
              {[1, 2, 3, 4].map((n) => (
                <div
                  key={n}
                  className={`h-1 flex-1 rounded ${n <= strength.score ? strengthColors[strength.label] : "bg-slate-200"}`}
                  data-oid={`pw-bar-${n}`}
                />
              ))}
            </div>
            <p className="text-xs text-slate-500" data-oid="pw-label">
              {strengthLabels[strength.label]}
            </p>
          </div>
        )}

        <TurnstileWidget onVerify={setTurnstileToken} />

        {signupSuccess && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 space-y-2" data-oid="signup-ok">
            <p className="text-green-800 text-sm font-medium" data-oid="signup-ok-title">
              {t("page:auth.signupSuccessTitle")}
            </p>
            <p className="text-green-700 text-sm" data-oid="signup-ok-body">
              {t("page:auth.signupSuccessBody")}
            </p>
            <p className="text-amber-700 text-xs flex items-start gap-1.5" data-oid="signup-ok-spam">
              <span data-oid="spam-icon">⚠️</span>
              {t("page:auth.signupSpamNotice")}
            </p>
          </div>
        )}

        {error &&
        <p className="text-red-600 text-sm" data-oid="h7krp8j">
            {error}
          </p>
        }

        <button
          type="submit"
          disabled={loading || !canSubmit}
          className="w-full bg-blue-600 text-white rounded-lg py-2 font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2"
          data-oid="uxs79pg">

          {loading ?
          <Loader2 className="animate-spin" size={18} data-oid="rxx5uwq" /> :
          isSignUp ?
          t("page:auth.signupButton") :

          t("page:auth.loginButton")
          }
        </button>

        <div className="text-center text-sm text-slate-500" data-oid="ec952ox">
          {isSignUp ? t("page:auth.haveAccount") : t("page:auth.noAccount")}{" "}
          <button
            type="button"
            onClick={() => { setIsSignUp(!isSignUp); setSignupSuccess(false); setError(""); }}
            className="text-blue-600 hover:underline"
            data-oid="l3vfmri">

            {isSignUp ? t("page:auth.loginLink") : t("page:auth.signupLink")}
          </button>
        </div>

        <p className="text-xs text-center text-slate-400" data-oid="mpy46--">
          <Link
            to="/admin/login"
            className="hover:underline"
            data-oid="t3kpkfp">

            {t("page:auth.adminLogin")}
          </Link>
        </p>
      </form>
    </div>);

}