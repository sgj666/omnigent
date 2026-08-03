import { i18n, setUiLanguagePreference } from "./index";
import {
  readLanguagePreference,
  type LanguagePreference,
  type SupportedLanguage,
} from "./languagePreferences";

function currentPreference(): LanguagePreference {
  if (typeof window === "undefined") return "system";
  try {
    return readLanguagePreference(window.localStorage);
  } catch {
    return "system";
  }
}

export async function setTestLanguage(language: SupportedLanguage): Promise<() => Promise<void>> {
  const previousPreference = currentPreference();
  await setUiLanguagePreference(language);
  return async () => setUiLanguagePreference(previousPreference);
}

export async function withTestLanguage<T>(
  language: SupportedLanguage,
  run: () => T | Promise<T>,
): Promise<T> {
  const restore = await setTestLanguage(language);
  try {
    return await run();
  } finally {
    await restore();
  }
}

export { i18n };
