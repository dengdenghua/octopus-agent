import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MacWindowControls } from "./mac-window-controls";

afterEach(() => vi.unstubAllGlobals());

describe("host-owned window controls", () => {
  it.each(["win32", "darwin", "linux", undefined])(
    "does not render duplicate window actions for %s",
    (platform) => {
      vi.stubGlobal(
        "octopus",
        platform ? { isElectron: true, platform } : undefined,
      );
      const { container } = render(<MacWindowControls />);
      expect(container).toBeEmptyDOMElement();
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
    },
  );
});
