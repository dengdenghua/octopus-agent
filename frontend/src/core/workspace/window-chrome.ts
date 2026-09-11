export const DESKTOP_TITLE_BAR_HEIGHT = 36;

export function resolveWindowChrome(
  platform: string | undefined,
  desktop: boolean,
  fullScreen = false,
  windowControlsOverlay = true,
) {
  const overlay =
    desktop &&
    windowControlsOverlay &&
    (platform === "win32" || platform === "darwin");
  const titleBarHeight = overlay && !fullScreen ? DESKTOP_TITLE_BAR_HEIGHT : 0;
  const contentTopInset =
    titleBarHeight && platform === "darwin" ? `${titleBarHeight}px` : "0px";
  return {
    fullScreen,
    titleBarHeight,
    titleBarInset:
      titleBarHeight && platform === "win32"
        ? `env(titlebar-area-height, ${titleBarHeight}px)`
        : `${titleBarHeight}px`,
    // Windows' overlay controls can share the app header. macOS traffic
    // lights still need their own inset so they never cover sidebar content.
    contentTopInset,
    controlsSafeInset: titleBarHeight && platform === "win32" ? "138px" : "0px",
    controlsSide: !desktop
      ? "none"
      : platform === "darwin"
        ? "left"
        : platform === "win32"
          ? "right"
          : "system",
    macTrafficLightsWidth:
      overlay && platform === "darwin" && !fullScreen ? 80 : 0,
  } as const;
}

export function desktopWindowChrome(fullScreen = false) {
  const shell = typeof window === "undefined" ? undefined : window.octopus;
  return resolveWindowChrome(
    shell?.platform,
    shell?.isElectron === true,
    fullScreen,
    shell?.windowControlsOverlay,
  );
}
