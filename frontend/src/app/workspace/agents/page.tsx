import { AgentWorldUnified } from "@/components/workspace/agents/agent-world-unified";
import CliTeamPanel from "@/components/workspace/cli-team-panel";

/* Implementation note. */
export default function AgentsPage() {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <div className="shrink-0 p-2">
        <CliTeamPanel />
      </div>
      <div className="min-h-0 flex-1">
        <AgentWorldUnified />
      </div>
    </div>
  );
}
