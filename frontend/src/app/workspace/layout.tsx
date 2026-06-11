import { Fragment, lazy, Suspense, useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import { Toaster } from "sonner";

import { MoliliLoginDialog } from "@/components/auth/molili-login-dialog";
import { Banner } from "@/components/ui/banner";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { WorkspaceSidebar } from "@/components/workspace/workspace-sidebar";
import {
  STUB_RESPONSE_EVENT,
  type StubResponseDetail,
} from "@/core/api/client";
import { swallow } from "@/core/utils/log";
import { useWorkspaceShortcuts } from "@/core/shortcuts/use-global-shortcuts";
import { useI18n } from "@/core/i18n/hooks";

const CommandPalette = lazy(() =>
  import("@/components/workspace/command-palette").then((m) => ({
    default: m.CommandPalette,
  })),
);

/* Implementation note. */
const ELECTRON_TITLE_BAR_HEIGHT = 36;
const inElectron = (): boolean =>
  typeof window !== "undefined" && !!window.octopus?.isElectron;

/* Implementation note. */
function useTitleBarThemeSync() {
  useEffect(() => {
    if (
      typeof navigator === "undefined" ||
      !navigator.userAgent.includes("Windows") ||
      !window.octopus
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
      void window.octopus!.window
        .setTitleBarOverlay({
          color: wrap(bg, "#fcfcfd"),
          symbolColor: wrap(fg, "#525252"),
        })
        .catch((e) => { swallow(e); });
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

function showStubResponseBanner(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return (
      window.localStorage?.getItem?.("octopus.debug.showStubResponses") ===
      "true"
    );
  } catch (e) {
    swallow(e);
    return false;
  }
}

function StubResponseBannerHost() {
  const { t } = useI18n();
  const [latest, setLatest] = useState<StubResponseDetail | null>(null);
  const showStubBanner = showStubResponseBanner();

  useEffect(() => {
    if (!showStubBanner) return;
    const handler = (event: Event) => {
      const detail = (event as CustomEvent<StubResponseDetail>).detail;
      if (!detail?.method || !detail.path) return;
      setLatest(detail);
    };
    window.addEventListener(STUB_RESPONSE_EVENT, handler);
    return () => window.removeEventListener(STUB_RESPONSE_EVENT, handler);
  }, [showStubBanner]);

  if (!showStubBanner || !latest) return null;

  return (
    <div className="border-b bg-background/95 px-3 py-2 backdrop-blur">
      <Banner
        tone="warning"
        title={t.common.stubResponseTitle}
        onDismiss={() => setLatest(null)}
        className="rounded-lg"
      >
        {t.common.stubResponseDescription(latest.method, latest.path)}
      </Banner>
    </div>
  );
}

export default function WorkspaceLayout() {
  const electron = inElectron();
  useTitleBarThemeSync();
  useWorkspaceShortcuts();
  return (
    <Fragment>
      {/* Implementation note. */}
      {/* Implementation note. */}
      {/* Implementation note. */}
      <SidebarProvider
        className="workspace-shell h-screen"
        defaultOpen
        style={
          electron
            ? ({ paddingTop: ELECTRON_TITLE_BAR_HEIGHT } as React.CSSProperties)
            : undefined
        }
      >
        <WorkspaceSidebar />
        <SidebarInset className="flex min-w-0 flex-col overflow-hidden">
          <StubResponseBannerHost />
          <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden">
            <Outlet />
          </div>
        </SidebarInset>
      </SidebarProvider>
      <MoliliLoginDialog />
      <Suspense fallback={null}>
        <CommandPalette />
      </Suspense>
      <Toaster position="top-center" />
    </Fragment>
  );
}
