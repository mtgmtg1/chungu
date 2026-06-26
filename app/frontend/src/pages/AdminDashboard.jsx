// [Flow: Step 1 (인증 확인) -> Step 2 (설정 로드) -> Step 3 (LLM/SMTP 설정 편집/테스트) -> Step 4 (job 모니터)]
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Loader2,
  Save,
  Mail,
  Cpu,
  Film,
  ListChecks,
  LogOut,
  KeyRound,
  CreditCard,
} from "lucide-react";
import { api } from "../api.js";

const STATUS_BADGE = {
  done: "bg-green-100 text-green-700",
  error: "bg-red-100 text-red-700",
  queued: "bg-slate-100 text-slate-600",
};

export default function AdminDashboard() {
  const [settings, setSettings] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [msg, setMsg] = useState("");
  const [loading, setLoading] = useState(true);
  const nav = useNavigate();

  useEffect(() => {
    (async () => {
      try {
        await api.adminMe();
        const [s, j] = await Promise.all([
          api.getSettings(),
          api.adminListJobs(),
        ]);
        setSettings(s);
        setJobs(j);
      } catch (e) {
        nav("/admin/login");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  function update(key, value) {
    setSettings((s) => ({ ...s, [key]: value }));
  }

  async function save() {
    setMsg("");
    try {
      const saved = await api.saveSettings(settings);
      setSettings(saved);
      setMsg("저장되었습니다");
    } catch (e) {
      setMsg(e.message);
    }
  }

  async function testLlm() {
    setMsg("LLM 테스트 중…");
    try {
      const r = await api.testLlm();
      setMsg(`LLM 응답: ${r.reply}`);
    } catch (e) {
      setMsg(e.message);
    }
  }

  async function testSmtp() {
    const to = prompt("테스트 메일을 받을 주소", settings.smtp_from || "");
    if (!to) return;
    setMsg("SMTP 테스트 중…");
    try {
      await api.testSmtp(to);
      setMsg(`테스트 메일 발송: ${to}`);
    } catch (e) {
      setMsg(e.message);
    }
  }

  async function changePw() {
    const cur = prompt("현재 비밀번호");
    if (!cur) return;
    const nw = prompt("새 비밀번호 (8자 이상)");
    if (!nw) return;
    try {
      await api.changePassword(cur, nw);
      setMsg("비밀번호가 변경되었습니다");
    } catch (e) {
      setMsg(e.message);
    }
  }

  async function logout() {
    await api.adminLogout();
    nav("/admin/login");
  }

  if (loading || !settings) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        data-oid="i77d70z"
      >
        <Loader2 className="animate-spin text-blue-600" data-oid="1zmzexy" />
      </div>
    );
  }

  const field = (key, label, type = "text") => (
    <div data-oid="-.so3_p">
      <label className="block text-sm font-medium mb-1" data-oid="r2-b4xx">
        {label}
      </label>
      <input
        type={type}
        value={settings[key] ?? ""}
        onChange={(e) => update(key, e.target.value)}
        className="w-full border rounded-lg px-3 py-2 text-sm"
        data-oid="xkkmctc"
      />
    </div>
  );

  return (
    <div className="min-h-screen" data-oid="buttj3s">
      <header className="border-b bg-white" data-oid="5zibyp8">
        <div
          className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between"
          data-oid="yl-9tmu"
        >
          <h1 className="text-xl font-bold" data-oid="ztrmbtc">
            관리자 대시보드
          </h1>
          <div className="flex gap-3" data-oid="u3-tbwc">
            <button
              onClick={changePw}
              className="text-sm text-slate-500 hover:text-slate-800 flex items-center gap-1"
              data-oid="qo.iqii"
            >
              <KeyRound size={16} data-oid="v51qsqe" /> 비밀번호
            </button>
            <button
              onClick={logout}
              className="text-sm text-slate-500 hover:text-slate-800 flex items-center gap-1"
              data-oid="t.zree6"
            >
              <LogOut size={16} data-oid="tmz3a.w" /> 로그아웃
            </button>
          </div>
        </div>
      </header>

      <main
        className="max-w-5xl mx-auto px-6 py-8 space-y-8"
        data-oid="n_4w9vz"
      >
        {msg && (
          <div
            className="bg-blue-50 text-blue-700 text-sm px-4 py-2 rounded-lg"
            data-oid="jwk5d0j"
          >
            {msg}
          </div>
        )}

        <section
          className="bg-white rounded-xl border p-6 space-y-4"
          data-oid="klx0lf7"
        >
          <h2
            className="font-semibold flex items-center gap-2"
            data-oid="u_724hs"
          >
            <Cpu size={18} data-oid="zbja0le" /> LLM 설정 (OpenAI 호환)
          </h2>
          <div className="grid md:grid-cols-2 gap-4" data-oid="zsr_o.d">
            {field("llm_endpoint", "엔드포인트 (/v1)")}
            {field("llm_model", "모델")}
            {field("llm_api_key", "API Key (선택)", "password")}
            {field("default_pipeline", "기본 파이프라인 (vision/hybrid)")}
          </div>
          <button
            onClick={testLlm}
            className="text-sm border rounded-lg px-3 py-1.5 hover:bg-slate-50"
            data-oid="k0af2op"
          >
            LLM 연결 테스트
          </button>
        </section>

        <section
          className="bg-white rounded-xl border p-6 space-y-4"
          data-oid="qrux3rw"
        >
          <h2
            className="font-semibold flex items-center gap-2"
            data-oid="__40ju3"
          >
            <Film size={18} data-oid="0ca5oz-" /> 미디어 LLM 설정
            (오디오/비디오, OpenAI 호환)
          </h2>
          <div className="grid md:grid-cols-2 gap-4" data-oid=".wv3hje">
            {field("media_llm_endpoint", "엔드포인트 (/v1)")}
            {field("media_llm_model", "모델")}
            {field("media_llm_api_key", "API Key (선택)", "password")}
          </div>
          <p className="text-xs text-slate-500" data-oid="44.062k">
            오디오/비디오 파일은 이 엔드포인트로 전송됩니다. 이미지/PDF는 위의
            기본 LLM 설정을 사용합니다.
          </p>
        </section>

        <section
          className="bg-white rounded-xl border p-6 space-y-4"
          data-oid="2.al-i9"
        >
          <h2
            className="font-semibold flex items-center gap-2"
            data-oid="_yh1s8g"
          >
            <Mail size={18} data-oid="xfmpp0_" /> SMTP 설정 (자체 메일 서버)
          </h2>
          <div className="grid md:grid-cols-2 gap-4" data-oid="j2xomok">
            {field("smtp_host", "호스트")}
            {field("smtp_port", "포트")}
            {field("smtp_user", "사용자")}
            {field("smtp_password", "비밀번호", "password")}
            {field("smtp_from", "발신 주소")}
            {field("smtp_use_tls", "TLS 사용 (1/0)")}
          </div>
          <button
            onClick={testSmtp}
            className="text-sm border rounded-lg px-3 py-1.5 hover:bg-slate-50"
            data-oid="uqf9-ea"
          >
            테스트 메일 발송
          </button>
        </section>

        <section
          className="bg-white rounded-xl border p-6 space-y-4"
          data-oid="gbi.wag"
        >
          <h2 className="font-semibold" data-oid="4zlcxfb">
            작업 제한
          </h2>
          <div className="grid md:grid-cols-3 gap-4" data-oid="gfgjzkj">
            {field("max_file_mb", "최대 파일 크기 (MB)")}
            {field("max_pages", "최대 페이지 수")}
            {field("download_expire_days", "다운로드 만료 (일)")}
          </div>
        </section>

        <section
          className="bg-white rounded-xl border p-6 space-y-4"
          data-oid="qv790ug"
        >
          <h2
            className="font-semibold flex items-center gap-2"
            data-oid="mgweruw"
          >
            <CreditCard size={18} data-oid="wzwte3w" /> 포인트/결제 설정
          </h2>
          <div className="grid md:grid-cols-3 gap-4" data-oid="ofqsxgo">
            {field("cost_per_page_krw", "페이지당 비용 (KRW)")}
            {field("cost_per_image_krw", "이미지당 비용 (KRW)")}
            {field("cost_per_audio_sec_krw", "오디오 초당 비용 (KRW)")}
            {field("cost_per_video_sec_krw", "비디오 초당 비용 (KRW)")}
            {field("cost_per_page_usd", "페이지당 비용 (USD)")}
            {field("usd_to_krw_rate", "USD→KRW 환율")}
          </div>
          <div data-oid="33ji.jr">
            <label
              className="block text-sm font-medium mb-1"
              data-oid="yejub44"
            >
              포인트 패키지 (JSON)
            </label>
            <textarea
              value={settings.point_packages || ""}
              onChange={(e) => update("point_packages", e.target.value)}
              rows={4}
              className="w-full border rounded-lg px-3 py-2 text-sm font-mono"
              data-oid="ynzts_3"
            />
          </div>
          <div className="grid md:grid-cols-2 gap-4" data-oid="r7q2r7-">
            {field("toss_secret_key", "Toss Secret Key", "password")}
            {field("toss_client_key", "Toss Client Key")}
            {field("paddle_api_key", "Paddle API Key", "password")}
            {field(
              "paddle_webhook_secret",
              "Paddle Webhook Secret",
              "password",
            )}
            {field("paddle_vendor_id", "Paddle Vendor ID")}
          </div>
        </section>

        <button
          onClick={save}
          className="bg-blue-600 text-white rounded-lg px-5 py-2.5 font-medium hover:bg-blue-700 flex items-center gap-2"
          data-oid="y0le3g5"
        >
          <Save size={18} data-oid="hb06v8p" /> 설정 저장
        </button>

        <section className="bg-white rounded-xl border p-6" data-oid="p185.pa">
          <h2
            className="font-semibold flex items-center gap-2 mb-4"
            data-oid="fuw26d9"
          >
            <ListChecks size={18} data-oid=":64qz:z" /> 최근 작업
          </h2>
          <div className="overflow-x-auto" data-oid="hve1eu-">
            <table className="w-full text-sm" data-oid="0k9jxs8">
              <thead data-oid="ec5:f47">
                <tr
                  className="text-left text-slate-500 border-b"
                  data-oid="5.tx-sk"
                >
                  <th className="py-2" data-oid="vyrrzjw">
                    파일
                  </th>
                  <th data-oid="0td_1yp">유형</th>
                  <th data-oid="9g_4j4.">이메일</th>
                  <th data-oid="zdk_yjf">방식</th>
                  <th data-oid="ugj1yu7">상태</th>
                  <th data-oid="lk:pn--">진행</th>
                  <th data-oid="d34agf0">생성</th>
                </tr>
              </thead>
              <tbody data-oid="40b0hf.">
                {jobs.map((j) => (
                  <tr
                    key={j.job_id}
                    className="border-b last:border-0"
                    data-oid="rwsuh4a"
                  >
                    <td
                      className="py-2 max-w-[180px] truncate"
                      data-oid="zx-dg0v"
                    >
                      {j.filename}
                    </td>
                    <td data-oid="j:v-yha">{j.file_type}</td>
                    <td data-oid="aa1n87h">{j.email}</td>
                    <td data-oid="znr9xzu">{j.pipeline}</td>
                    <td data-oid=":m_8ilu">
                      <span
                        className={`px-2 py-0.5 rounded text-xs ${STATUS_BADGE[j.status] || "bg-amber-100 text-amber-700"}`}
                        data-oid="ypa:jk5"
                      >
                        {j.status}
                      </span>
                    </td>
                    <td data-oid="vlqpnjl">
                      {j.total_pages
                        ? `${j.done_pages}/${j.total_pages}p`
                        : `${j.done_files}/${j.total_files}f`}
                    </td>
                    <td className="text-slate-400 text-xs" data-oid="0pbo5r:">
                      {j.created_at?.slice(0, 16).replace("T", " ")}
                    </td>
                  </tr>
                ))}
                {jobs.length === 0 && (
                  <tr data-oid="_rmmghk">
                    <td
                      colSpan={7}
                      className="py-6 text-center text-slate-400"
                      data-oid="o944shl"
                    >
                      작업이 없습니다
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}
