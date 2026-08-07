import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { PageBackButton } from "./PageBackButton";

function CurrentLocation() {
  const location = useLocation();
  return <output>{`${location.pathname}${location.search}`}</output>;
}

function DetailPage() {
  return <PageBackButton fallbackTo="/tasks">返回</PageBackButton>;
}

describe("PageBackButton", () => {
  afterEach(() => {
    window.history.replaceState(null, "");
  });

  it("returns to the previous route and preserves its filters", () => {
    window.history.replaceState({ idx: 1 }, "");
    render(
      <MemoryRouter initialEntries={["/tasks?state=running", "/tasks/task-1"]} initialIndex={1}>
        <Routes>
          <Route path="/tasks" element={<CurrentLocation />} />
          <Route path="/tasks/:taskId" element={<DetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "返回" }));

    expect(screen.getByText("/tasks?state=running")).toBeInTheDocument();
  });

  it("uses the collection route when the detail page was opened directly", () => {
    window.history.replaceState({ idx: 0 }, "");
    render(
      <MemoryRouter initialEntries={["/tasks/task-1"]}>
        <Routes>
          <Route path="/tasks" element={<CurrentLocation />} />
          <Route path="/tasks/:taskId" element={<DetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "返回" }));

    expect(screen.getByText("/tasks")).toBeInTheDocument();
  });
});
