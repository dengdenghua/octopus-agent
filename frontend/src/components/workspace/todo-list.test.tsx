import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { TodoList } from "./todo-list";

const todos = [
  { content: "Task A", status: "pending" },
  { content: "Task B", status: "in_progress" },
  { content: "Task C", status: "completed" },
];

describe("TodoList", () => {
  it("renders todo title and items", () => {
    renderWithProviders(<TodoList todos={todos} collapsed={false} />);
    expect(screen.getByText("To-dos")).toBeInTheDocument();
    expect(screen.getByText("Task A")).toBeInTheDocument();
    expect(screen.getByText("Task B")).toBeInTheDocument();
    expect(screen.getByText("Task C")).toBeInTheDocument();
  });

  it("calls onToggle in controlled mode", () => {
    const onToggle = vi.fn();
    renderWithProviders(
      <TodoList todos={todos} collapsed={true} onToggle={onToggle} />,
    );
    fireEvent.click(screen.getByText("To-dos"));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("toggles internal state in uncontrolled mode", () => {
    const { container } = renderWithProviders(<TodoList todos={todos} />);
    const main = container.querySelector("main")!;
    expect(main.className).toContain("h-0");
    const header = container.querySelector("header")!;
    fireEvent.click(header);
    expect(main.className).toContain("h-28");
  });

  it("applies hidden styles when hidden is true", () => {
    const { container } = renderWithProviders(
      <TodoList todos={todos} hidden />,
    );
    const root = container.firstElementChild as HTMLElement;
    expect(root.className).toContain("pointer-events-none");
    expect(root.className).toContain("opacity-0");
  });

  it("shows expanded state when collapsed is false", () => {
    const { container } = renderWithProviders(
      <TodoList todos={todos} collapsed={false} />,
    );
    const main = container.querySelector("main");
    expect(main?.className).toContain("h-28");
  });
});
