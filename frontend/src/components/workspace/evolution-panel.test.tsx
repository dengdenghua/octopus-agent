/* Implementation note. */
import { describe, expect, test } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { AllProviders } from "@/test/harness";
import type { EvolutionStatus } from "@/core/observability/api";

import { EvolutionPanel } from "./evolution-panel";

function baseStatus(overrides: Partial<EvolutionStatus> = {}): EvolutionStatus {
  return {
    enabled: true,
    rules_count: 0,
    memories_count: 0,
    rules_lines: [],
    memories_lines: [],
    trajectories: { total: 0, react_loop: 0, react_loop_failures: 0 },
    react_variants: [],
    ...overrides,
  };
}

function renderPanel(status: EvolutionStatus) {
  const trigger = <button type="button">open-evolution</button>;
  const utils = render(
    <AllProviders locale="zh-CN">
      <EvolutionPanel status={status} trigger={trigger} />
    </AllProviders>,
  );
  // Click the trigger to open the dialog
  fireEvent.click(screen.getByText("open-evolution"));
  return utils;
}

function clickStat(dialog: HTMLElement, label: string) {
  const button = within(dialog).getByText(label).closest("button");
  expect(button).not.toBeNull();
  fireEvent.click(button!);
}

describe("EvolutionPanel", () => {
  test("status summary reflects learned lessons and task history", async () => {
    renderPanel(
      baseStatus({
        rules_count: 4,
        memories_count: 9,
        trajectories: { total: 120, react_loop: 80, react_loop_failures: 3 },
      }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain(
      "已从 120 次任务中沉淀 13 条可复用经验",
    );
    expect(dialog.textContent).toContain("建议关注");
    expect(dialog.textContent).toContain("风险经验");
    expect(dialog.textContent).toContain("有效做法");
    expect(dialog.textContent).toContain("复盘样本");
    expect(dialog.textContent).toContain("深度任务");
    expect(dialog.textContent).toContain("4");
    expect(dialog.textContent).toContain("9");
    expect(dialog.textContent).toContain("120");
    expect(dialog.textContent).toContain("80 次");
    expect(dialog.textContent).toContain("3 条需复盘");
  });

  test("rule lines render with their text + remembered count", async () => {
    renderPanel(
      baseStatus({
        rules_count: 2,
        rules_lines: [
          "Avoid calling `rm -rf` without explicit confirmation.",
          "Prefer structured JSON over raw strings in tool output.",
        ],
      }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("rm -rf");
    expect(dialog.textContent).toContain("structured JSON");
    expect(dialog.textContent).toContain("2 条");
    expect(dialog.textContent).toContain("下次遇到相似任务时会自动参考");
  });

  test("empty rules show the localized mitigation hint", async () => {
    renderPanel(baseStatus({ rules_count: 0, rules_lines: [] }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("还没有发现稳定重复的问题");
  });

  test("empty memories show the localized memory hint", async () => {
    renderPanel(baseStatus({ memories_count: 0, memories_lines: [] }));
    const dialog = await screen.findByRole("dialog");
    clickStat(dialog, "有效做法");
    expect(dialog.textContent).toContain("还没有足够稳定的成功经验");
  });

  test("metric cards switch the details pane", async () => {
    renderPanel(
      baseStatus({
        rules_count: 1,
        memories_count: 1,
        rules_lines: ["Keep rule-visible checks in the foreground."],
        memories_lines: ["Reuse memory-visible planning flow."],
        trajectories: { total: 12, react_loop: 7, react_loop_failures: 2 },
      }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("rule-visible");
    expect(dialog.textContent).not.toContain("memory-visible");

    clickStat(dialog, "有效做法");
    expect(dialog.textContent).toContain("memory-visible");
    expect(dialog.textContent).not.toContain("rule-visible");

    clickStat(dialog, "复盘样本");
    expect(dialog.textContent).toContain("样本已进入复盘池");
    expect(dialog.textContent).toContain("经验已沉淀完成");

    clickStat(dialog, "深度任务");
    expect(dialog.textContent).toContain("深度任务已进入评估样本");
    expect(dialog.textContent).toContain("被标记为需复盘");
  });

  test("tool failure lesson lines are localized", async () => {
    renderPanel(
      baseStatus({
        rules_count: 1,
        rules_lines: [
          "[MIDÂ·6x] When calling 'edit_file' with args=['old_string', 'new_string', 'path'], failure signature 'failed:read_before_write_required' seen 6 times â Skill 'edit_file' failed with 'failed:read_before_write_required'; consider alternative skill or validate inputs.",
        ],
      }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain(
      "edit_file 触发「读写顺序不正确」6 次",
    );
    expect(dialog.textContent).not.toContain("When calling");
  });

  test("react_variants are tucked behind advanced details", async () => {
    renderPanel(
      baseStatus({
        react_variants: [
          {
            name: "A-stable",
            max_iterations: 8,
            temperature: 0.2,
            assignments: 10,
            successes: 7,
            failures: 3,
            success_rate: 0.7,
          },
          {
            name: "B-explore",
            max_iterations: 12,
            temperature: 0.9,
            assignments: 0, // zero-assignment case renders "—"
            successes: 0,
            failures: 0,
            success_rate: 0,
          },
        ],
      }),
    );
    const dialog = await screen.findByRole("dialog");
    clickStat(dialog, "复盘样本");
    expect(dialog.textContent).toContain("高级信息");

    fireEvent.click(within(dialog).getByText("高级信息"));

    expect(dialog.textContent).toContain("A-stable");
    expect(dialog.textContent).toContain("B-explore");
    const table = within(dialog).getByRole("table");
    expect(table.textContent).toContain("70%");
    expect(table.textContent).toContain("—");
  });

  test("no variants → no advanced strategy details rendered", async () => {
    renderPanel(baseStatus({ react_variants: [] }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).not.toContain("高级信息");
  });

  test("reflect button is present and labeled 立即复盘", async () => {
    renderPanel(baseStatus());
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("立即复盘");
  });
});
