import { describe, expect, it } from "vitest";

import {
  isChatSurfaceRoute,
  isCompanySurfaceActive,
  isNavRouteActive,
  isStorageLibraryRouteActive,
  isStorageRouteActive,
} from "./sidebar-routing";

describe("sidebar routing helpers", () => {
  it("detects chat surface routes", () => {
    expect(isChatSurfaceRoute("/workspace/realtime")).toBe(true);
    expect(isChatSurfaceRoute("/workspace/realtime/new")).toBe(true);
    expect(isChatSurfaceRoute("/workspace/storage")).toBe(false);
  });

  it("detects storage-family routes", () => {
    expect(isStorageRouteActive("/workspace/storage")).toBe(true);
    expect(isStorageRouteActive("/workspace/nas/files")).toBe(true);
    expect(isStorageRouteActive("/workspace/knowledge")).toBe(true);
    expect(isStorageRouteActive("/workspace/agents")).toBe(false);
  });

  it("matches nav routes with prefix semantics", () => {
    expect(isNavRouteActive("/workspace/agents", "/workspace/agents")).toBe(
      true,
    );
    expect(
      isNavRouteActive("/workspace/agents/team", "/workspace/agents"),
    ).toBe(true);
    expect(isNavRouteActive("/workspace/evolution", "/workspace/agents")).toBe(
      false,
    );
  });

  it("activates storage library rows by ?library= param", () => {
    expect(
      isStorageLibraryRouteActive(
        "/workspace/storage?library=files",
        "?library=files",
        "/workspace/storage?library=files",
      ),
    ).toBe(true);
    expect(
      isStorageLibraryRouteActive(
        "/workspace/storage",
        "",
        "/workspace/storage?library=files",
      ),
    ).toBe(false);
  });

  it("defaults company surface unless agent surface is active", () => {
    expect(isCompanySurfaceActive("/workspace/storage")).toBe(true);
    expect(isCompanySurfaceActive("/workspace/agents?surface=chat")).toBe(
      false,
    );
  });
});
