import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/providers/AuthProvider";

/**
 * Route guard that redirects unauthenticated users to /login.
 *
 * When auth is disabled on the backend (authStatus.enabled === false),
 * all users are allowed through — matching the backend's behavior.
 */
export function ProtectedRoute() {
  const { isLoading, authStatus, isAuthenticated, isGuest } = useAuth();

  // Still loading auth status — show nothing to avoid flash
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-muted-foreground text-sm">Loading...</div>
      </div>
    );
  }

  // Auth disabled on backend — let everyone through
  if (authStatus && !authStatus.enabled) {
    return <Outlet />;
  }

  // Auth enabled but not authenticated and not guest — redirect to login
  if (!isAuthenticated && !isGuest) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}
