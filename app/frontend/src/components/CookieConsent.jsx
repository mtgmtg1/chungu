// [Flow: Step 1 (localStorage에서 동의 여부 확인) -> Step 2 (미동의 시 배너 표시) -> Step 3 (동의/거절 시 localStorage 저장 후 배너 숨김)]
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

const STORAGE_KEY = "proof_cookie_consent";

export default function CookieConsent() {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const consent = localStorage.getItem(STORAGE_KEY);
    if (!consent) setVisible(true);
  }, []);

  const handleAccept = () => {
    localStorage.setItem(STORAGE_KEY, "accepted");
    setVisible(false);
  };

  const handleDecline = () => {
    localStorage.setItem(STORAGE_KEY, "declined");
    setVisible(false);
  };

  const handleEssentialOnly = () => {
    localStorage.setItem(STORAGE_KEY, "essential_only");
    setVisible(false);
  };

  if (!visible) return null;

  return (
    <div className="fixed bottom-0 left-0 right-0 z-50 bg-gray-900 text-white px-4 py-3 md:py-4 shadow-lg">
      <div className="max-w-4xl mx-auto flex flex-col sm:flex-row items-center gap-4">
        <p className="text-sm flex-1">
          {t("legal.cookie.message")}{" "}
          <Link to="/privacy" className="text-blue-400 hover:underline">
            {t("legal.cookie.learnMore")}
          </Link>
        </p>
        <div className="flex flex-col md:flex-row gap-3 shrink-0 w-full md:w-auto">
          <button
            onClick={handleDecline}
            className="text-sm text-gray-300 hover:text-white px-4 py-2 rounded-lg border border-gray-600 hover:border-gray-400 transition-colors w-full md:w-auto"
          >
            {t("legal.cookie.decline")}
          </button>
          <button
            onClick={handleEssentialOnly}
            className="text-sm text-gray-200 hover:text-white px-4 py-2 rounded-lg border border-gray-500 hover:border-gray-300 transition-colors w-full md:w-auto"
          >
            {t("legal.cookie.essentialOnly")}
          </button>
          <button
            onClick={handleAccept}
            className="text-sm text-white bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg transition-colors w-full md:w-auto"
          >
            {t("legal.cookie.accept")}
          </button>
        </div>
      </div>
    </div>
  );
}
