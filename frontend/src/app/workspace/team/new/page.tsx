import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { uuid } from "@/core/utils/uuid";

export default function TeamNewPage() {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const newThreadId = uuid();
    navigate(`/workspace/team/${newThreadId}${location.search}`, {
      replace: true,
    });
  }, [location.search, navigate]);

  return null;
}
