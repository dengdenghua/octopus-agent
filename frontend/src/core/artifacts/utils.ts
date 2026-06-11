import { getBackendBaseURL } from "../config";
import type { AgentThread } from "../threads";

export type WorkspaceOutputArea = "output" | "stages" | "final" | "deploy" | "upload";

const WORKSPACE_OUTPUT_PREFIX = "workspace-output:";

export function workspaceOutputRef({
  area,
  relativePath,
}: {
  area: WorkspaceOutputArea;
  relativePath: string;
}) {
  return `${WORKSPACE_OUTPUT_PREFIX}${area}:${relativePath.replace(/^\/+/, "")}`;
}

export function parseWorkspaceOutputRef(filepath: string):
  | { area: WorkspaceOutputArea; relativePath: string }
  | null {
  if (!filepath.startsWith(WORKSPACE_OUTPUT_PREFIX)) return null;
  const rest = filepath.slice(WORKSPACE_OUTPUT_PREFIX.length);
  const separator = rest.indexOf(":");
  if (separator <= 0) return null;
  const area = rest.slice(0, separator) as WorkspaceOutputArea;
  if (!["output", "stages", "final", "deploy", "upload"].includes(area)) {
    return null;
  }
  const relativePath = rest.slice(separator + 1).replace(/^\/+/, "");
  if (!relativePath) return null;
  return { area, relativePath };
}

export function artifactDisplayPath(filepath: string) {
  return parseWorkspaceOutputRef(filepath)?.relativePath ?? filepath;
}

function encodeArtifactPath(path: string) {
  return path
    .replace(/^\/+/, "")
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
}

export function urlOfArtifact({
  filepath,
  threadId,
  download = false,
  isMock = false,
}: {
  filepath: string;
  threadId: string;
  download?: boolean;
  isMock?: boolean;
}) {
  const workspaceOutput = parseWorkspaceOutputRef(filepath);
  if (workspaceOutput) {
    const params = new URLSearchParams({ area: workspaceOutput.area });
    if (download) params.set("download", "true");
    return `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/outputs/${encodeArtifactPath(workspaceOutput.relativePath)}?${params.toString()}`;
  }
  if (isMock) {
    return `${getBackendBaseURL()}/mock/api/threads/${threadId}/artifacts${filepath}${download ? "?download=true" : ""}`;
  }
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${filepath}${download ? "?download=true" : ""}`;
}

export function extractArtifactsFromThread(thread: AgentThread) {
  return thread.values.artifacts ?? [];
}

export function resolveArtifactURL(absolutePath: string, threadId: string) {
  return `${getBackendBaseURL()}/api/threads/${threadId}/artifacts${absolutePath}`;
}

