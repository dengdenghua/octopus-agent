/**
 * Redirect away from routes whose module the user has hidden.
 *
 * Hiding a sidebar entry is not enough on its own — bookmarks, history, and
 * deep links would still reach a removed module. One guard on the workspace
 * layout covers every catalog route.
 */
import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { useEnabledModuleIds } from "./enabled-modules";
import { isLocationBlocked } from "./module-routing";

export function useModuleRouteGuard(fallbackRoute: string): void {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const enabledIds = useEnabledModuleIds();

  useEffect(() => {
    if (!isLocationBlocked(pathname, search, enabledIds)) return;
    // `replace` so Back doesn't bounce the user into the blocked route again.
    navigate(fallbackRoute, { replace: true });
  }, [enabledIds, fallbackRoute, navigate, pathname, search]);
}
