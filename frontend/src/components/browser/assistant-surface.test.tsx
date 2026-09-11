import { useEffect, useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import {
  AssistantSurface,
  fitAssistant,
  useAssistantPresentation,
} from "./assistant-surface";

afterEach(() => vi.restoreAllMocks());
it("keeps the whole floating window visible after a viewport shrink", () => {
  const p = fitAssistant(
    { width: 390, height: 500 },
    { width: 700, height: 800, right: 400, bottom: 300 },
  );
  expect(p.width + p.right).toBeLessThanOrEqual(378);
  expect(p.height + p.bottom).toBeLessThanOrEqual(488);
  expect(p.right).toBeGreaterThanOrEqual(12);
  expect(p.bottom).toBeGreaterThanOrEqual(12);
});

it("retains the same conversation and draft across float, minimize, restore and dock", async () => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    width: 1200,
    height: 750,
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    right: 1200,
    bottom: 750,
    toJSON: () => ({}),
  });
  const mount = vi.fn(),
    unmount = vi.fn();
  function Conversation() {
    const presentation = useAssistantPresentation();
    const [draft, setDraft] = useState("");
    useEffect(() => {
      mount();
      return unmount;
    }, []);
    return (
      <div>
        {presentation?.compact && presentation.dragHandle}
        <button
          onClick={() => presentation?.setExpanded(!presentation.expanded)}
          aria-label={presentation?.expanded ? "收起对话记录" : "展开对话记录"}
        >
          最近一条
        </button>
        <input
          aria-label="草稿"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        {presentation?.compact && presentation.controls}
      </div>
    );
  }
  function Harness() {
    const [open, setOpen] = useState(true);
    return (
      <div>
        <AssistantSurface
          open={open}
          onOpenChange={setOpen}
          dockWidth={380}
          onDockWidthChange={() => {}}
        >
          <Conversation />
        </AssistantSurface>
      </div>
    );
  }
  const user = userEvent.setup();
  render(<Harness />);
  const input = screen.getByRole("textbox", { name: "草稿" });
  await user.type(input, "保留当前任务");
  expect(screen.getByRole("complementary")).toHaveStyle({
    height: "78px",
    right: "232px",
    bottom: "16px",
  });
  await user.click(screen.getByRole("button", { name: "展开对话记录" }));
  expect(screen.getByRole("complementary")).toHaveStyle({
    height: "520px",
    bottom: "16px",
  });
  await user.click(screen.getByRole("button", { name: "收起对话记录" }));
  expect(screen.getByRole("textbox", { name: "草稿" })).toBeVisible();
  expect(input).toHaveValue("保留当前任务");
  await user.click(screen.getByRole("button", { name: "展开对话记录" }));
  expect(screen.getByRole("complementary")).toHaveAttribute(
    "data-presentation",
    "floating",
  );
  const handle = screen.getByLabelText("拖动聊天窗口，方向键移动");
  handle.setPointerCapture = vi.fn();
  fireEvent(
    handle,
    new MouseEvent("pointerdown", {
      bubbles: true,
      button: 0,
      clientX: 800,
      clientY: 200,
    }),
  );
  fireEvent(
    handle,
    new MouseEvent("pointermove", {
      bubbles: true,
      clientX: 740,
      clientY: 170,
    }),
  );
  fireEvent(handle, new MouseEvent("pointerup", { bubbles: true }));
  expect(screen.getByRole("complementary")).toHaveStyle({
    right: "292px",
    bottom: "46px",
  });
  const resize = screen.getByRole("button", { name: "调整悬浮聊天大小" });
  resize.focus();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("complementary")).toHaveStyle({ width: "756px" });
  await user.click(screen.getByRole("button", { name: "收起聊天" }));
  expect(input).not.toBeVisible();
  expect(unmount).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "恢复浏览器聊天" }));
  await user.click(screen.getByRole("button", { name: "停靠到右侧" }));
  expect(screen.getByRole("textbox", { name: "草稿" })).toBe(input);
  expect(input).toHaveValue("保留当前任务");
  expect(mount).toHaveBeenCalledOnce();
});

it("keeps the default narrow layout as a compact input bar", () => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    width: 390,
    height: 700,
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    right: 390,
    bottom: 700,
    toJSON: () => ({}),
  });
  render(
    <div>
      <AssistantSurface
        open
        onOpenChange={() => {}}
        dockWidth={380}
        onDockWidthChange={() => {}}
      >
        <input aria-label="草稿" />
      </AssistantSurface>
    </div>,
  );
  expect(screen.getByRole("complementary")).toHaveAttribute(
    "data-presentation",
    "sheet",
  );
  expect(screen.getByRole("complementary")).toHaveStyle({ width: "366px" });
  expect(screen.getByRole("complementary")).toHaveStyle({ height: "78px" });
  expect(
    screen.queryByRole("button", { name: "悬浮聊天" }),
  ).not.toBeInTheDocument();
});
