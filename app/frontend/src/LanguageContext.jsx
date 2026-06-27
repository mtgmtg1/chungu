// [Flow: Step 1 (init i18n) -> Step 2 (detect or load saved language from localStorage/Supabase) -> Step 3 (change language and persist) -> Step 4 (provide context)]
import { createContext, useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "./api.js";

const LanguageContext = createContext(null);

const STORAGE_KEY = "chungu-language";
const SUPPORTED_LANGUAGES = ["en", "ko", "ja"];

function normalizeLanguage(raw) {
  if (!raw) return "en";
  const base = raw.split("-")[0].toLowerCase();
  if (SUPPORTED_LANGUAGES.includes(base)) return base;
  return "en";
}

export function LanguageProvider({ children }) {
  const { i18n } = useTranslation();
  const [language, setLanguageState] = useState("en");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function init() {
      const saved = localStorage.getItem(STORAGE_KEY);
      const browserLang = normalizeLanguage(navigator.language);
      const initialLang = normalizeLanguage(saved || browserLang);
      await i18n.changeLanguage(initialLang);
      setLanguageState(initialLang);
      setLoading(false);
    }
    init();
  }, [i18n]);

  useEffect(() => {
    if (loading) return;
    document.documentElement.lang = language;
  }, [language, loading]);

  const setLanguage = async (lang) => {
    const next = normalizeLanguage(lang);
    if (next === language) return;
    await i18n.changeLanguage(next);
    setLanguageState(next);
    localStorage.setItem(STORAGE_KEY, next);
    try {
      await api.updateLanguage({ language: next });
    } catch {
      // Ignore network errors for language persistence
    }
  };

  return (
    <LanguageContext.Provider
      value={{
        language,
        setLanguage,
        loading,
        supportedLanguages: SUPPORTED_LANGUAGES,
      }}
      data-oid="dt6ognq"
    >
      {children}
    </LanguageContext.Provider>
  );
}

export const useLanguage = () => useContext(LanguageContext);
