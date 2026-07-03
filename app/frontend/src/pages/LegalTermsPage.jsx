// [Flow: Step 1 (페이지 진입) -> Step 2 (i18n으로 다국어 약관 렌더링, 18조 6장 구조) -> Step 3 (뒤로 가기 버튼)]
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

const LEGAL_EMAIL = "admin@proof.teamcat.app";

/**
 * 다단락 텍스트를 \n 기준으로 분리하여 <p> 요소 배열로 렌더링
 * @param {string} text - i18n 번역 텍스트 (\n으로 단락 구분)
 * @returns {JSX.Element[]} <p> 요소 배열
 */
const renderParagraphs = (text) =>
  text.split("\n").map((paragraph, index) => (
    <p key={index} className="mb-3 leading-relaxed">{paragraph}</p>
  ));

export default function LegalTermsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-gray-50 py-12 px-4">
      <div className="max-w-3xl mx-auto bg-white rounded-xl shadow-sm p-8 md:p-12">
        <button
          onClick={() => navigate(-1)}
          className="text-sm text-gray-500 hover:text-gray-700 mb-6 inline-flex items-center gap-1"
        >
          ← {t("actions.back")}
        </button>

        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          {t("legal.terms.title")}
        </h1>
        <p className="text-sm text-gray-400 mb-8">
          {t("legal.terms.lastUpdated")}: 2026-07-03
        </p>

        <div className="prose prose-sm max-w-none text-gray-700 space-y-6">
          {/* 제1장 총칙 및 이용계약 체결 */}
          <h2 className="text-xl font-bold text-gray-900 border-b pb-2 pt-4">{t("legal.terms.ch1Title")}</h2>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s1Title")}</h3>{renderParagraphs(t("legal.terms.s1Body"))}</section>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s2Title")}</h3>{renderParagraphs(t("legal.terms.s2Body"))}</section>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s3Title")}</h3>{renderParagraphs(t("legal.terms.s3Body"))}</section>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s4Title")}</h3>{renderParagraphs(t("legal.terms.s4Body"))}</section>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s5Title")}</h3>{renderParagraphs(t("legal.terms.s5Body"))}</section>

          {/* 제2장 서비스 아키텍처의 제공 및 기술적 한계 */}
          <h2 className="text-xl font-bold text-gray-900 border-b pb-2 pt-4">{t("legal.terms.ch2Title")}</h2>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s6Title")}</h3>{renderParagraphs(t("legal.terms.s6Body"))}</section>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s7Title")}</h3>{renderParagraphs(t("legal.terms.s7Body"))}</section>

          {/* 제3장 데이터 국지화 및 개인정보의 엄격한 보호 */}
          <h2 className="text-xl font-bold text-gray-900 border-b pb-2 pt-4">{t("legal.terms.ch3Title")}</h2>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s8Title")}</h3>{renderParagraphs(t("legal.terms.s8Body"))}</section>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s9Title")}</h3>{renderParagraphs(t("legal.terms.s9Body"))}</section>

          {/* 제4장 자체 호스팅 AI의 지식재산권 정책 및 환각 면책 */}
          <h2 className="text-xl font-bold text-gray-900 border-b pb-2 pt-4">{t("legal.terms.ch4Title")}</h2>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s10Title")}</h3>{renderParagraphs(t("legal.terms.s10Body"))}</section>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s11Title")}</h3>{renderParagraphs(t("legal.terms.s11Body"))}</section>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s12Title")}</h3>{renderParagraphs(t("legal.terms.s12Body"))}</section>

          {/* 제5장 API 모네타이제이션 및 B2B 생태계의 엄격한 책임 통제 */}
          <h2 className="text-xl font-bold text-gray-900 border-b pb-2 pt-4">{t("legal.terms.ch5Title")}</h2>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s13Title")}</h3>{renderParagraphs(t("legal.terms.s13Body"))}</section>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s14Title")}</h3>{renderParagraphs(t("legal.terms.s14Body"))}</section>

          {/* 제6장 총괄적 책임 제한, 수출 통제 및 분쟁 해결 */}
          <h2 className="text-xl font-bold text-gray-900 border-b pb-2 pt-4">{t("legal.terms.ch6Title")}</h2>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s15Title")}</h3>{renderParagraphs(t("legal.terms.s15Body"))}</section>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s16Title")}</h3>{renderParagraphs(t("legal.terms.s16Body"))}</section>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s17Title")}</h3>{renderParagraphs(t("legal.terms.s17Body"))}</section>
          <section><h3 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s18Title")}</h3>{renderParagraphs(t("legal.terms.s18Body"))}</section>

          <section className="border-t pt-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.contactTitle")}</h2>
            <p>
              {t("legal.terms.contactBody")}{" "}
              <a href={`mailto:${LEGAL_EMAIL}`} className="text-blue-600 hover:underline">
                {LEGAL_EMAIL}
              </a>
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
