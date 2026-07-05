// [Flow: Step 1 (헤더 렌더링) -> Step 2 (변환 모델별 가격 카드 렌더링) -> Step 3 (보내기 형식 가격 카드 렌더링) -> Step 4 (결제 안내 및 충전 버튼 렌더링)]
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  ArrowLeft,
  Check,
  Coins,
  FileCode,
  FileSpreadsheet,
  FileText,
  FileType,
  Sparkles,
  Table2,
} from "lucide-react";
import GlobalFooter from "../components/GlobalFooter.jsx";

/**
 *보내기 형식 하나를 아이콘과 가격이 포함된 카드로 렌더링합니다.
 * @param {Object} props - React props
 * @param {React.ComponentType} props.icon - lucide-react 아이콘 컴포넌트
 * @param {string} props.iconBgClass - 아이콘 배경에 적용할 Tailwind 클래스
 * @param {string} props.iconColorClass - 아이콘 색상에 적용할 Tailwind 클래스
 * @param {string} props.label - 파일 형식 이름
 * @param {string} props.price - 가격 또는 무료 문구
 * @param {string} props.priceColorClass - 가격 텍스트 색상 클래스
 * @param {string} props.dataOid - QA 테스트용 data-oid 식별자
 * @returns {JSX.Element}보내기 형식 카드
 */
function ExportFormatCard({
  icon: Icon,
  iconBgClass,
  iconColorClass,
  label,
  price,
  priceColorClass,
  dataOid,
}) {
  return (
    <div
      className="flex flex-col items-center p-5 rounded-2xl bg-white border border-slate-200 shadow-md w-[150px] snap-center"
      data-oid={dataOid}
    >
      <div
        className={`w-12 h-12 rounded-xl ${iconBgClass} flex items-center justify-center mb-3`}
      >
        <Icon className={iconColorClass} size={24} />
      </div>
      <p className="text-sm font-semibold text-slate-900 text-center mb-1 break-words min-h-[40px] flex items-center justify-center">
        {label}
      </p>
      <p className={`text-xs font-medium ${priceColorClass}`}>{price}</p>
    </div>
  );
}

/**
 * 변환 모델별 가격 카드를 렌더링합니다.
 * @param {Object} props - React props
 * @param {string} [props.badge] - 카드 상단에 표시할 배지 텍스트
 * @param {React.ComponentType} props.icon - 모델 대표 아이콘
 * @param {string} props.iconBgClass - 아이콘 배경 클래스
 * @param {string} props.iconColorClass - 아이콘 색상 클래스
 * @param {string} props.title - 모델명
 * @param {string} props.desc - 모델 설명
 * @param {string} props.price - 주요 가격
 * @param {string} props.priceColorClass - 가격 색상 클래스
 * @param {string} [props.subPrice] - 부가 가격 안내
 * @param {string[]} props.features - 제공 기능 목록
 * @param {string} props.dataOid - QA 테스트용 data-oid 식별자
 * @returns {JSX.Element} 변환 모델 가격 카드
 */
function ModelPriceCard({
  badge,
  icon: Icon,
  iconBgClass,
  iconColorClass,
  title,
  desc,
  price,
  priceColorClass,
  subPrice,
  features,
  dataOid,
}) {
  return (
    <div
      className="relative bg-white rounded-3xl p-7 shadow-lg border border-slate-200 flex flex-col"
      data-oid={dataOid}
    >
      {badge && (
        <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-gradient-to-r from-rose-400 to-orange-400 text-white text-xs font-bold px-3 py-1 rounded-full shadow-sm">
          {badge}
        </div>
      )}
      <div className="flex flex-col items-center text-center mb-6">
        <div
          className={`w-16 h-16 rounded-2xl ${iconBgClass} flex items-center justify-center mb-4 shadow-sm`}
        >
          <Icon className={iconColorClass} size={32} />
        </div>
        <h3 className="text-lg font-bold text-slate-900">{title}</h3>
        <p className="text-sm text-slate-500 mt-1">{desc}</p>
      </div>
      <div className="text-center mb-5">
        <p className={`text-4xl font-extrabold ${priceColorClass} mb-1`}>
          {price}
        </p>
        {subPrice && (
          <p className="text-sm font-medium text-slate-600">{subPrice}</p>
        )}
      </div>
      <ul className="space-y-3 mt-auto w-fit mx-auto">
        {features.map((feature, index) => (
          <li
            key={index}
            className="flex items-start gap-2 text-sm text-slate-600"
          >
            <Check
              size={16}
              className="text-emerald-500 mt-0.5 flex-shrink-0"
            />
            <span>{feature}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * 가격 정책 페이지를 렌더링합니다.
 * @returns {JSX.Element} 가격 페이지 전체 UI
 */
export default function ApiPricingPage() {
  const { t } = useTranslation();
  const nav = useNavigate();

  const exportFormats = [
    {
      key: "md",
      icon: FileCode,
      iconBgClass: "bg-slate-100",
      iconColorClass: "text-slate-600",
      label: t("page:price.exportMarkdown"),
      price: t("page:price.exportFree"),
      priceColorClass: "text-green-600",
      dataOid: "price-export-md",
    },
    {
      key: "docx",
      icon: FileType,
      iconBgClass: "bg-blue-100",
      iconColorClass: "text-blue-600",
      label: t("page:price.exportWord"),
      price: t("page:price.exportFree"),
      priceColorClass: "text-green-600",
      dataOid: "price-export-docx",
    },
{
      key: "xlsx-basic",
      icon: FileSpreadsheet,
      iconBgClass: "bg-emerald-100",
      iconColorClass: "text-emerald-600",
      label: t("page:price.exportExcelBasic"),
      price: t("page:price.exportExcelBasicPrice"),
      priceColorClass: "text-blue-600",
      dataOid: "price-export-xlsx-basic",
    },
    {
      key: "xlsx-advanced",
      icon: Table2,
      iconBgClass: "bg-indigo-100",
      iconColorClass: "text-indigo-600",
      label: t("page:price.exportExcelAdvanced"),
      price: t("page:price.exportExcelAdvancedPrice"),
      priceColorClass: "text-indigo-600",
      dataOid: "price-export-xlsx-advanced",
    },
  ];

  return (
    <div
      className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50/60 to-rose-50/40"
      data-oid="price-page"
    >
      <header
        className="border-b bg-white/80 backdrop-blur"
        data-oid="price-header"
      >
        <div
          className="max-w-5xl mx-auto px-6 py-4 flex items-center gap-2"
          data-oid="price-header-inner"
        >
          <button
            onClick={() => nav(-1)}
            className="text-slate-500 hover:text-slate-800"
            data-oid="price-back"
          >
            <ArrowLeft size={20} />
          </button>
          <h1 className="text-xl font-bold" data-oid="api-price-title">
            {t("page:price.apiTitle")}
          </h1>
        </div>
      </header>

      <main
        className="max-w-5xl mx-auto px-6 py-10"
        data-oid="price-main"
      >
        <div className="text-center mb-12" data-oid="price-hero">
          <h2
            className="text-3xl font-bold text-slate-900 mb-3"
            data-oid="price-hero-title"
          >
            {t("page:price.apiTitle")}
          </h2>
          <p
            className="text-lg text-slate-600 max-w-2xl mx-auto"
            data-oid="price-hero-desc"
          >
            {t("page:price.apiSubtitle")}
          </p>
        </div>

        <div
          className="bg-blue-50 border border-blue-100 rounded-2xl p-5 mb-10 text-center"
          data-oid="api-price-subscription-notice"
        >
          <p className="text-blue-800 text-sm font-medium mb-2">
            {t("page:price.subscriptionNotice")}
          </p>
          <Link
            to="/price"
            className="inline-flex items-center gap-1 text-blue-600 hover:underline font-semibold"
            data-oid="api-price-to-price-link"
          >
            {t("page:price.subscriptionLink")}
          </Link>
        </div>

        {/* 크레딧 구매 섹션 (API 요금제 — Paddle 체크아웃과 동일한 상품/가격) */}
        <div
          className="bg-white border border-slate-200 rounded-3xl p-6 md:p-8 shadow-lg mb-14"
          data-oid="price-credit-card"
        >
          <div className="flex items-center gap-3 mb-4">
            <div className="w-12 h-12 bg-gradient-to-br from-emerald-100 to-teal-50 rounded-xl flex items-center justify-center shadow-sm">
              <Coins className="text-emerald-600" size={24} />
            </div>
            <h2 className="text-xl font-bold text-slate-900">
              {t("page:price.creditTitle")}
            </h2>
          </div>
          <p className="text-slate-600 mb-4">
            {t("page:price.creditDesc")}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
            <div className="bg-slate-50 rounded-2xl p-4 text-center">
              <p className="text-sm text-slate-500 mb-1">{t("page:price.creditProduct")}</p>
              <p className="text-3xl font-extrabold text-emerald-600">
                {t("page:price.creditUnitPrice")}
              </p>
              <p className="text-sm text-slate-500 mt-1">{t("page:price.creditMinimum")}</p>
            </div>
            <div className="bg-slate-50 rounded-2xl p-4 flex flex-col justify-center">
              <p className="text-sm text-slate-500 mb-1">{t("page:price.creditExamples")}</p>
            </div>
          </div>
          <div className="text-center mb-6">
            <p className="text-sm text-slate-500 mb-1">
              {t("legal.consent.taxNotice")}
            </p>
            <p className="text-sm text-slate-500">
              {t("page:price.refundNotice")}
            </p>
          </div>
          <div className="flex justify-center">
            <Link
              to="/payment"
              className="inline-flex items-center justify-center gap-2 w-full sm:w-auto bg-gradient-to-r from-blue-500 to-cyan-500 text-white px-6 py-3 rounded-xl font-semibold hover:from-blue-600 hover:to-cyan-600 transition-all shadow-sm"
              data-oid="price-recharge-link"
            >
              <Coins size={18} />
              {t("page:price.rechargeButton")}
            </Link>
          </div>
        </div>

        {/* 크레딧 사용률 (모델별 페이지당 가격) */}
        <h2
          className="text-xl font-bold text-slate-900 mb-6 text-center"
          data-oid="price-models-title"
        >
          {t("page:price.modelsTitle")}
        </h2>
        <div
          className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-14"
          data-oid="price-model-cards"
        >
          <ModelPriceCard
            icon={FileText}
            iconBgClass="bg-gradient-to-br from-blue-100 to-cyan-50"
            iconColorClass="text-blue-600"
            title={t("page:price.basicTitle")}
            desc={t("page:price.basicDesc")}
            price={t("page:price.basicPrice")}
            priceColorClass="text-blue-600"
            subPrice={t("page:price.basicFree")}
            features={[
              t("page:price.basicFeature1"),
              t("page:price.basicFeature2"),
              t("page:price.basicFeature3"),
            ]}
            dataOid="price-basic-card"
          />
          <ModelPriceCard
            badge={t("page:price.mostPopular")}
            icon={Sparkles}
            iconBgClass="bg-gradient-to-br from-rose-100 to-orange-50"
            iconColorClass="text-rose-500"
            title={t("page:price.premiumTitle")}
            desc={t("page:price.premiumDesc")}
            price={t("page:price.premiumPricePdf")}
            priceColorClass="text-rose-500"
            subPrice={`${t("page:price.premiumPriceAudio")} · ${t(
              "page:price.premiumPriceVideo"
            )}`}
            features={[
              t("page:price.premiumFeature1"),
              t("page:price.premiumFeature2"),
              t("page:price.premiumFeature3"),
            ]}
            dataOid="price-premium-card"
          />
        </div>

        <h2
          className="text-xl font-bold text-slate-900 mb-6 text-center"
          data-oid="price-exports-title"
        >
          {t("page:price.exportsTitle")}
        </h2>
        <div
          className="flex gap-4 flex-wrap justify-center mb-14"
          data-oid="price-exports-list"
        >
          {exportFormats.map((format) => (
            <ExportFormatCard key={format.key} {...format} />
          ))}
        </div>
      </main>
      <GlobalFooter />
    </div>
  );
}
