// [Flow: Step 1 (헤더 렌더링) -> Step 2 (요약/모델별 가격 카드 렌더링) -> Step 3 (보내기 형식 가격 렌더링) -> Step 4 (결제 안내 및 충전 버튼 렌더링)]
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Coins, FileText, Sparkles, FileSpreadsheet, CreditCard, RefreshCcw } from "lucide-react";

/** 변환 모델별 가격 카드에서 공통으로 사용하는 아이템 레이아웃 */
function PriceFeature({ icon: Icon, children }) {
  return (
    <li className="flex items-start gap-2 text-sm text-slate-600">
      <Icon size={16} className="text-blue-600 mt-0.5 flex-shrink-0" />
      <span>{children}</span>
    </li>
  );
}

export default function PricePage() {
  const { t } = useTranslation();
  const nav = useNavigate();

  return (
    <div className="min-h-screen bg-slate-50" data-oid="price-page">
      <header className="border-b bg-white" data-oid="price-header">
        <div className="max-w-5xl mx-auto px-6 py-4 flex items-center gap-2" data-oid="price-header-inner">
          <button
            onClick={() => nav(-1)}
            className="text-slate-500 hover:text-slate-800"
            data-oid="price-back"
          >
            <ArrowLeft size={20} />
          </button>
          <h1 className="text-xl font-bold" data-oid="price-title">{t("page:price.title")}</h1>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-10" data-oid="price-main">
        {/* 소개 영역 */}
        <div className="text-center mb-12" data-oid="price-hero">
          <h2 className="text-3xl font-bold text-slate-900 mb-3" data-oid="price-hero-title">
            {t("page:price.title")}
          </h2>
          <p className="text-lg text-slate-600 max-w-2xl mx-auto" data-oid="price-hero-desc">
            {t("page:price.subtitle")}
          </p>
        </div>

        {/* 변환 모델별 가격 */}
        <h2 className="text-xl font-bold text-slate-900 mb-6" data-oid="price-models-title">
          {t("page:price.modelsTitle")}
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-12" data-oid="price-model-cards">
          {/* 기본 모델 */}
          <div className="bg-white border rounded-xl p-6 shadow-sm" data-oid="price-basic-card">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center">
                <FileText className="text-blue-600" size={22} />
              </div>
              <div>
                <h3 className="font-bold text-slate-900">{t("page:price.basicTitle")}</h3>
                <p className="text-sm text-slate-500">{t("page:price.basicDesc")}</p>
              </div>
            </div>
            <p className="text-3xl font-bold text-blue-600 mb-1" data-oid="price-basic-price">
              {t("page:price.basicPrice")}
            </p>
            <p className="text-sm font-medium text-green-600 mb-4">{t("page:price.basicFree")}</p>
            <ul className="space-y-2">
              <PriceFeature icon={FileText}>{t("page:price.basicFeature1")}</PriceFeature>
              <PriceFeature icon={Sparkles}>{t("page:price.basicFeature2")}</PriceFeature>
              <PriceFeature icon={RefreshCcw}>{t("page:price.basicFeature3")}</PriceFeature>
            </ul>
          </div>

          {/* 고급 모델 */}
          <div className="bg-white border rounded-xl p-6 shadow-sm" data-oid="price-premium-card">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 bg-indigo-50 rounded-lg flex items-center justify-center">
                <Sparkles className="text-indigo-600" size={22} />
              </div>
              <div>
                <h3 className="font-bold text-slate-900">{t("page:price.premiumTitle")}</h3>
                <p className="text-sm text-slate-500">{t("page:price.premiumDesc")}</p>
              </div>
            </div>
            <p className="text-3xl font-bold text-indigo-600 mb-1" data-oid="price-premium-pdf">
              {t("page:price.premiumPricePdf")}
            </p>
            <p className="text-sm font-medium text-slate-600 mb-4">
              {t("page:price.premiumPriceAudio")} · {t("page:price.premiumPriceVideo")}
            </p>
            <ul className="space-y-2">
              <PriceFeature icon={Sparkles}>{t("page:price.premiumFeature1")}</PriceFeature>
              <PriceFeature icon={FileText}>{t("page:price.premiumFeature2")}</PriceFeature>
              <PriceFeature icon={RefreshCcw}>{t("page:price.premiumFeature3")}</PriceFeature>
            </ul>
          </div>
        </div>

        {/*보내기 형식 가격 */}
        <h2 className="text-xl font-bold text-slate-900 mb-6" data-oid="price-exports-title">
          {t("page:price.exportsTitle")}
        </h2>
        <div className="bg-white border rounded-xl p-6 shadow-sm mb-10" data-oid="price-exports-card">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="p-4 bg-slate-50 rounded-lg" data-oid="price-export-md">
              <p className="font-medium text-slate-900 mb-1">{t("page:price.exportMarkdown")}</p>
              <p className="text-sm text-green-600 font-medium">{t("page:price.exportFree")}</p>
            </div>
            <div className="p-4 bg-slate-50 rounded-lg" data-oid="price-export-docx">
              <p className="font-medium text-slate-900 mb-1">{t("page:price.exportWord")}</p>
              <p className="text-sm text-green-600 font-medium">{t("page:price.exportFree")}</p>
            </div>
            <div className="p-4 bg-slate-50 rounded-lg" data-oid="price-export-pptx">
              <p className="font-medium text-slate-900 mb-1">{t("page:price.exportPpt")}</p>
              <p className="text-sm text-green-600 font-medium">{t("page:price.exportFree")}</p>
            </div>
            <div className="p-4 bg-slate-50 rounded-lg" data-oid="price-export-xlsx-basic">
              <p className="font-medium text-slate-900 mb-1">{t("page:price.exportExcelBasic")}</p>
              <p className="text-sm text-blue-600 font-medium">{t("page:price.exportExcelBasicPrice")}</p>
            </div>
            <div className="p-4 bg-slate-50 rounded-lg sm:col-span-2 lg:col-span-1" data-oid="price-export-xlsx-advanced">
              <p className="font-medium text-slate-900 mb-1">{t("page:price.exportExcelAdvanced")}</p>
              <p className="text-sm text-indigo-600 font-medium">{t("page:price.exportExcelAdvancedPrice")}</p>
            </div>
          </div>
        </div>

        {/* 결제 안내 및 충전 */}
        <div className="bg-white border rounded-xl p-6 md:p-8 shadow-sm" data-oid="price-payment-card">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center">
              <CreditCard className="text-blue-600" size={22} />
            </div>
            <h2 className="text-xl font-bold text-slate-900">{t("page:price.paymentTitle")}</h2>
          </div>
          <p className="text-slate-600 mb-6">{t("page:price.paymentDesc")}</p>
          <p className="text-sm text-slate-500 mb-6">{t("page:price.refundNotice")}</p>
          <Link
            to="/payment"
            className="inline-flex items-center gap-2 bg-blue-600 text-white px-5 py-2.5 rounded-lg font-medium hover:bg-blue-700 transition-colors"
            data-oid="price-recharge-link"
          >
            <Coins size={18} />
            {t("page:price.rechargeButton")}
          </Link>
        </div>
      </main>
    </div>
  );
}
