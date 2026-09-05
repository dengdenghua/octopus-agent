import { useEffect } from "react";
import { useLocation } from "react-router-dom";

import { useI18n } from "@/core/i18n/hooks";
import { WORKBENCH_BUILTIN_APPS } from "@/core/workbench/apps";

/** Conversation and public share views own their dynamic titles. */
export function RouteTitle() {
  const { pathname, search } = useLocation();
  const { t } = useI18n();
  useEffect(() => {
    if (
      pathname.startsWith("/workspace/realtime/") ||
      pathname.startsWith("/share/")
    )
      return;
    const workbench = WORKBENCH_BUILTIN_APPS.find((app) => {
      const route = app.workspaceRoute.split("?")[0]!;
      return pathname === route || pathname.startsWith(`${route}/`);
    });
    const title =
      workbench?.name ??
      (pathname.startsWith("/workspace/agents") ? "HUB" : undefined) ??
      (pathname === "/workspace/web-app"
        ? new URLSearchParams(search).get("title")
        : undefined);
    document.title = title ? `${title} - ${t.pages.appName}` : t.pages.appName;
  }, [pathname, search, t.pages.appName]);
  return null;
}
