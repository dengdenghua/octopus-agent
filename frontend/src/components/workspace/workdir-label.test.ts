import { describe, expect, it } from "vitest";
import { managedWorkdirThreadId, workdirDisplayName } from "./workdir-label";

const path = "D:\\echo agent\\data\\workspaces\\d175776d9821d0a86f1bb2b0\\838947010f5a20b3ae6ef14e\\87ef910243bf4c4d8fb0a66ca22475e0";
describe("workdir labels", () => {
  it("resolves canonical and member project threads without displaying internal IDs", () => {
    const id = managedWorkdirThreadId(path)!;
    expect(workdirDisplayName(path, [{ id: "p", name: "规格书", execution_thread_id: id }], "任务工作区")).toBe("规格书");
    expect(workdirDisplayName(path.replaceAll("\\", "/") + "/", [{ id: "p", name: "投资", thread_ids: [id] }], "任务工作区")).toBe("投资");
    expect(workdirDisplayName(path, [], "任务工作区")).toBe("任务工作区");
  });
  it("preserves ordinary directory names including hex names outside managed storage", () => {
    expect(workdirDisplayName("D:/echo agent", [], "任务工作区")).toBe("echo agent");
    expect(workdirDisplayName("D:/repos/87ef910243bf4c4d8fb0a66ca22475e0", [], "任务工作区")).toBe("87ef910243bf4c4d8fb0a66ca22475e0");
  });
});
