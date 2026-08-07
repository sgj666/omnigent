import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { i18n, registerNativeLanguageSync, setUiLanguagePreference } from "./index";

beforeEach(async () => {
  await setUiLanguagePreference("en");
});

afterEach(async () => {
  registerNativeLanguageSync(undefined);
  await setUiLanguagePreference("system");
});

describe("i18n runtime", () => {
  it("synchronizes language changes with the Electron desktop bridge", async () => {
    const setLanguage = vi.fn();
    (window as unknown as Record<string, unknown>).omnigentDesktop = {
      kind: "electron",
      setLanguage,
    };
    try {
      await setUiLanguagePreference("zh-CN");
      expect(setLanguage).toHaveBeenCalledWith("zh-CN", "zh-CN");
    } finally {
      delete (window as unknown as Record<string, unknown>).omnigentDesktop;
    }
  });

  it("applies a manual language immediately and synchronizes the document", async () => {
    await setUiLanguagePreference("zh-CN");
    expect(i18n.resolvedLanguage).toBe("zh-CN");
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(document.title).toBe("Orvia");
  });

  it("preserves a dynamic title owned by the chat page", async () => {
    document.title = "Active conversation";
    await setUiLanguagePreference("zh-CN");
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(document.title).toBe("Active conversation");
  });

  it("resolves system language changes while system preference is selected", async () => {
    const originalLanguages = navigator.languages;
    const nativeSync = vi.fn();
    registerNativeLanguageSync(nativeSync);
    try {
      Object.defineProperty(navigator, "languages", {
        configurable: true,
        value: ["en-US"],
      });
      await setUiLanguagePreference("system");
      nativeSync.mockClear();
      Object.defineProperty(navigator, "languages", {
        configurable: true,
        value: ["zh-CN"],
      });
      window.dispatchEvent(new Event("languagechange"));
      await new Promise((resolve) => {
        setTimeout(resolve, 0);
      });
      expect(i18n.resolvedLanguage).toBe("zh-CN");
      expect(nativeSync).toHaveBeenCalledWith("system", "zh-CN");
    } finally {
      Object.defineProperty(navigator, "languages", {
        configurable: true,
        value: originalLanguages,
      });
    }
  });

  it("synchronizes the selected preference and effective language with native shells", async () => {
    const nativeSync = vi.fn();
    registerNativeLanguageSync(nativeSync);
    await setUiLanguagePreference("zh-CN");
    expect(nativeSync).toHaveBeenCalledWith("zh-CN", "zh-CN");
  });

  it("immediately synchronizes a native callback registered after initialization", async () => {
    await setUiLanguagePreference("zh-CN");
    const nativeSync = vi.fn();
    registerNativeLanguageSync(nativeSync);
    expect(nativeSync).toHaveBeenCalledWith("zh-CN", "zh-CN");
  });

  it("ignores browser language changes while a manual preference is selected", async () => {
    const originalLanguages = navigator.languages;
    try {
      await setUiLanguagePreference("en");
      Object.defineProperty(navigator, "languages", {
        configurable: true,
        value: ["zh-CN"],
      });
      window.dispatchEvent(new Event("languagechange"));
      await new Promise((resolve) => {
        setTimeout(resolve, 0);
      });
      expect(i18n.resolvedLanguage).toBe("en");
    } finally {
      Object.defineProperty(navigator, "languages", {
        configurable: true,
        value: originalLanguages,
      });
    }
  });
});
