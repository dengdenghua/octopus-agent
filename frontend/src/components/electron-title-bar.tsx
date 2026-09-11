import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  desktopWindowChrome,
  DESKTOP_TITLE_BAR_HEIGHT,
} from "@/core/workspace/window-chrome";

const ELECTRON_TITLE_BAR_HEIGHT = DESKTOP_TITLE_BAR_HEIGHT;
// Native macOS controls occupy the left side of the separate title-bar row.
const MAC_TRAFFIC_LIGHTS_WIDTH_WINDOWED = 80;

const inElectron = (): boolean =>
  typeof window !== "undefined" && !!window.octopus?.isElectron;

const isMac = (): boolean =>
  inElectron()
    ? window.octopus?.platform === "darwin"
    : typeof navigator !== "undefined" &&
      /Mac/.test(navigator.platform) &&
      navigator.maxTouchPoints < 2;

const isWindows = (): boolean =>
  inElectron()
    ? window.octopus?.platform === "win32"
    : typeof navigator !== "undefined" &&
      navigator.userAgent.includes("Windows");

function useTitleBarThemeSync() {
  useEffect(() => {
    if (
      !isWindows() ||
      !window.octopus ||
      window.octopus.windowControlsOverlay === false
    ) {
      return;
    }
    const apply = () => {
      const root = document.documentElement;
      const cs = getComputedStyle(root);
      const bg = cs.getPropertyValue("--background").trim();
      const fg = cs.getPropertyValue("--foreground").trim();
      const wrap = (v: string, fb: string) => {
        if (!v) return fb;
        if (v.startsWith("#") || v.startsWith("rgb") || v.startsWith("oklch"))
          return v;
        return `hsl(${v})`;
      };
      void window
        .octopus!.window.setTitleBarOverlay({
          color: wrap(bg, "#fcfcfd"),
          symbolColor: wrap(fg, "#525252"),
        })
        .catch(() => {});
    };
    apply();
    const obs = new MutationObserver(apply);
    obs.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "class"],
    });
    return () => obs.disconnect();
  }, []);
}

interface ElectronTitleBarContextValue {
  fullScreen: boolean;
  macTrafficLightsWidth: number;
  titleBarHeight: number;
  titleBarInset: string;
  contentTopInset: string;
  controlsSafeInset: string;
  controlsSide: "none" | "left" | "right" | "system";
}

const ElectronTitleBarContext =
  createContext<ElectronTitleBarContextValue | null>(null);

export function ElectronTitleBarProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [fullScreen, setFullScreen] = useState(false);

  useEffect(() => {
    if (!inElectron() || !window.octopus) return;

    // Initial state
    window.octopus.window
      .isFullScreen()
      .then((res: { ok: boolean; fullScreen?: boolean }) => {
        if (res.ok) setFullScreen(!!res.fullScreen);
      })
      .catch(() => {});

    // Listen for changes
    const off = window.octopus.on(
      "window:fullscreen-changed",
      (...args: unknown[]) => {
        const payload = args[0] as { fullScreen?: boolean } | undefined;
        setFullScreen(!!payload?.fullScreen);
      },
    );
    return off;
  }, []);

  return (
    <ElectronTitleBarContext.Provider value={desktopWindowChrome(fullScreen)}>
      {children}
    </ElectronTitleBarContext.Provider>
  );
}

export function useElectronTitleBar() {
  return useContext(ElectronTitleBarContext) ?? desktopWindowChrome();
}

export function ElectronTitleBar() {
  const { titleBarHeight, titleBarInset, controlsSide } = useElectronTitleBar();
  useTitleBarThemeSync();

  if (!titleBarHeight) return null;

  return (
    <>
      {/* Native controls remain owned by the OS. Reserve one separate row so
          collapsing a sidebar or opening a dialog cannot overlap them. */}
      <div
        aria-hidden
        data-window-titlebar={controlsSide}
        className={
          controlsSide === "right"
            ? "pointer-events-none fixed inset-x-0 top-0 z-[60] bg-transparent"
            : "pointer-events-none fixed inset-x-0 top-0 z-[60] border-b border-border bg-background"
        }
        style={
          {
            height: titleBarInset,
            WebkitAppRegion: "drag",
          } as React.CSSProperties
        }
      />
    </>
  );
}

export {
  inElectron,
  isMac,
  isWindows,
  ELECTRON_TITLE_BAR_HEIGHT,
  MAC_TRAFFIC_LIGHTS_WIDTH_WINDOWED,
};
