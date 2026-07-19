import { expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";

import { renderWithProviders } from "@/test/harness";

import { ProtectedRoute } from "./protected-route";

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({
    isLoading: true,
    authStatus: null,
    isAuthenticated: false,
  }),
}));

it("shows a localized workspace loading state", () => {
  renderWithProviders(
    <Routes>
      <Route element={<ProtectedRoute />}>
        <Route path="/" element={<div>工作区</div>} />
      </Route>
    </Routes>,
    { locale: "zh-CN" },
  );

  expect(screen.getByText("正在加载工作区...")).toBeInTheDocument();
  expect(screen.queryByText("Loading workspace")).not.toBeInTheDocument();
});
