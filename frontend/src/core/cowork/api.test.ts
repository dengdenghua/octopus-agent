import { beforeEach, describe, expect, test, vi } from "vitest";

import {
  getCollabSession,
  getCoworkGroup,
  inviteCoworkMember,
  linkCoworkRoom,
  removeCoworkMember,
  setCoworkMode,
} from "./api";

const fetchMock = vi.fn();

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const state = {
  roster: [],
  mode: "chat",
  event_count: 0,
  is_one_to_one: true,
};

describe("cowork api", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  test("loads a thread cowork group", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        thread_id: "thread/1",
        state,
        blackboard: {},
        events: [],
        responders: [],
      }),
    );

    const group = await getCoworkGroup("thread/1");

    expect(group.thread_id).toBe("thread/1");
    expect(fetchMock).toHaveBeenCalledWith("/api/cowork/thread%2F1", {
      headers: {},
    });
  });

  test("invites, removes, and switches mode on a thread group", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ ok: true, state }))
      .mockResolvedValueOnce(jsonResponse({ ok: true, state }))
      .mockResolvedValueOnce(jsonResponse({ ok: true, state }));

    await inviteCoworkMember("thread/1", {
      target_id: "codex-cli",
      grant: { scope: "from_join" },
    });
    await removeCoworkMember("thread/1", "codex-cli");
    await setCoworkMode("thread/1", "swarm");

    expect(fetchMock.mock.calls[0]).toEqual([
      "/api/cowork/thread%2F1/members",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: "agent",
          role: "participant",
          grant: { scope: "from_join" },
          target_id: "codex-cli",
        }),
      },
    ]);
    expect(fetchMock.mock.calls[1]).toEqual([
      "/api/cowork/thread%2F1/members/codex-cli",
      { method: "DELETE", headers: {} },
    ]);
    expect(fetchMock.mock.calls[2]).toEqual([
      "/api/cowork/thread%2F1/mode",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "swarm" }),
      },
    ]);
  });

  test("throws response details on failure", async () => {
    fetchMock.mockResolvedValueOnce(new Response("nope", { status: 401 }));

    await expect(getCoworkGroup("thread-1")).rejects.toThrow(
      "Load cowork group failed: 401 nope",
    );
  });

  test("loads the unified collaboration session", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        session_id: "thread/1",
        room_id: "room-9",
        mode: "swarm",
        roster: [],
        blackboard: {},
        tasks: [],
        presence: [],
        room_messages: [{ text: "hi" }],
        room_participants: [{ id: "p1" }],
      }),
    );

    const session = await getCollabSession("thread/1");

    expect(session.session_id).toBe("thread/1");
    expect(session.room_id).toBe("room-9");
    expect(session.room_messages).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledWith("/api/collab/thread%2F1", {
      headers: {},
    });
  });

  test("links a team room to a session", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: true, state }));

    await linkCoworkRoom("thread/1", "room-9");

    expect(fetchMock.mock.calls[0]).toEqual([
      "/api/collab/thread%2F1/link-room",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ room_id: "room-9" }),
      },
    ]);
  });
});
