// [Flow: Step 1 (read current language) -> Step 2 (render dropdown) -> Step 3 (change language on selection)]
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useLanguage } from "../LanguageContext.jsx";

const LANGUAGE_OPTIONS = [
  { value: "en", label: "English", flag: "🇺🇸" },
  { value: "ko", label: "한국어", flag: "🇰🇷" },
  { value: "ja", label: "日本語", flag: "🇯🇵" },
];

export default function LanguageSelector() {
  const { i18n } = useTranslation();
  const { language, setLanguage } = useLanguage();
  const [open, setOpen] = useState(false);

  const current =
    LANGUAGE_OPTIONS.find((l) => l.value === language) || LANGUAGE_OPTIONS[0];

  const handleSelect = async (value) => {
    await setLanguage(value);
    setOpen(false);
  };

  return (
    <div className="relative" data-oid="0oty5r_">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-outline-variant text-on-surface-variant hover:text-primary hover:border-primary/30 transition-colors text-sm"
        aria-label={i18n.t("language.label", "Language")}
        data-oid="tvb93dz"
      >
        <span className="text-base" data-oid="_.pi4h6">
          {current.flag}
        </span>
        <span className="font-medium uppercase" data-oid="ft433iw">
          {current.value}
        </span>
      </button>
      {open && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
            data-oid="x.h9ef0"
          />

          <div
            className="absolute right-0 top-full mt-2 w-40 bg-surface rounded-xl shadow-lg border border-outline-variant z-50 py-1"
            data-oid=".-i..zq"
          >
            {LANGUAGE_OPTIONS.map((option) => (
              <button
                key={option.value}
                onClick={() => handleSelect(option.value)}
                className={`w-full flex items-center gap-3 px-4 py-2 text-sm text-left transition-colors ${
                  language === option.value
                    ? "bg-primary-container/10 text-primary font-medium"
                    : "text-on-surface hover:bg-surface-container-high"
                }`}
                data-oid="v1livaz"
              >
                <span className="text-base" data-oid="lbuahhb">
                  {option.flag}
                </span>
                <span data-oid=".rhchmy">{option.label}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
