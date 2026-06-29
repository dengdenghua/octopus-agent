import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useEffect } from "react";

import { legacyTeamWorkspaceTarget } from "@/core/router/legacy-workspace-routes";

export default function TeamPage() {
  const navigate = useNavigate();
  const { threadId } = useParams<{ threadId?: string }>();
  const { search } = useLocation();

  useEffect(() => {
    navigate(legacyTeamWorkspaceTarget(threadId, search), { replace: true });
  }, [navigate, search, threadId]);

  return null;
}
