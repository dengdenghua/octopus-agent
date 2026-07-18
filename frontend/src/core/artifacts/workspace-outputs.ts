import { authHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";

import { type WorkspaceOutputArea, workspaceOutputRef } from "./utils";

export interface WorkspaceOutputEntry {
  name: string;
  area: WorkspaceOutputArea;
  relative_path: string;
  path: string;
  size: number;
  modified: number;
  download_url: string;
}

interface WorkspaceOutputsResponse {
  thread_id: string;
  area: WorkspaceOutputArea;
  files: WorkspaceOutputEntry[];
  count: number;
}

const ARTIFACT_AREAS: WorkspaceOutputArea[] = [
  "final",
  "deploy",
  "stages",
  "output",
];

async function listWorkspaceOutputArea(
  threadId: string,
  area: WorkspaceOutputArea,
  signal?: AbortSignal,
): Promise<WorkspaceOutputEntry[]> {
  const params = new URLSearchParams({ area });
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/outputs?${params.toString()}`,
    { headers: authHeaders(), signal },
  );
  if (!response.ok) return [];
  const data = (await response.json()) as WorkspaceOutputsResponse;
  return data.files ?? [];
}

export async function listWorkspaceArtifactRefs(
  threadId: string,
  signal?: AbortSignal,
): Promise<string[]> {
  const results = await Promise.allSettled(
    ARTIFACT_AREAS.map((area) => listWorkspaceOutputArea(threadId, area, signal)),
  );
  const refs: string[] = [];
  const seen = new Set<string>();

  for (const result of results) {
    if (result.status !== "fulfilled") continue;
    for (const file of result.value) {
      const ref = workspaceOutputRef({
        area: file.area,
        relativePath: file.relative_path,
      });
      const key = `${file.path || file.area}:${file.relative_path}`;
      if (seen.has(key)) continue;
      seen.add(key);
      refs.push(ref);
    }
  }

  return refs;
}
