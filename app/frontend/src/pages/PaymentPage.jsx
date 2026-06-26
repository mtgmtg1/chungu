// [Flow: Step 1 (패키지 조회) -> Step 2 (Toss/Paddle 선택) -> Step 3 (결제 진행) -> Step 4 (검증/포인트 충전)]
import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Coins,
  CreditCard,
  ArrowLeft,
  Loader2,
  CheckCircle2,
} from "lucide-react";
import { api } from "../api.js";
import { useAuth } from "../AuthContext.jsx";

export default function PaymentPage() {
  const { user } = useAuth();
  const { t } = useTranslation();
  const [packages, setPackages] = useState([]);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");
  const nav = useNavigate();

  useEffect(() => {
    if (!user) return;
    load();
  }, [user]);

  async function load() {
    try {
      const [pkg, me] = await Promise.all([api.getPackages(), api.me()]);
      setPackages(pkg.packages || []);
      setProfile(me);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function payWithToss(pkg) {
    setPaying(true);
    setError("");
    try {
      const order = await api.createTossOrder({ package_id: pkg.name });
      // Toss SDK가 로드되어 있지 않으면 테스트용 수동 결제창은 대체로 처리합니다.
      if (window.TossPayments) {
        const toss = window.TossPayments(order.client_key || "");
        toss.requestPayment(t("page:payment.card"), {
          amount: order.amount,
          orderId: order.order_id,
          orderName: t("page:payment.orderName", { points: pkg.points }),
          customerEmail: profile?.email || "",
          successUrl: `${window.location.origin}/payment?toss=success&orderId=${order.order_id}`,
          failUrl: `${window.location.origin}/payment?toss=fail&orderId=${order.order_id}`,
        });
      } else {
        // SDK가 없으면 백엔드 검증만 수동 시뮬레이션 (개발/테스트용)
        await api.verifyToss({
          paymentKey: "test-" + order.order_id,
          orderId: order.order_id,
          amount: order.amount,
        });
        setSuccess(true);
        await load();
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setPaying(false);
    }
  }

  async function payWithPaddle(pkg) {
    setPaying(true);
    setError("");
    try {
      const checkout = await api.createPaddleCheckout({ package_id: pkg.name });
      window.open(checkout.checkout_url, "_blank");
    } catch (e) {
      setError(e.message);
    } finally {
      setPaying(false);
    }
  }

  if (!user) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        data-oid="3l92vl."
      >
        <div className="text-center" data-oid="edw7on1">
          <p data-oid="h-reqzp">{t("page:payment.loginRequired")}</p>
          <button
            onClick={() => nav("/login")}
            className="bg-blue-600 text-white px-4 py-2 rounded-lg mt-4"
            data-oid="bg0b4n9"
          >
            {t("page:payment.login")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50" data-oid="l9k42rr">
      <header className="border-b bg-white" data-oid="hfwiisz">
        <div
          className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between"
          data-oid=":isf3cw"
        >
          <div className="flex items-center gap-2" data-oid="frg68c_">
            <Link
              to="/dashboard"
              className="text-slate-500 hover:text-slate-800"
              data-oid="kdds9ce"
            >
              <ArrowLeft size={20} data-oid="xfooidz" />
            </Link>
            <h1 className="text-xl font-bold" data-oid="30fc1xs">
              {t("page:payment.title")}
            </h1>
          </div>
          <div className="flex items-center gap-2 text-sm" data-oid="afnt3l_">
            <Coins size={18} className="text-yellow-500" data-oid="j9a8cg0" />
            <span data-oid="5din6o9">
              {t("page:payment.balance", {
                points: profile?.points_balance ?? "-",
              })}
            </span>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8" data-oid="qlt.1_4">
        {success && (
          <div
            className="bg-green-50 text-green-700 rounded-lg p-4 mb-6 flex items-center gap-2"
            data-oid=".bmcdoo"
          >
            <CheckCircle2 size={20} data-oid="49exo6e" />{" "}
            {t("page:payment.rechargeComplete")}
          </div>
        )}
        {error && (
          <p className="text-red-600 text-sm mb-6" data-oid="0.u1bz6">
            {error}
          </p>
        )}

        {loading ? (
          <div className="text-center py-12" data-oid="gjb3z:2">
            <Loader2 className="animate-spin mx-auto" data-oid="_:an-g9" />
          </div>
        ) : (
          <div
            className="grid grid-cols-1 md:grid-cols-3 gap-6"
            data-oid="xleyd7u"
          >
            {packages.map((pkg) => (
              <div
                key={pkg.name}
                className="bg-white rounded-xl border p-6 flex flex-col"
                data-oid="9sq1aua"
              >
                <h2 className="text-lg font-bold mb-1" data-oid="ps::tgl">
                  {pkg.name}
                </h2>
                <p
                  className="text-3xl font-bold text-blue-600 mb-4"
                  data-oid="ttmkwm3"
                >
                  {pkg.points.toLocaleString()} P
                </p>
                <p className="text-sm text-slate-500 mb-6" data-oid="ygbdhg1">
                  ₩{pkg.krw.toLocaleString()} / ${pkg.usd}
                </p>
                <div className="mt-auto space-y-2" data-oid="0cib32z">
                  <button
                    onClick={() => payWithToss(pkg)}
                    disabled={paying}
                    className="w-full bg-blue-600 text-white rounded-lg py-2 font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2"
                    data-oid="dz.wt.u"
                  >
                    {paying ? (
                      <Loader2
                        className="animate-spin"
                        size={16}
                        data-oid="d1w7-r8"
                      />
                    ) : (
                      <>
                        <CreditCard size={16} data-oid="wu9tmbk" />{" "}
                        {t("page:payment.cardKrw")}
                      </>
                    )}
                  </button>
                  <button
                    onClick={() => payWithPaddle(pkg)}
                    disabled={paying}
                    className="w-full bg-slate-800 text-white rounded-lg py-2 font-medium hover:bg-slate-900 disabled:opacity-50"
                    data-oid="::m743j"
                  >
                    {t("page:payment.paypalUsd")}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
