export const LANGUAGE_PREFERENCE_KEY = "omnigent:language";

export type LanguagePreference = "system" | "en" | "zh-CN";
export type SupportedLanguage = "en" | "zh-CN";

export function resolveSystemLanguage(languages: readonly string[]): SupportedLanguage {
  for (const locale of languages) {
    const normalized = locale.toLowerCase();
    if (normalized.startsWith("zh")) return "zh-CN";
    if (normalized.startsWith("en")) return "en";
  }
  return "en";
}

export function resolveLanguage(
  preference: LanguagePreference,
  languages: readonly string[],
): SupportedLanguage {
  return preference === "system" ? resolveSystemLanguage(languages) : preference;
}

export function readLanguagePreference(storage: Pick<Storage, "getItem">): LanguagePreference {
  try {
    const value = storage.getItem(LANGUAGE_PREFERENCE_KEY);
    return value === "system" || value === "en" || value === "zh-CN" ? value : "system";
  } catch {
    return "system";
  }
}

export function writeLanguagePreference(
  storage: Pick<Storage, "setItem">,
  preference: LanguagePreference,
): void {
  try {
    storage.setItem(LANGUAGE_PREFERENCE_KEY, preference);
  } catch {
    // Storage access and quota errors are non-fatal for preferences.
  }
}
