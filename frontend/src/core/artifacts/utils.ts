import { getBackendBaseURL } from "../config";
import type { AgentThread } from "../threads";

export type WorkspaceOutputArea =
  | "output"
  | "stages"
  | "final"
  | "deploy"
  | "upload";

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

export function parseWorkspaceOutputRef(
  filepath: string,
): { area: WorkspaceOutputArea; relativePath: string } | null {
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

/**
 * Convert a runtime-emitted absolute workspace path into the stable artifact
 * reference understood by the per-thread outputs API.  Tool traces carry
 * absolute paths for auditability, while the preview endpoint intentionally
 * accepts only a scoped relative path.
 */
export function normalizeWorkspaceArtifactRef(filepath: string, threadId?: string) {
  if (!threadId || parseWorkspaceOutputRef(filepath)) return filepath;
  const parts = filepath.replaceAll("\\", "/").split("/").filter(Boolean);
  const workspaceIndex = parts.lastIndexOf("workspaces");
  if (workspaceIndex < 0 || parts[workspaceIndex + 1] !== threadId) {
    return filepath;
  }
  const root = workspaceIndex + 2;
  const area = parts[root];
  if (!area) return filepath;

  if (area === "output") {
    const nestedArea = parts[root + 1];
    if (nestedArea === "final" || nestedArea === "stages") {
      const relativePath = parts.slice(root + 2).join("/");
      return relativePath ? workspaceOutputRef({ area: nestedArea, relativePath }) : filepath;
    }
  }
  if (["output", "deploy", "upload"].includes(area)) {
    const relativePath = parts.slice(root + 1).join("/");
    return relativePath
      ? workspaceOutputRef({ area: area as WorkspaceOutputArea, relativePath })
      : filepath;
  }
  return filepath;
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
