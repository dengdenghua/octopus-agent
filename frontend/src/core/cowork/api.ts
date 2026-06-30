import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";

import type {
  CoworkGroupResponse,
  CoworkInviteInput,
  CoworkMode,
  CoworkPresenceResponse,
  CoworkSearchKind,
  CoworkSearchResponse,
} from "./types";

const BASE = () => `${getBackendBaseURL()}/api/cowork`;

async function parseJson<T>(res: Response, action: string): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(
      `${action} failed: ${res.status}${detail ? ` ${detail}` : ` ${res.statusText}`}`,
    );
  }
  return (await res.json()) as T;
}

export async function getCoworkGroup(
  threadId: string,
): Promise<CoworkGroupResponse> {
  const res = await fetch(`${BASE()}/${encodeURIComponent(threadId)}`, {
    headers: authHeaders(),
  });
  return parseJson<CoworkGroupResponse>(res, "Load cowork group");
}

export async function inviteCoworkMember(
  threadId: string,
  input: CoworkInviteInput,
): Promise<CoworkGroupResponse["state"]> {
  const res = await fetch(
    `${BASE()}/${encodeURIComponent(threadId)}/members`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({
        kind: "agent",
        role: "participant",
        grant: { scope: "all", ...(input.grant ?? {}) },
        ...input,
      }),
    },
  );
  const data = await parseJson<{ ok: boolean; state: CoworkGroupResponse["state"] }>(
    res,
    "Invite cowork member",
  );
  return data.state;
}

export async function removeCoworkMember(
  threadId: string,
  memberId: string,
): Promise<CoworkGroupResponse["state"]> {
  const res = await fetch(
    `${BASE()}/${encodeURIComponent(threadId)}/members/${encodeURIComponent(
      memberId,
    )}`,
    {
      method: "DELETE",
      headers: authHeaders(),
    },
  );
  const data = await parseJson<{ ok: boolean; state: CoworkGroupResponse["state"] }>(
    res,
    "Remove cowork member",
  );
  return data.state;
}

export async function setCoworkMode(
  threadId: string,
  mode: CoworkMode,
): Promise<CoworkGroupResponse["state"]> {
  const res = await fetch(`${BASE()}/${encodeURIComponent(threadId)}/mode`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify({ mode }),
  });
  const data = await parseJson<{ ok: boolean; state: CoworkGroupResponse["state"] }>(
    res,
    "Set cowork mode",
  );
  return data.state;
}

export async function searchCowork(
  threadId: string,
  query: string,
  opts: { kinds?: CoworkSearchKind[]; limit?: number; untilSeq?: number } = {},
): Promise<CoworkSearchResponse> {
  const params = new URLSearchParams({ q: query });
  if (opts.kinds?.length) params.set("kinds", opts.kinds.join(","));
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.untilSeq != null) params.set("until_seq", String(opts.untilSeq));
  const res = await fetch(
    `${BASE()}/${encodeURIComponent(threadId)}/search?${params.toString()}`,
    { headers: authHeaders() },
  );
  return parseJson<CoworkSearchResponse>(res, "Search cowork group");
}

export async function getCoworkPresence(
  threadId: string,
): Promise<CoworkPresenceResponse> {
  const res = await fetch(
    `${BASE()}/${encodeURIComponent(threadId)}/presence`,
    { headers: authHeaders() },
  );
  return parseJson<CoworkPresenceResponse>(res, "Load cowork presence");
}

export async function markCoworkRead(
  threadId: string,
  memberId: string,
  seq?: number,
): Promise<void> {
  const res = await fetch(`${BASE()}/${encodeURIComponent(threadId)}/read`, {
    method: "POST",
    headers: jsonAuthHeaders(),
    body: JSON.stringify({ member_id: memberId, ...(seq != null ? { seq } : {}) }),
  });
  await parseJson<{ ok: boolean }>(res, "Mark cowork read");
}

export async function coworkHeartbeat(
  threadId: string,
  memberId: string,
): Promise<void> {
  const res = await fetch(
    `${BASE()}/${encodeURIComponent(threadId)}/heartbeat`,
    {
      method: "POST",
      headers: jsonAuthHeaders(),
      body: JSON.stringify({ member_id: memberId }),
    },
  );
  await parseJson<{ ok: boolean }>(res, "Cowork heartbeat");
}
