import { screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type * as StorageApi from "@/core/storage/api";
import { getNASManifest, startNASService } from "@/core/storage/api";
import { renderWithProviders } from "@/test/harness";
import StoragePage from "./page";

vi.mock("@/core/storage/api", async (importOriginal) => ({
  ...(await importOriginal<typeof StorageApi>()),
  getNASManifest: vi.fn(),
  getNASPolicy: vi.fn().mockResolvedValue({ mode: "privacy" }),
  listNASSources: vi.fn().mockResolvedValue([]),
  listNASDirectory: vi.fn().mockRejectedValue(new Error("HTTP 503")),
  startNASService: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(getNASManifest)
    .mockReset()
    .mockRejectedValue(new Error("HTTP 503"));
  vi.mocked(startNASService).mockReset().mockResolvedValue({
    ok: false,
    status: "not_found",
    base_url: "/api/storage",
    auth_token: null,
  });
});

it("explains a missing storage service without polling an uninstalled process", async () => {
  renderWithProviders(<StoragePage />, {
    locale: "zh-CN",
    initialRoute: "/workspace/storage?library=computer",
  });
  expect(await screen.findByRole("alert")).toHaveTextContent(
    /未找到 octopus-storage/,
  );
  expect(startNASService).toHaveBeenCalledOnce();
  expect(getNASManifest).toHaveBeenCalledOnce();
  expect(
    screen.getByRole("button", { name: "扫描", exact: true }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "效率", exact: true }),
  ).toBeDisabled();
});
