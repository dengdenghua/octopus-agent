import { createRef, useState } from "react";
import { Globe } from "lucide-react";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/harness";
import { BrowserStartPage } from "./browser-start-page";

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({ isAuthenticated: true, user: { username: "local" } }),
}));
const onOpen = vi.fn();
const onSearch = vi.fn();
const onManageDesktop = vi.fn();
function Home() {
  const [query, setQuery] = useState("");
  const [engine, setEngine] = useState(0);
  return (
    <BrowserStartPage
      active
      query={query}
      onQueryChange={setQuery}
      onSearch={() => onSearch(query)}
      searchInputRef={createRef<HTMLInputElement>()}
      engines={[{ name: "百度" }, { name: "Bing" }]}
      selectedEngine={engine}
      onEngineChange={setEngine}
      onOpen={onOpen}
      onManageDesktop={onManageDesktop}
      apps={[
        {
          name: "项目管理",
          description: "项目协作",
          category: "work",
          url: "octopus://workspace/projects",
          icon: Globe,
        },
        {
          name: "GitHub",
          description: "代码",
          category: "work",
          url: "https://github.com",
          icon: Globe,
        },
      ]}
    />
  );
}
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});

it("submits the typed query by Enter and the search button", async () => {
  const user = userEvent.setup();
  renderWithProviders(<Home />, { locale: "zh-CN" });
  await user.type(
    screen.getByRole("textbox", { name: "搜索网页" }),
    "星空{Enter}",
  );
  expect(onSearch).toHaveBeenLastCalledWith("星空");
  await user.click(screen.getByRole("button", { name: "搜索", exact: true }));
  expect(onSearch).toHaveBeenCalledTimes(2);
});

it("filters and opens an existing app, and retains the desktop manager entry", async () => {
  const user = userEvent.setup();
  renderWithProviders(<Home />, { locale: "zh-CN" });
  await user.click(screen.getByRole("button", { name: "应用", exact: true }));
  await user.type(screen.getByRole("textbox", { name: "搜索应用" }), "项目");
  expect(
    screen.queryByRole("button", { name: "GitHub" }),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "项目管理" }));
  expect(onOpen).toHaveBeenCalledWith("octopus://workspace/projects");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "应用", exact: true }));
  await user.click(screen.getByRole("button", { name: "管理应用与小组件" }));
  expect(onManageDesktop).toHaveBeenCalledOnce();
});

it("persists wallpaper and applies the selected search engine", async () => {
  const user = userEvent.setup();
  renderWithProviders(<Home />, { locale: "zh-CN" });
  await user.click(screen.getByRole("button", { name: "主页设置" }));
  await user.click(screen.getByRole("button", { name: "森林" }));
  expect(localStorage.getItem("echo.browser.start.wallpaper.v1")).toBe(
    "forest",
  );
  expect(screen.getByRole("button", { name: "森林" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await user.selectOptions(
    screen.getByRole("combobox", { name: "搜索引擎" }),
    "1",
  );
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "搜索", exact: true }),
  ).toHaveAttribute("title", "使用 Bing 搜索");
});
