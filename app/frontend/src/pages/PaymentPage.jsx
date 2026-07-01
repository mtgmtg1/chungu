// [Flow: Step 1 (패키지 조회) -> Step 2 (Toss/Paddle 선택) -> Step 3 (결제 진행) -> Step 4 (검증/포인트 충전)]
import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Coins,
  CreditCard,
  ArrowLeft,
  Loader2,
  CheckCircle2 } from
"lucide-react";
import { api } from "../api.js";
import { useAuth } from "../AuthContext.jsx";
import { SkeletonCard } from "../components/Skeleton.jsx";
import { AnimatedRow } from "../components/AnimatedList.jsx";

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
          failUrl: `${window.location.origin}/payment?toss=fail&orderId=${order.order_id}`
        });
      } else {
        // SDK가 없으면 백엔드 검증만 수동 시뮬레이션 (개발/테스트용)
        await api.verifyToss({
          paymentKey: "test-" + order.order_id,
          orderId: order.order_id,
          amount: order.amount
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
      <div className="min-h-screen flex items-center justify-center" data-oid="mjx7mna">
        <div className="text-center" data-oid="t.p7jw0">
          <p data-oid="sh:71dz">{t("page:payment.loginRequired")}</p>
          <button
            onClick={() => nav("/login")}
            className="bg-blue-600 text-white px-4 py-2 rounded-lg mt-4" data-oid="f7tjrz_">

            {t("page:payment.login")}
          </button>
        </div>
      </div>);

  }

  return (
    <div className="min-h-screen bg-slate-50" data-oid="ti5b7jd">
      <header className="border-b bg-white" data-oid="u5:vv96">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between" data-oid="1c44p8h">
          <div className="flex items-center gap-2" data-oid="wunuvs3">
            <Link
              to="/dashboard"
              className="text-slate-500 hover:text-slate-800" data-oid="q2-gs61">

              <ArrowLeft size={20} data-oid="84tplgv" />
            </Link>
            <h1 className="text-xl font-bold" data-oid="vx2ugc2">{t("page:payment.title")}</h1>
          </div>
          <div className="flex items-center gap-2 text-sm" data-oid="o1fv93u">
            <Coins size={18} className="text-yellow-500" data-oid="5qemmsy" />
            <span data-oid="xkf9k4_">
              {t("page:payment.balance", {
                points: profile?.points_balance ?? "-"
              })}
            </span>
          </div>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8" data-oid="re0ndhu">
        {success &&
        <div className="bg-green-50 text-green-700 rounded-lg p-4 mb-6 flex items-center gap-2" data-oid="uky.q5p">
            <CheckCircle2 size={20} data-oid="9pf.6q0" /> {t("page:payment.rechargeComplete")}
          </div>
        }
        {error && <p className="text-red-600 text-sm mb-6" data-oid="kqiknzg">{error}</p>}

        {loading ?
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6" data-oid="_puqmv1">
            {Array.from({ length: 6 }).map((_, i) =>
          <SkeletonCard key={i} rows={2} />
          )}
          </div> :

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6" data-oid="8m4cd1y">
            {packages.map((pkg, idx) =>
          <AnimatedRow key={pkg.name} index={idx}>
          <div
            className="bg-white border p-5 flex flex-col" data-oid="7h4o0ni">

                <h2 className="text-lg font-bold mb-1" data-oid="t9ga6p.">{pkg.name}</h2>
                <p className="text-3xl font-bold text-blue-600 mb-4" data-oid="0ghf_1q">
                  {pkg.points.toLocaleString()} P
                </p>
                <p className="text-sm text-slate-500 mb-6" data-oid="l9sdgtu">
                  ₩{pkg.krw.toLocaleString()} / ${pkg.usd}
                </p>
                <div className="mt-auto space-y-2" data-oid="qozi_ph">
                  <button
                onClick={() => payWithToss(pkg)}
                disabled={paying}
                className="w-full bg-blue-600 text-white py-2 font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center justify-center gap-2" data-oid="s22k1.l">

                    {paying ?
                <Loader2 className="animate-spin" size={16} data-oid="6teove6" /> :

                <>
                        <CreditCard size={16} data-oid="ta8u39y" /> {t("page:payment.cardKrw")}
                      </>
                }
                  </button>
                  <button
                onClick={() => payWithPaddle(pkg)}
                disabled={paying}
                className="w-full bg-slate-800 text-white py-2 font-medium hover:bg-slate-900 disabled:opacity-50" data-oid=".oou1a9">

                    {t("page:payment.paypalUsd")}
                  </button>
                </div>
              </div>
          </AnimatedRow>
          )}
          </div>
        }
      </main>
    </div>);

}