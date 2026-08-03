import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { withTestLanguage } from "@/i18n/testHelpers";
import { NotFoundPage } from "./NotFoundPage";

afterEach(cleanup);

describe("NotFoundPage", () => {
  it("localizes the unmatched-route message", async () => {
    await withTestLanguage("zh-CN", () => {
      render(
        <MemoryRouter>
          <NotFoundPage />
        </MemoryRouter>,
      );

      expect(screen.getByRole("heading", { name: "页面未找到" })).toBeInTheDocument();
      expect(screen.getByText("你访问的网址与应用中的任何路由都不匹配。")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "返回主页" })).toHaveAttribute("href", "/");
    });
  });
});
