// [Flow: Step 1 (이메일/비번 입력) -> Step 2 (Turnstile 검증) -> Step 3 (로그인 요청) -> Step 4 (성공 시 대시보드 이동)]
import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Lock, Loader2 } from "lucide-react";
import { api } from "../api.js";

const TURNSTILE_SITE_KEY = import.meta.env.VITE_TURNSTILE_SITE_KEY || "";

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
  return <div ref={containerRef} className="flex justify-center" data-oid="ts-adm" />;
}

export default function AdminLogin() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [turnstileToken, setTurnstileToken] = useState("");
  const nav = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.adminLogin(email, password, turnstileToken);
      nav("/admin");
    } catch (e) {
      const msg = e?.message || "";
      if (msg.includes("429") || msg.includes("너무 많습니다")) {
        setError(msg);
      } else if (msg.includes("403") || msg.includes("bot")) {
        setError("bot 확인에 실패했습니다. 다시 시도하세요.");
      } else if (msg.includes("남은 시도 횟수")) {
        setError(msg);
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center"
      data-oid="vcjtn4x">

      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-xl shadow-sm border p-6 w-full max-w-sm space-y-4"
        data-oid="ua4-gq-">

        <div className="text-center" data-oid="7k_y3d_">
          <Lock className="mx-auto text-blue-600 mb-2" size={20} data-oid="as4yzch" />
          <h1 className="text-base font-bold" data-oid="_jreo-v">
            관리자 로그인
          </h1>
        </div>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="이메일"
          className="w-full border rounded-lg px-3 py-1.5"
          data-oid="wsegj5g" />


        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="비밀번호"
          className="w-full border rounded-lg px-3 py-1.5"
          data-oid=":kgaarx" />


        <TurnstileWidget onVerify={setTurnstileToken} />

        {error &&
        <p className="text-red-600 text-sm" data-oid="nfc1c58">
            {error}
          </p>
        }
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 text-white rounded-lg py-2 font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2"
          data-oid="t5cjf98">

          {loading ?
          <Loader2 className="animate-spin" size={18} data-oid="mswupuq" /> :

          "로그인"
          }
        </button>
      </form>
    </div>);

}