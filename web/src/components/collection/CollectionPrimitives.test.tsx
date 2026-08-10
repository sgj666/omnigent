import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CollectionPageHeader,
  CollectionState,
  CollectionToolbar,
  EntityTable,
  SegmentedFilter,
  StatusBadge,
} from "./CollectionPrimitives";

afterEach(() => cleanup());

describe("collection primitives", () => {
  it("renders a semantic page header and toolbar", () => {
    render(
      <>
        <CollectionPageHeader
          title="Projects"
          description="Organize related work"
          actions={<button type="button">New project</button>}
        />
        <CollectionToolbar label="Project controls">
          <input aria-label="Search projects" />
        </CollectionToolbar>
      </>,
    );

    expect(screen.getByRole("heading", { level: 1, name: "Projects" })).toBeInTheDocument();
    expect(screen.getByRole("toolbar", { name: "Project controls" })).toContainElement(
      screen.getByRole("textbox", { name: "Search projects" }),
    );
  });

  it("exposes selected segmented filter state and changes it on click", () => {
    const onValueChange = vi.fn();
    render(
      <SegmentedFilter
        label="Project status"
        value="active"
        options={[
          { value: "all", label: "All", count: 3 },
          { value: "active", label: "Active", count: 2 },
        ]}
        onValueChange={onValueChange}
      />,
    );

    expect(screen.getByRole("button", { name: "Active, 2" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "All, 3" }));
    expect(onValueChange).toHaveBeenCalledWith("all");
  });

  it("renders accessible table headers and status badges", () => {
    render(
      <EntityTable
        caption="Projects"
        columns={[
          { key: "name", label: "Name" },
          { key: "status", label: "Status" },
        ]}
      >
        <tr>
          <td>Launch</td>
          <td>
            <StatusBadge tone="success">Active</StatusBadge>
          </td>
        </tr>
      </EntityTable>,
    );

    const table = screen.getByRole("table", { name: "Projects" });
    expect(within(table).getByRole("columnheader", { name: "Name" })).toBeInTheDocument();
    expect(within(table).getByText("Active")).toHaveAttribute("data-tone", "success");
  });

  it("distinguishes non-blocking states from errors", () => {
    const { rerender } = render(<CollectionState state="empty" title="No projects" />);
    expect(screen.getByRole("status")).toHaveTextContent("No projects");

    rerender(<CollectionState state="error" title="Projects could not be loaded" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Projects could not be loaded");
  });
});
