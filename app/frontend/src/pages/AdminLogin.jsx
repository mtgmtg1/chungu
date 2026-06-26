// [Flow: Step 1 (이메일/비번 입력) -> Step 2 (로그인 요청) -> Step 3 (성공 시 대시보드 이동)]
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Lock, Loader2 } from "lucide-react";
import { api } from "../api.js";

export default function AdminLogin() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const nav = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.adminLogin(email, password);
      nav("/admin");
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center"
      data-oid="-f-h2zf"
    >
      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-xl shadow-sm border p-8 w-full max-w-sm space-y-5"
        data-oid="4frnrcu"
      >
        <div className="text-center" data-oid="vo78wdy">
          <Lock className="mx-auto text-blue-600 mb-2" data-oid="ies5da7" />
          <h1 className="text-lg font-bold" data-oid=".8simvd">
            관리자 로그인
          </h1>
        </div>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="이메일"
          className="w-full border rounded-lg px-3 py-2"
          data-oid="v4t13uk"
        />

        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="비밀번호"
          className="w-full border rounded-lg px-3 py-2"
          data-oid="yj_.aiv"
        />

        {error && (
          <p className="text-red-600 text-sm" data-oid="0zlt1zt">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 text-white rounded-lg py-2.5 font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2"
          data-oid="xtta2qv"
        >
          {loading ? (
            <Loader2 className="animate-spin" size={18} data-oid="bl2.r_." />
          ) : (
            "로그인"
          )}
        </button>
      </form>
    </div>
  );
}
