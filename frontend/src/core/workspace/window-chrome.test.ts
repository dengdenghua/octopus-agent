import { describe, expect, it } from "vitest";
import { resolveWindowChrome } from "./window-chrome";

describe("native window chrome policy", () => {
  it("shares the app header with the native Windows overlay", () => {
    expect(resolveWindowChrome("win32", true)).toMatchObject({
      controlsSide: "right",
      titleBarHeight: 36,
      titleBarInset: "env(titlebar-area-height, 36px)",
      contentTopInset: "0px",
      controlsSafeInset: "138px",
      macTrafficLightsWidth: 0,
    });
  });
  it("retains native macOS traffic lights on the left", () => {
    expect(resolveWindowChrome("darwin", true)).toMatchObject({
      controlsSide: "left",
      titleBarHeight: 36,
      titleBarInset: "36px",
      contentTopInset: "36px",
      controlsSafeInset: "0px",
      macTrafficLightsWidth: 80,
    });
  });
  it("lets Linux use its system frame without a second reserved row", () => {
    expect(resolveWindowChrome("linux", true)).toMatchObject({
      controlsSide: "system",
      titleBarHeight: 0,
      titleBarInset: "0px",
    });
  });
  it.each(["darwin", "win32", "linux"])(
    "does not emulate OS buttons in a %s web browser",
    (platform) => {
      expect(resolveWindowChrome(platform, false)).toMatchObject({
        controlsSide: "none",
        titleBarHeight: 0,
      });
    },
  );
  it.each(["darwin", "win32"])(
    "does not duplicate the system title bar in a %s auxiliary window",
    (platform) => {
      expect(resolveWindowChrome(platform, true, false, false)).toMatchObject({
        titleBarHeight: 0,
        titleBarInset: "0px",
        macTrafficLightsWidth: 0,
      });
    },
  );
  it.each(["darwin", "win32"])(
    "reclaims the reserved title area in %s fullscreen",
    (platform) => {
      expect(resolveWindowChrome(platform, true, true)).toMatchObject({
        titleBarHeight: 0,
        titleBarInset: "0px",
        macTrafficLightsWidth: 0,
      });
    },
  );
});
