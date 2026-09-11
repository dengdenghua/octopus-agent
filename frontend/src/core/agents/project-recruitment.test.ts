import { beforeEach, expect, test, vi } from "vitest";
import { provisionProjectRoles } from "./project-recruitment";
const mocks = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), install: vi.fn() }));
vi.mock("./api", () => ({ listAgents: mocks.list, createAgent: mocks.create }));
vi.mock("./agent-world-api", () => ({ installCloudExpert: mocks.install }));
beforeEach(() => { vi.clearAllMocks(); mocks.list.mockResolvedValue([]); mocks.create.mockResolvedValue({}); });
test("prepares HUB and new roles through the existing APIs", async () => {
  mocks.install.mockResolvedValue({ agent_id: "loaded_hub" });
  expect(await provisionProjectRoles([
    { source: "hub", key: "hub:wb_test", name: "Test", expert_id: "wb_test" },
    { source: "new", key: "new_role", agent_id: "new_role", name: "Engineer", description: "Test designs", soul: "Reviewed role" },
  ])).toEqual({ "hub:wb_test": "loaded_hub", new_role: "new_role" });
  expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ name: "new_role", display_name: "Engineer", soul: "Reviewed role" }));
});
test("failure does not report roles as prepared", async () => {
  mocks.install.mockRejectedValue(new Error("Permission denied"));
  await expect(provisionProjectRoles([{ source: "hub", key: "hub:x", name: "X", expert_id: "x" }])).rejects.toThrow("Permission denied");
  expect(mocks.create).not.toHaveBeenCalled();
});

test("expiry during preparation stops remaining roles and never returns an approval payload", async () => {
  let active = true;
  mocks.install.mockImplementationOnce(async () => {
    active = false;
    return { agent_id: "already_loaded" };
  });
  await expect(provisionProjectRoles([
    { source: "hub", key: "hub:a", name: "A", expert_id: "a" },
    { source: "hub", key: "hub:b", name: "B", expert_id: "b" },
  ], () => active)).rejects.toThrow("Approval expired");
  expect(mocks.install).toHaveBeenCalledTimes(1);
  expect(mocks.install).toHaveBeenCalledWith("a");
});

test("an already expired request performs no role mutations", async () => {
  await expect(provisionProjectRoles([
    { source: "hub", key: "hub:a", name: "A", expert_id: "a" },
  ], () => false)).rejects.toThrow("Approval expired");
  expect(mocks.install).not.toHaveBeenCalled();
  expect(mocks.create).not.toHaveBeenCalled();
});
test("retries reuse matching roles and reject conflicting role definitions", async () => {
  const role = { source: "new" as const, key: "r", agent_id: "r", name: "Role", description: "Scope", soul: "Rules" };
  mocks.list.mockResolvedValue([{ name: "r", description: "Scope" }]);
  await expect(provisionProjectRoles([role])).resolves.toEqual({ r: "r" });
  expect(mocks.create).not.toHaveBeenCalled();
  mocks.list.mockResolvedValue([{ name: "r", description: "Changed" }]);
  await expect(provisionProjectRoles([role])).rejects.toThrow("configuration changed");
});
