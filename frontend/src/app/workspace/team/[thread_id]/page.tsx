import { Navigate, useLocation, useParams } from "react-router-dom";

import { legacyTeamWorkspaceTarget } from "@/core/router/legacy-workspace-routes";

export default function TeamPage() {
  const { threadId } = useParams<{ threadId?: string }>();
  const { search } = useLocation();

  return <Navigate to={legacyTeamWorkspaceTarget(threadId, search)} replace />;
}
