import i18next from "i18next";
import { initReactI18next } from "react-i18next";
import {
  readLanguagePreference,
  resolveLanguage,
  writeLanguagePreference,
  type LanguagePreference,
  type SupportedLanguage,
} from "./languagePreferences";
import { namespaceKeys, resources } from "./resources";

type NativeLanguageSync = (
  preference: LanguagePreference,
  effectiveLanguage: SupportedLanguage,
) => void | Promise<void>;

let languagePreference = readStoredLanguagePreference();
let nativeLanguageSync: NativeLanguageSync | undefined;

function getBrowserLanguages(): readonly string[] {
  if (typeof navigator === "undefined") return [];
  if (navigator.languages.length > 0) return navigator.languages;
  return navigator.language ? [navigator.language] : [];
}

function readStoredLanguagePreference(): LanguagePreference {
  if (typeof window === "undefined") return "system";
  try {
    return readLanguagePreference(window.localStorage);
  } catch {
    return "system";
  }
}

function writeStoredLanguagePreference(preference: LanguagePreference): void {
  if (typeof window === "undefined") return;
  try {
    writeLanguagePreference(window.localStorage, preference);
  } catch {
    // Accessing localStorage itself can fail in restricted browser contexts.
  }
}

function synchronizeDocument(): void {
  if (typeof document === "undefined") return;
  document.documentElement.lang = i18n.resolvedLanguage ?? "en";
  document.title = i18n.t("documentTitle", { ns: "common" });
}

export const i18n = i18next.createInstance();

void i18n.use(initReactI18next).init({
  resources,
  lng: resolveLanguage(languagePreference, getBrowserLanguages()),
  supportedLngs: ["en", "zh-CN"],
  fallbackLng: "en",
  ns: namespaceKeys,
  defaultNS: "common",
  initImmediate: false,
  showSupportNotice: false,
  interpolation: { escapeValue: false },
});

synchronizeDocument();

/** Registers the optional native-shell synchronization callback. */
export function registerNativeLanguageSync(callback: NativeLanguageSync | undefined): void {
  nativeLanguageSync = callback;
}

async function synchronizeNative(
  preference: LanguagePreference,
  effectiveLanguage: SupportedLanguage,
): Promise<void> {
  try {
    await nativeLanguageSync?.(preference, effectiveLanguage);
  } catch {
    // Native-shell synchronization is optional and must not block the web UI.
  }
}

export async function setUiLanguagePreference(next: LanguagePreference): Promise<void> {
  languagePreference = next;
  writeStoredLanguagePreference(next);
  const effectiveLanguage = resolveLanguage(next, getBrowserLanguages());
  await i18n.changeLanguage(effectiveLanguage);
  synchronizeDocument();
  await synchronizeNative(next, effectiveLanguage);
}

if (typeof window !== "undefined") {
  window.addEventListener("languagechange", () => {
    if (languagePreference !== "system") return;
    const effectiveLanguage = resolveLanguage("system", getBrowserLanguages());
    void i18n.changeLanguage(effectiveLanguage).then(async () => {
      synchronizeDocument();
      await synchronizeNative("system", effectiveLanguage);
    });
  });
}
