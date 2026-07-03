// [Flow: Step 1 (페이지 진입) -> Step 2 (i18n으로 다국어 약관 렌더링) -> Step 3 (뒤로 가기 버튼)]
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

const LEGAL_EMAIL = "admin@proof.teamcat.app";

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
          {t("legal.terms.lastUpdated")}: 2026-01-01
        </p>

        <div className="prose prose-sm max-w-none text-gray-700 space-y-6">
          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s1Title")}</h2>
            <p>{t("legal.terms.s1Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s2Title")}</h2>
            <p>{t("legal.terms.s2Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s3Title")}</h2>
            <p>{t("legal.terms.s3Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s4Title")}</h2>
            <p>{t("legal.terms.s4Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s5Title")}</h2>
            <p>{t("legal.terms.s5Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s6Title")}</h2>
            <p>{t("legal.terms.s6Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s7Title")}</h2>
            <p>{t("legal.terms.s7Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s8Title")}</h2>
            <p>{t("legal.terms.s8Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s9Title")}</h2>
            <p>{t("legal.terms.s9Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s10Title")}</h2>
            <p>{t("legal.terms.s10Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s11Title")}</h2>
            <p>{t("legal.terms.s11Body")}</p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{t("legal.terms.s12Title")}</h2>
            <p>{t("legal.terms.s12Body")}</p>
          </section>

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
