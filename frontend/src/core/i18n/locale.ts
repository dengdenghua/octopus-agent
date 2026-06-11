export const SUPPORTED_LOCALES = ["en-US", "zh-CN", "ja-JP", "ko-KR"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en-US";

export type LangCode = "en" | "zh" | "ja" | "ko";

export const I18N_CONFIG: Array<{
  locale: LangCode;
  name: string;
  fullLocale: Locale;
}> = [
  { locale: "en", name: "English", fullLocale: "en-US" },
  { locale: "zh", name: "中文", fullLocale: "zh-CN" },
  { locale: "ja", name: "日本語", fullLocale: "ja-JP" },
  { locale: "ko", name: "한국어", fullLocale: "ko-KR" },
];

export const SUPPORTED_LANGS = I18N_CONFIG.map((c) => c.locale);

export const DEFAULT_LANG: LangCode = "en";

/* Implementation note. */
const LANG_TO_LOCALE_MAP = new Map<string, Locale>(
  I18N_CONFIG.map(({ locale, fullLocale }) => [locale, fullLocale]),
);

export function isLocale(value: string): value is Locale {
  return (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

export function getLocaleByLang(lang: string): Locale {
  return LANG_TO_LOCALE_MAP.get(lang.toLowerCase()) ?? DEFAULT_LOCALE;
}

export function normalizeLocale(locale: string | null | undefined): Locale {
  if (!locale) {
    return DEFAULT_LOCALE;
  }

  if (isLocale(locale)) {
    return locale;
  }

  // Implementation note.
  const lower = locale.toLowerCase();
  for (const { locale: langCode, fullLocale } of I18N_CONFIG) {
    if (lower.startsWith(langCode)) {
      return fullLocale;
    }
  }

  return DEFAULT_LOCALE;
}

// Helper function to detect browser locale
export function detectLocale(): Locale {
  if (typeof window === "undefined") {
    return DEFAULT_LOCALE;
  }

  return normalizeLocale(navigator.language);
}
