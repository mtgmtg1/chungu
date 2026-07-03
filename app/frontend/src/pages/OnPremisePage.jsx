// [Flow: Step 1 (슬라이더 상태로 처리량/가격 계산) -> Step 2 (문의 폼 렌더링) -> Step 3 (검증 후 API 제출) -> Step 4 (성공/에러 피드백)]
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Building2, CheckCircle2, Globe, HardDrive, Loader2, Mail, MessageSquare, Server, ShieldCheck, User, Wrench, Zap } from "lucide-react";
import { api } from "../api.js";
import GlobalFooter from "../components/GlobalFooter.jsx";

const MIN_PAGES = 3000;
const MAX_PAGES = 12000;
const STEP_PAGES = 1000;
const BASE_PRICE = 20000;
const MAX_PRICE = 80000;

/** 시간당 처리량을 USD 가격으로 선형 계산한다 */
function calculatePrice(pagesPerHour) {
  const ratio = (pagesPerHour - MIN_PAGES) / (MAX_PAGES - MIN_PAGES);
  return Math.round(BASE_PRICE + ratio * (MAX_PRICE - BASE_PRICE));
}

/** USD 금액을 통화 형식 문자열로 변환한다 */
function formatUsd(value) {
  return `$${value.toLocaleString("en-US")}`;
}

export default function OnPremisePage() {
  const { t } = useTranslation();
  const nav = useNavigate();
  const [pagesPerHour, setPagesPerHour] = useState(MIN_PAGES);
  const [form, setForm] = useState({
    company: "",
    contact_name: "",
    email: "",
    country: "",
    message: "",
    agreed_terms: false,
  });
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState("");

  const price = useMemo(() => calculatePrice(pagesPerHour), [pagesPerHour]);

  // [Flow: 폼 필드 이름/값을 받아 -> 기존 상태를 복사 -> 해당 필드만 갱신 -> 새 상태 반환]
  function updateField(name, value) {
    setForm((prev) => ({ ...prev, [name]: value }));
  }

  // [Flow: 필수값 및 약관 동의 확인 -> 누락 시 에러 메시지 반환 -> 모두 통과 시 null 반환]
  function validateForm() {
    if (!form.email.trim()) return t("page:onPremise.requiredEmail");
    if (!form.agreed_terms) return t("page:onPremise.requiredTerms");
    return null;
  }

  // [Flow: 검증 -> API 제출 -> 성공 시 폼 초기화 -> 에러 시 메시지 표시]
  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    const validationError = validateForm();
    if (validationError) return setError(validationError);

    setSubmitting(true);
    try {
      await api.submitOnPremiseInquiry({
        ...form,
        pages_per_hour: pagesPerHour,
      });
      setSuccess(true);
      setForm({ company: "", contact_name: "", email: "", country: "", message: "", agreed_terms: false });
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setError(err.message || t("page:errors.unknown"));
    } finally {
      setSubmitting(false);
    }
  }

  // [Flow: 슬라이더 변경값을 1000 단위로 정규화 -> 상태 갱신]
  function handleSliderChange(e) {
    const value = Math.round(parseInt(e.target.value, 10) / STEP_PAGES) * STEP_PAGES;
    setPagesPerHour(Math.max(MIN_PAGES, Math.min(MAX_PAGES, value)));
  }

  const features = [
    { icon: HardDrive, title: t("page:onPremise.featureUnlimited"), desc: t("page:onPremise.featureUnlimitedDesc") },
    { icon: ShieldCheck, title: t("page:onPremise.featureSecure"), desc: t("page:onPremise.featureSecureDesc") },
    { icon: Zap, title: t("page:onPremise.featureUpdates"), desc: t("page:onPremise.featureUpdatesDesc") },
    { icon: Wrench, title: t("page:onPremise.featureSupport"), desc: t("page:onPremise.featureSupportDesc") },
    { icon: Server, title: t("page:onPremise.featureDelivery"), desc: t("page:onPremise.featureDeliveryDesc") },
  ];

  if (success) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center px-6" data-oid="onprem-success">
        <div className="max-w-md w-full bg-white border rounded-xl p-8 text-center shadow-sm">
          <CheckCircle2 className="mx-auto text-green-600 mb-4" size={48} />
          <h1 className="text-xl font-bold text-slate-900 mb-2">{t("page:onPremise.successTitle")}</h1>
          <p className="text-slate-600 mb-6">{t("page:onPremise.successBody")}</p>
          <button
            onClick={() => nav("/payment")}
            className="w-full bg-blue-600 text-white py-2.5 rounded-lg font-medium hover:bg-blue-700 transition-colors"
            data-oid="onprem-back-btn"
          >
            {t("page:payment.back")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50" data-oid="onprem-page">
      <header className="border-b bg-white" data-oid="onprem-header">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center gap-2" data-oid="onprem-header-inner">
          <button onClick={() => nav(-1)} className="text-slate-500 hover:text-slate-800" data-oid="onprem-back">
            <ArrowLeft size={20} />
          </button>
          <h1 className="text-xl font-bold" data-oid="onprem-title">{t("page:onPremise.title")}</h1>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10" data-oid="onprem-main">
        {/* Hero */}
        <div className="text-center mb-12" data-oid="onprem-hero">
          <h2 className="text-3xl font-bold text-slate-900 mb-4" data-oid="onprem-hero-title">
            {t("page:onPremise.heroTitle")}
          </h2>
          <p className="text-lg text-slate-600 max-w-2xl mx-auto" data-oid="onprem-hero-desc">
            {t("page:onPremise.heroDesc")}
          </p>
        </div>

        {/* Features */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-16" data-oid="onprem-features">
          {features.map((feature) => (
            <div
              key={feature.title}
              className="bg-white border rounded-xl p-6 shadow-sm"
              data-oid={`onprem-feature-${feature.title}`}
            >
              <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center mb-4">
                <feature.icon className="text-blue-600" size={22} />
              </div>
              <h3 className="font-bold text-slate-900 mb-2">{feature.title}</h3>
              <p className="text-sm text-slate-600">{feature.desc}</p>
            </div>
          ))}
        </div>

        {/* Pricing slider */}
        <div className="bg-white border rounded-xl p-6 md:p-8 mb-10 shadow-sm" data-oid="onprem-pricing">
          <h2 className="text-xl font-bold text-slate-900 mb-2" data-oid="onprem-pricing-title">
            {t("page:onPremise.sliderTitle")}
          </h2>
          <p className="text-slate-600 mb-8" data-oid="onprem-pricing-desc">
            {t("page:onPremise.sliderDesc")}
          </p>

          <div className="mb-6" data-oid="onprem-slider-wrap">
            <div className="flex justify-between text-sm font-medium text-slate-500 mb-2">
              <span>{t("page:onPremise.minLabel")}: {t("page:onPremise.pagesPerHour", { value: MIN_PAGES.toLocaleString() })}</span>
              <span>{t("page:onPremise.maxLabel")}: {t("page:onPremise.pagesPerHour", { value: MAX_PAGES.toLocaleString() })}</span>
            </div>
            <input
              type="range"
              min={MIN_PAGES}
              max={MAX_PAGES}
              step={STEP_PAGES}
              value={pagesPerHour}
              onChange={handleSliderChange}
              className="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
              data-oid="onprem-slider"
            />
          </div>

          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 bg-slate-50 rounded-lg p-6" data-oid="onprem-price-box">
            <div data-oid="onprem-selected">
              <p className="text-sm text-slate-500 mb-1">{t("page:onPremise.pagesPerHour", { value: pagesPerHour.toLocaleString() })}</p>
              <p className="text-xs text-slate-400">{formatUsd(BASE_PRICE)} ~ {formatUsd(MAX_PRICE)}</p>
            </div>
            <div className="text-right" data-oid="onprem-estimated">
              <p className="text-sm text-slate-500 mb-1">{t("page:onPremise.estimatedPrice")}</p>
              <p className="text-3xl font-bold text-blue-600">{formatUsd(price)}</p>
            </div>
          </div>
        </div>

        {/* Form */}
        <div className="bg-white border rounded-xl p-6 md:p-8 shadow-sm" data-oid="onprem-form-card">
          <h2 className="text-xl font-bold text-slate-900 mb-2" data-oid="onprem-form-title">{t("page:onPremise.formTitle")}</h2>
          <p className="text-slate-600 mb-6" data-oid="onprem-form-desc">{t("page:onPremise.formDesc")}</p>

          {error && <p className="text-red-600 text-sm mb-4" data-oid="onprem-error">{error}</p>}

          <form onSubmit={handleSubmit} className="space-y-5" data-oid="onprem-form">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div data-oid="onprem-company-wrap">
                <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="company">
                  <Building2 size={14} className="inline mr-1 mb-0.5 text-slate-400" />
                  {t("page:onPremise.company")}
                </label>
                <input
                  id="company"
                  type="text"
                  value={form.company}
                  onChange={(e) => updateField("company", e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  data-oid="onprem-company"
                />
              </div>

              <div data-oid="onprem-name-wrap">
                <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="contact_name">
                  <User size={14} className="inline mr-1 mb-0.5 text-slate-400" />
                  {t("page:onPremise.contactName")}
                </label>
                <input
                  id="contact_name"
                  type="text"
                  value={form.contact_name}
                  onChange={(e) => updateField("contact_name", e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  data-oid="onprem-name"
                />
              </div>

              <div data-oid="onprem-email-wrap">
                <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="email">
                  <Mail size={14} className="inline mr-1 mb-0.5 text-slate-400" />
                  {t("page:onPremise.email")}
                </label>
                <input
                  id="email"
                  type="email"
                  required
                  value={form.email}
                  onChange={(e) => updateField("email", e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  data-oid="onprem-email"
                />
              </div>

              <div data-oid="onprem-country-wrap">
                <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="country">
                  <Globe size={14} className="inline mr-1 mb-0.5 text-slate-400" />
                  {t("page:onPremise.country")}
                </label>
                <input
                  id="country"
                  type="text"
                  value={form.country}
                  onChange={(e) => updateField("country", e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  data-oid="onprem-country"
                />
              </div>
            </div>

            <div data-oid="onprem-message-wrap">
              <label className="block text-sm font-medium text-slate-700 mb-1" htmlFor="message">
                <MessageSquare size={14} className="inline mr-1 mb-0.5 text-slate-400" />
                {t("page:onPremise.message")}
              </label>
              <textarea
                id="message"
                rows={4}
                value={form.message}
                onChange={(e) => updateField("message", e.target.value)}
                className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                data-oid="onprem-message"
              />
            </div>

            <label className="flex items-start gap-2 text-sm text-slate-600" data-oid="onprem-terms-wrap">
              <input
                type="checkbox"
                checked={form.agreed_terms}
                onChange={(e) => updateField("agreed_terms", e.target.checked)}
                className="mt-0.5"
                data-oid="onprem-terms"
              />
              <span>
                {t("page:onPremise.agreeTerms")}{" "}
                <Link to="/terms" target="_blank" className="text-blue-600 hover:underline" data-oid="onprem-terms-link">
                  {t("common:footer.terms")}
                </Link>
              </span>
            </label>

            <button
              type="submit"
              disabled={submitting}
              className="w-full bg-blue-600 text-white py-3 font-medium hover:bg-blue-700 disabled:opacity-50 rounded-lg flex items-center justify-center gap-2"
              data-oid="onprem-submit"
            >
              {submitting ? <Loader2 className="animate-spin" size={18} /> : <Mail size={18} />}
              {submitting ? t("page:onPremise.submitting") : t("page:onPremise.submit")}
            </button>
          </form>
        </div>
      </main>
      <GlobalFooter />
    </div>
  );
}
