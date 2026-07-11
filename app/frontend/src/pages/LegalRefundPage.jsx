// [Flow: Step 1 (페이지 진입) -> Step 2 (i18n으로 다국어 환불 정책 렌더링) -> Step 3 (뒤로 가기 버튼)]
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import GlobalFooter from "../components/GlobalFooter.jsx";

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

export default function LegalRefundPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-gray-50 py-6 md:py-12 px-4">
      <div className="max-w-3xl mx-auto bg-white rounded-xl shadow-sm p-5 md:p-8 lg:p-12">
        <button
          onClick={() => navigate(-1)}
          className="text-sm text-gray-500 hover:text-gray-700 mb-6 inline-flex items-center gap-1"
        >
          ← {t("actions.back")}
        </button>

        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          {t("legal.refund.title")}
        </h1>
        <p className="text-sm text-gray-400 mb-8">
          {t("legal.refund.lastUpdated")}: {t("legal.refund.effectiveDate")}
        </p>

        <div className="prose prose-sm max-w-none text-gray-700 space-y-6">
          {renderParagraphs(t("legal.refund.body"))}

          <section className="border-t pt-6">
            <p>
              <a href={`mailto:${LEGAL_EMAIL}`} className="text-blue-600 hover:underline">
                {LEGAL_EMAIL}
              </a>
            </p>
          </section>
        </div>
      </div>
      <GlobalFooter />
    </div>
  );
}
