import { describe, expect, it } from "vitest";

import type { SubtaskStatus } from "@/core/tasks/types";

import { subtaskProgress, subtaskRunState } from "./subtask-status-ui";

describe("subtask status UI mapping", () => {
  it.each<SubtaskStatus>(["failed", "cancelled", "timed_out"])(
    "maps terminal non-success status %s to error instead of waiting",
    (status) => {
      expect(subtaskRunState(status)).toBe("error");
      expect(subtaskProgress({ status, progress: 0.2 })).toBe(1);
    },
  );

  it("keeps pending and active statuses visually distinct", () => {
    expect(subtaskRunState("pending")).toBe("waiting");
    expect(subtaskProgress({ status: "pending", progress: 0 })).toBe(0.08);

    expect(subtaskRunState("in_progress")).toBe("running");
    expect(subtaskProgress({ status: "in_progress", progress: 0.5 })).toBe(0.5);
  });
});
