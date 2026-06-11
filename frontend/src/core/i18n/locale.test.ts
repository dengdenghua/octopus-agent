import { describe, expect, it } from "vitest";

import {
  DEFAULT_LOCALE,
  I18N_CONFIG,
  SUPPORTED_LOCALES,
  detectLocale,
  getLocaleByLang,
  isLocale,
  normalizeLocale,
} from "./locale";

describe("isLocale", () => {
  it("returns true for supported locales", () => {
    expect(isLocale("en-US")).toBe(true);
    expect(isLocale("zh-CN")).toBe(true);
    expect(isLocale("ja-JP")).toBe(true);
    expect(isLocale("ko-KR")).toBe(true);
  });

  it("returns false for unsupported values", () => {
    expect(isLocale("fr-FR")).toBe(false);
    expect(isLocale("en")).toBe(false);
    expect(isLocale("")).toBe(false);
  });
});

describe("getLocaleByLang", () => {
  it("maps en to en-US", () => {
    expect(getLocaleByLang("en")).toBe("en-US");
  });

  it("maps zh to zh-CN", () => {
    expect(getLocaleByLang("zh")).toBe("zh-CN");
  });

  it("maps ja to ja-JP", () => {
    expect(getLocaleByLang("ja")).toBe("ja-JP");
  });

  it("maps ko to ko-KR", () => {
    expect(getLocaleByLang("ko")).toBe("ko-KR");
  });

  it("is case-insensitive", () => {
    expect(getLocaleByLang("EN")).toBe("en-US");
    expect(getLocaleByLang("ZH")).toBe("zh-CN");
    expect(getLocaleByLang("JA")).toBe("ja-JP");
    expect(getLocaleByLang("KO")).toBe("ko-KR");
  });

  it("returns default for unknown lang", () => {
    expect(getLocaleByLang("fr")).toBe(DEFAULT_LOCALE);
  });
});

describe("normalizeLocale", () => {
  it("returns exact match for supported locale", () => {
    expect(normalizeLocale("en-US")).toBe("en-US");
    expect(normalizeLocale("zh-CN")).toBe("zh-CN");
    expect(normalizeLocale("ja-JP")).toBe("ja-JP");
    expect(normalizeLocale("ko-KR")).toBe("ko-KR");
  });

  it("normalizes prefix to full locale", () => {
    expect(normalizeLocale("zh")).toBe("zh-CN");
    expect(normalizeLocale("zh-TW")).toBe("zh-CN");
    expect(normalizeLocale("en")).toBe("en-US");
    expect(normalizeLocale("en-GB")).toBe("en-US");
    expect(normalizeLocale("ja")).toBe("ja-JP");
    expect(normalizeLocale("ja-JP-mac")).toBe("ja-JP");
    expect(normalizeLocale("ko")).toBe("ko-KR");
  });

  it("returns default for null/undefined/empty", () => {
    expect(normalizeLocale(null)).toBe(DEFAULT_LOCALE);
    expect(normalizeLocale(undefined)).toBe(DEFAULT_LOCALE);
    expect(normalizeLocale("")).toBe(DEFAULT_LOCALE);
  });

  it("returns default for unknown locale", () => {
    expect(normalizeLocale("fr-FR")).toBe(DEFAULT_LOCALE);
  });
});

describe("detectLocale", () => {
  it("returns a supported locale based on navigator.language", () => {
    const result = detectLocale();
    expect(SUPPORTED_LOCALES).toContain(result);
  });
});

describe("I18N_CONFIG", () => {
  it("contains one entry per supported locale", () => {
    const fullLocales = I18N_CONFIG.map((c) => c.fullLocale).sort();
    const expected = [...SUPPORTED_LOCALES].sort();
    expect(fullLocales).toEqual(expected);
  });
});
