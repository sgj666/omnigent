import { describe, expect, it } from "vitest";
import {
  LANGUAGE_PREFERENCE_KEY,
  readLanguagePreference,
  resolveLanguage,
  resolveSystemLanguage,
  writeLanguagePreference,
  type LanguagePreference,
} from "./languagePreferences";

describe("resolveSystemLanguage", () => {
  it.each(["zh", "zh-CN", "zh-SG", "zh-TW", "ZH-hans"])(
    "resolves %s to Simplified Chinese",
    (locale) => {
      expect(resolveSystemLanguage([locale])).toBe("zh-CN");
    },
  );

  it.each([[[]], [["en-US"]], [["fr-FR"]], [["system"]]])(
    "falls back to English for unsupported locales (%j)",
    (locales) => {
      expect(resolveSystemLanguage(locales)).toBe("en");
    },
  );
});

describe("resolveLanguage", () => {
  it.each(["en", "zh-CN"] as const)("keeps the explicit %s preference", (preference) => {
    expect(resolveLanguage(preference, ["zh-TW"])).toBe(preference);
  });

  it("resolves the system preference from the provided language list", () => {
    expect(resolveLanguage("system", ["fr-FR", "zh-TW"])).toBe("zh-CN");
    expect(resolveLanguage("system", ["fr-FR", "en-US"])).toBe("en");
  });
});

describe("language preference storage", () => {
  it("uses the expected storage key", () => {
    expect(LANGUAGE_PREFERENCE_KEY).toBe("omnigent:language");
  });

  it.each([null, "", "fr", "zh-TW"])("falls back to system for stored value %j", (value) => {
    expect(readLanguagePreference({ getItem: () => value })).toBe("system");
  });

  it("falls back to system when storage throws while reading", () => {
    const storage = {
      getItem(): string | null {
        throw new Error("access denied");
      },
    };

    expect(readLanguagePreference(storage)).toBe("system");
  });

  it.each<LanguagePreference>(["system", "en", "zh-CN"])(
    "persists the %s preference",
    (preference) => {
      let storedKey: string | undefined;
      let storedValue: string | undefined;
      const storage = {
        setItem(key: string, value: string): void {
          storedKey = key;
          storedValue = value;
        },
      };

      writeLanguagePreference(storage, preference);

      expect(storedKey).toBe(LANGUAGE_PREFERENCE_KEY);
      expect(storedValue).toBe(preference);
    },
  );

  it("does not throw when storage throws while writing", () => {
    const storage = {
      setItem(): void {
        throw new Error("quota exceeded");
      },
    };

    expect(() => writeLanguagePreference(storage, "zh-CN")).not.toThrow();
  });
});
