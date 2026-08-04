import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setTestLanguage } from "@/i18n/testHelpers";
import { CommandGoalDialog } from "./CommandGoalDialog";

afterEach(cleanup);

describe("CommandGoalDialog", () => {
  it("submits a trimmed completion condition", () => {
    const onStartGoal = vi.fn();
    const onOpenChange = vi.fn();
    render(
      <CommandGoalDialog
        open
        onOpenChange={onOpenChange}
        readOnly={false}
        onStartGoal={onStartGoal}
      />,
    );

    fireEvent.change(screen.getByTestId("goal-condition"), {
      target: { value: "  All tests pass  " },
    });
    fireEvent.click(screen.getByTestId("goal-start"));

    expect(onStartGoal).toHaveBeenCalledWith("All tests pass");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("describes the selected goal backend", () => {
    render(
      <CommandGoalDialog
        open
        onOpenChange={vi.fn()}
        readOnly={false}
        onStartGoal={vi.fn()}
        backendLabel="Codex"
      />,
    );

    expect(screen.getByText(/Codex keeps working until this condition is met/)).toBeInTheDocument();
  });

  it("rejects an empty condition", () => {
    const onStartGoal = vi.fn();
    render(
      <CommandGoalDialog open onOpenChange={vi.fn()} readOnly={false} onStartGoal={onStartGoal} />,
    );

    fireEvent.click(screen.getByTestId("goal-start"));

    expect(screen.getByText("Goal condition cannot be empty.")).toBeInTheDocument();
    expect(onStartGoal).not.toHaveBeenCalled();
  });

  it("disables editing in read-only sessions", () => {
    render(<CommandGoalDialog open onOpenChange={vi.fn()} readOnly onStartGoal={vi.fn()} />);

    expect(screen.getByTestId("goal-condition")).toBeDisabled();
    expect(screen.getByTestId("goal-start")).toBeDisabled();
  });

  it("localizes goal controls and validation in Chinese", async () => {
    const restore = await setTestLanguage("zh-CN");
    try {
      render(
        <CommandGoalDialog
          open
          onOpenChange={vi.fn()}
          readOnly={false}
          onStartGoal={vi.fn()}
          backendLabel="Codex"
        />,
      );

      expect(screen.getByText("目标")).toBeInTheDocument();
      expect(
        screen.getByText("Codex 将持续工作，直到满足此条件。进度和完成状态会显示在会话中。"),
      ).toBeInTheDocument();
      expect(screen.getByTestId("goal-condition")).toHaveAttribute(
        "placeholder",
        "所有测试通过且实现已完成",
      );
      fireEvent.click(screen.getByTestId("goal-start"));
      expect(screen.getByText("目标完成条件不能为空。")).toBeInTheDocument();
    } finally {
      await restore();
    }
  });
});
