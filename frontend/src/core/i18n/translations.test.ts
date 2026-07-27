import { describe, expect, it } from "vitest";

import { SUPPORTED_LOCALES, type Locale } from "./locale";
import { enUS, jaJP, koKR, zhCN, type Translations } from "./locales";
import { loadTranslations } from "./translations";

const TRANSLATIONS_BY_LOCALE: Record<Locale, Translations> = {
  "en-US": enUS,
  "zh-CN": zhCN,
  "ja-JP": jaJP,
  "ko-KR": koKR,
};

describe("translation bundles", () => {
  it("has a static bundle for every supported locale", () => {
    expect(Object.keys(TRANSLATIONS_BY_LOCALE).sort()).toEqual(
      [...SUPPORTED_LOCALES].sort(),
    );
  });

  it("keeps every locale structurally aligned with en-US", () => {
    const expectedShape = collectShape(enUS);

    for (const locale of SUPPORTED_LOCALES) {
      expect(collectShape(TRANSLATIONS_BY_LOCALE[locale]), locale).toEqual(
        expectedShape,
      );
    }
  });

  it("loads and caches every supported locale", async () => {
    for (const locale of SUPPORTED_LOCALES) {
      const first = await loadTranslations(locale);
      const second = await loadTranslations(locale);

      expect(first, locale).toBe(TRANSLATIONS_BY_LOCALE[locale]);
      expect(second, locale).toBe(first);
    }
  });
});

const DYNAMIC_RECORD_PATHS = new Set([
  "$.personality.categories",
  "$.personality.templateDescriptions",
  "$.personality.templateNames",
  // These bundles use English-source-string keys: en-US is intentionally
  // empty (the key IS the value), other locales map English→translation.
  // Shape comparison must treat them as opaque records, not expand keys.
  "$.workspaceComputer",
  "$.agentOperator",
]);

function collectShape(value: unknown, path = "$"): string[] {
  if (Array.isArray(value)) {
    return [`${path}:array`];
  }

  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const keys = Object.keys(record).sort();
    if (DYNAMIC_RECORD_PATHS.has(path)) {
      return [`${path}:object`];
    }
    return [
      `${path}:object:${keys.join(",")}`,
      ...keys.flatMap((key) => collectShape(record[key], `${path}.${key}`)),
    ];
  }

  return [`${path}:${typeof value}`];
}
