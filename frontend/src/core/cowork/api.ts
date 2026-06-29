import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";

import type {
  CoworkGroupResponse,
  CoworkInviteInput,
  CoworkMode,
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
