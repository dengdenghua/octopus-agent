import { Navigate, useLocation } from "react-router-dom";
import { legacyTeamWorkspaceTarget } from "@/core/router/legacy-workspace-routes";

export default function TeamNewPage() {
  const location = useLocation();

  return (
    <Navigate to={legacyTeamWorkspaceTarget("new", location.search)} replace />
  );
}
