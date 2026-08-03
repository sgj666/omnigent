const { describe, it } = require("node:test");
const assert = require("node:assert/strict");

const {
  normalizeDesktopLocale,
  resolveDesktopLocale,
  isLanguagePreference,
  isSupportedLanguage,
} = require("../src/desktop_locale");

describe("desktop locale normalization", () => {
  it("normalizes persisted preferences and resolves system locales", () => {
    assert.deepEqual(normalizeDesktopLocale({}, "en-US"), {
      preference: "system",
      effectiveLanguage: "en",
    });
    assert.deepEqual(normalizeDesktopLocale({ ui_language: "zh-CN" }, "en-US"), {
      preference: "zh-CN",
      effectiveLanguage: "zh-CN",
    });
    assert.deepEqual(normalizeDesktopLocale({ ui_language: "system" }, "zh-TW"), {
      preference: "system",
      effectiveLanguage: "zh-CN",
    });
  });

  it("falls back safely for invalid persisted and OS values", () => {
    assert.deepEqual(normalizeDesktopLocale({ ui_language: "fr" }, "fr-FR"), {
      preference: "system",
      effectiveLanguage: "en",
    });
    assert.deepEqual(normalizeDesktopLocale({ ui_language: null }, null), {
      preference: "system",
      effectiveLanguage: "en",
    });
    assert.equal(resolveDesktopLocale("bogus", "fr-FR").effectiveLanguage, "en");
    assert.equal(isLanguagePreference("system"), true);
    assert.equal(isLanguagePreference("bogus"), false);
    assert.equal(isSupportedLanguage("zh-CN"), true);
    assert.equal(isSupportedLanguage("zh"), false);
  });
});
