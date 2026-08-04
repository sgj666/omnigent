import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRef } from "react";
import { setTestLanguage } from "@/i18n/testHelpers";
import { SelectionPopup } from "./ChatPage";

beforeEach(() => {
  Range.prototype.getBoundingClientRect = vi.fn(
    () => ({ top: 20, left: 10, width: 40, height: 16 }) as DOMRect,
  );
});

afterEach(() => {
  cleanup();
  window.getSelection()?.removeAllRanges();
  vi.restoreAllMocks();
});

describe("SelectionPopup", () => {
  it("uses the professional Chinese reply label and keeps the Enter glyph", async () => {
    const restore = await setTestLanguage("zh-CN");
    try {
      const containerRef = createRef<HTMLDivElement>();
      render(
        <div ref={containerRef}>
          <p>Selected response text</p>
          <SelectionPopup containerRef={containerRef} onReply={vi.fn()} />
        </div>,
      );

      const selection = window.getSelection();
      const text = screen.getByText("Selected response text");
      const range = document.createRange();
      range.selectNodeContents(text);
      selection?.removeAllRanges();
      selection?.addRange(range);

      await act(async () => {
        document.dispatchEvent(new Event("selectionchange"));
      });

      expect(screen.getByRole("button", { name: "回复 ↵" })).toBeInTheDocument();
    } finally {
      await restore();
    }
  });
});
