import { describe, expect, it } from "vitest";
import { screen, fireEvent, cleanup } from "@testing-library/react";
import { renderWithProviders as render } from "@/test/harness";
import { afterEach } from "vitest";
import { EmployeeBlueprints, blueprints, employeeSetupRoute } from "./employee-blueprints";
afterEach(cleanup);
describe("employee subdirectory", () => {
  it("covers each source occupation once and gives each blueprint a distinct identity", () => {
    expect(blueprints).toHaveLength(32);
    expect(new Set(blueprints.map(r => r.id)).size).toBe(32);
    const occupations = blueprints.flatMap(r => r.original_indices);
    expect(occupations).toHaveLength(76);
    expect(new Set(occupations).size).toBe(76);
  });
  it("searches covered occupations and routes to configuration rather than claiming installation", () => {
    render(<EmployeeBlueprints searchQuery="海外仓储账务" />);
    expect(screen.getByText("仓储与库存运营")).toBeTruthy();
    expect(screen.getByText("1 个岗位")).toBeTruthy();
    expect(screen.queryByText("待配置")).toBeNull();
    const role = blueprints.find(r => r.name === "仓储与库存运营")!;
    const params = new URLSearchParams(employeeSetupRoute(role).split("?")[1]);
    expect(params.get("template")).toBe("exec-assistant");
    expect(params.get("role")).toBe(role.name);
    expect(params.get("focus")).toContain("海外仓储账务");
    expect(screen.getByRole("link", { name: "配置仓储与库存运营" }).getAttribute("href")).toBe(`#${employeeSetupRoute(role)}`);
  });
  it("filters categories and opens role details", () => {
    render(<EmployeeBlueprints />);
    fireEvent.click(screen.getByRole("button", { name: "技术支持", exact: true }));
    expect(screen.getByText("2 个岗位")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "产品经理", exact: true })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "安全工程师", exact: true }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText("可复用基础与来源")).toBeTruthy();
  });
  it("ignores a selected category when returning to the full directory", () => {
    const view = render(<EmployeeBlueprints />);
    fireEvent.click(screen.getByRole("button", { name: "技术支持", exact: true }));
    expect(screen.queryByRole("button", { name: "产品经理", exact: true })).toBeNull();
    view.rerender(<EmployeeBlueprints showCategories={false} />);
    expect(screen.queryByLabelText("数字员工分类")).toBeNull();
    expect(screen.getByRole("button", { name: "产品经理", exact: true })).toBeTruthy();
  });
});
