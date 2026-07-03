// [Flow: Step 1 (페이지 진입) -> Step 2 (i18n으로 다국어 개인정보처리방침 렌더링) -> Step 3 (뒤로 가기 버튼)]
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

const LEGAL_EMAIL = "admin@proof.teamcat.app";

export default function LegalPrivacyPage() {
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
          {t("legal.privacy.title")}
        </h1>
        <p className="text-sm text-gray-400 mb-8">
          {t("legal.privacy.lastUpdated")}: 2026-01-01
        </p>

        <div className="prose prose-sm max-w-none text-gray-700 space-y-6">
          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.privacy.s1Title")}</h2>
            <p>{t("legal.privacy.s1Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.privacy.s2Title")}</h2>
            <p>{t("legal.privacy.s2Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.privacy.s3Title")}</h2>
            <p>{t("legal.privacy.s3Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.privacy.s4Title")}</h2>
            <p>{t("legal.privacy.s4Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.privacy.s5Title")}</h2>
            <p>{t("legal.privacy.s5Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.privacy.s6Title")}</h2>
            <p>{t("legal.privacy.s6Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.privacy.s7Title")}</h2>
            <p>{t("legal.privacy.s7Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.privacy.s8Title")}</h2>
            <p>{t("legal.privacy.s8Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.privacy.s9Title")}</h2>
            <p>{t("legal.privacy.s9Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.privacy.s10Title")}</h2>
            <p>{t("legal.privacy.s10Body")}</p>
          </section>

          <section className="border-t pt-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.privacy.contactTitle")}</h2>
            <p>
              {t("legal.privacy.contactBody")}{" "}
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
