import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { legacyTeamWorkspaceTarget } from "@/core/router/legacy-workspace-routes";

export default function TeamNewPage() {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    navigate(legacyTeamWorkspaceTarget("new", location.search), {
      replace: true,
    });
  }, [location.search, navigate]);

  return null;
}
