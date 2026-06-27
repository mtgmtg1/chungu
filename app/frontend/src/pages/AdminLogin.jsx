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
      data-oid="vcjtn4x"
    >
      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-xl shadow-sm border p-8 w-full max-w-sm space-y-5"
        data-oid="ua4-gq-"
      >
        <div className="text-center" data-oid="7k_y3d_">
          <Lock className="mx-auto text-blue-600 mb-2" data-oid="as4yzch" />
          <h1 className="text-lg font-bold" data-oid="_jreo-v">
            관리자 로그인
          </h1>
        </div>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="이메일"
          className="w-full border rounded-lg px-3 py-2"
          data-oid="wsegj5g"
        />

        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="비밀번호"
          className="w-full border rounded-lg px-3 py-2"
          data-oid=":kgaarx"
        />

        {error && (
          <p className="text-red-600 text-sm" data-oid="nfc1c58">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 text-white rounded-lg py-2.5 font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2"
          data-oid="t5cjf98"
        >
          {loading ? (
            <Loader2 className="animate-spin" size={18} data-oid="mswupuq" />
          ) : (
            "로그인"
          )}
        </button>
      </form>
    </div>
  );
}
