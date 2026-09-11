import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  ElectronTitleBar,
  ElectronTitleBarProvider,
  isMac,
  isWindows,
  useElectronTitleBar,
} from "./electron-title-bar";
import { WorkspaceNavigationControls } from "./workspace/mac-window-controls";

afterEach(() => vi.unstubAllGlobals());

function LayoutProbe() {
  const { titleBarInset } = useElectronTitleBar();
  return <output data-testid="inset">{titleBarInset}</output>;
}

it("uses the desktop bridge instead of browser platform sniffing", () => {
  vi.stubGlobal("octopus", { isElectron: true, platform: "darwin" });
  expect(isMac()).toBe(true);
  expect(isWindows()).toBe(false);
  render(<WorkspaceNavigationControls />);
  expect(screen.queryByRole("button")).toBeNull();
});

it("removes and restores the reserved row on native fullscreen events", async () => {
  let onFullscreen: ((payload: { fullScreen: boolean }) => void) | undefined;
  const unsubscribe = vi.fn();
  vi.stubGlobal("octopus", {
    isElectron: true,
    platform: "darwin",
    window: {
      isFullScreen: vi.fn().mockResolvedValue({ ok: true, fullScreen: false }),
    },
    on: vi.fn((_event, listener) => {
      onFullscreen = listener;
      return unsubscribe;
    }),
  });
  const { unmount, container } = render(
    <ElectronTitleBarProvider>
      <ElectronTitleBar />
      <LayoutProbe />
    </ElectronTitleBarProvider>,
  );
  await waitFor(() => expect(onFullscreen).toBeDefined());
  expect(screen.getByTestId("inset")).toHaveTextContent("36px");
  expect(
    container.querySelector('[data-window-titlebar="left"]'),
  ).toBeInTheDocument();
  act(() => onFullscreen!({ fullScreen: true }));
  expect(screen.getByTestId("inset")).toHaveTextContent("0px");
  expect(container.querySelector("[data-window-titlebar]")).toBeNull();
  act(() => onFullscreen!({ fullScreen: false }));
  expect(screen.getByTestId("inset")).toHaveTextContent("36px");
  unmount();
  expect(unsubscribe).toHaveBeenCalledOnce();
});

it("does not add a fake title bar to Linux or ordinary web pages", () => {
  vi.stubGlobal("octopus", { isElectron: true, platform: "linux" });
  const { container, rerender } = render(<ElectronTitleBar />);
  expect(container).toBeEmptyDOMElement();
  vi.stubGlobal("octopus", undefined);
  rerender(<ElectronTitleBar />);
  expect(container).toBeEmptyDOMElement();
});

it("honors a desktop window that already has a native system frame", () => {
  vi.stubGlobal("octopus", {
    isElectron: true,
    platform: "win32",
    windowControlsOverlay: false,
  });
  const { container } = render(<ElectronTitleBar />);
  expect(container).toBeEmptyDOMElement();
});
