import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { uuid } from "@/core/utils/uuid";

export default function TeamNewPage() {
  const navigate = useNavigate();

  useEffect(() => {
    const newThreadId = uuid();
    navigate(`/workspace/team/${newThreadId}`, { replace: true });
  }, [navigate]);

  return null;
}
