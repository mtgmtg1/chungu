// [Flow: Step 1 (페이지 진입) -> Step 2 (i18n으로 12조 개인정보처리방침 렌더링) -> Step 3 (뒤로 가기 버튼)]
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

const LEGAL_EMAIL = "admin@proof.teamcat.app";

/**
 * LegalPrivacyPage 컴포넌트
 * 목적: i18n translation 키를 사용하여 다국어 개인정보처리방침(12조) 페이지 렌더링
 * 반환값: JSX 페이지 요소
 */
export default function LegalPrivacyPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  // 12조 섹션 키 배열 — 순서대로 렌더링
  const sectionKeys = Array.from({ length: 12 }, (_, i) => i + 1);

  // [Flow: Step 1 (페이지 컨테이너) -> Step 2 (제목 + intro) -> Step 3 (12조 섹션 반복 렌더링) -> Step 4 (문의처)]
  return (
    <div className="min-h-screen bg-gray-50 py-12 px-4">
      <div className="max-w-3xl mx-auto bg-white rounded-xl shadow-sm p-8 md:p-12">
        {/* 뒤로 가기 버튼 */}
        <button
          onClick={() => navigate(-1)}
          className="text-sm text-gray-500 hover:text-gray-700 mb-6 inline-flex items-center gap-1"
        >
          ← {t("actions.back")}
        </button>

        {/* 제목 및 시행일자 */}
        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          {t("legal.privacy.title")}
        </h1>
        <p className="text-sm text-gray-400 mb-8">
          {t("legal.privacy.lastUpdated")}: {t("legal.privacy.effectiveDate")}
        </p>

        {/* 도입부 (intro) */}
        <p className="text-base leading-relaxed text-gray-700 mb-8 whitespace-pre-line">
          {t("legal.privacy.intro")}
        </p>

        {/* 12조 섹션 반복 렌더링 */}
        <div className="text-gray-700 space-y-8">
          {sectionKeys.map((num) => (
            <section key={num}>
              <h2 className="text-xl font-bold text-gray-900 mb-3">
                {t(`legal.privacy.s${num}Title`)}
              </h2>
              <p className="text-base leading-relaxed text-gray-700 whitespace-pre-line">
                {t(`legal.privacy.s${num}Body`)}
              </p>
            </section>
          ))}

          {/* 문의처 섹션 */}
          <section className="border-t pt-6">
            <h2 className="text-xl font-bold text-gray-900 mb-3">
              {t("legal.privacy.contactTitle")}
            </h2>
            <p className="text-base leading-relaxed text-gray-700">
              {t("legal.privacy.contactBody")}{" "}
              <a
                href={`mailto:${LEGAL_EMAIL}`}
                className="text-blue-600 hover:underline"
              >
                {LEGAL_EMAIL}
              </a>
            </p>
          </section>
        </div>
      </div>
    </div>
  );
}
