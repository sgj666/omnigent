// Locale normalization for the native Electron shell. The web bundle accepts
// the same small preference set, while native APIs need one effective locale
// for their own copy.

"use strict";

const LANGUAGE_PREFERENCES = new Set(["system", "en", "zh-CN"]);
const SUPPORTED_LANGUAGES = new Set(["en", "zh-CN"]);

function isLanguagePreference(value) {
  return typeof value === "string" && LANGUAGE_PREFERENCES.has(value);
}

function isSupportedLanguage(value) {
  return typeof value === "string" && SUPPORTED_LANGUAGES.has(value);
}

function resolveSystemLanguage(osLocale) {
  const values = Array.isArray(osLocale) ? osLocale : [osLocale];
  for (const value of values) {
    if (typeof value !== "string") continue;
    const normalized = value.toLowerCase();
    if (normalized.startsWith("zh")) return "zh-CN";
    if (normalized.startsWith("en")) return "en";
  }
  return "en";
}

function resolveDesktopLocale(preference, osLocale) {
  const normalizedPreference = isLanguagePreference(preference) ? preference : "system";
  return {
    preference: normalizedPreference,
    effectiveLanguage:
      normalizedPreference === "system" ? resolveSystemLanguage(osLocale) : normalizedPreference,
  };
}

function normalizeDesktopLocale(settings = {}, osLocale) {
  return resolveDesktopLocale(settings?.ui_language, osLocale);
}

module.exports = {
  LANGUAGE_PREFERENCES,
  SUPPORTED_LANGUAGES,
  isLanguagePreference,
  isSupportedLanguage,
  resolveSystemLanguage,
  resolveDesktopLocale,
  normalizeDesktopLocale,
};
