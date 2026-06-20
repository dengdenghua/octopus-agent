import { Navigate, useParams } from "react-router-dom";

export default function RealtimeThreadPage() {
  const { threadId } = useParams<{ threadId: string }>();
  return (
    <Navigate
      to={
        threadId ? `/workspace/realtime/${threadId}` : "/workspace/realtime/new"
      }
      replace
    />
  );
}
