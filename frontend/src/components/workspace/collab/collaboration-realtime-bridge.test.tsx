import { act, render, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CollaborationRealtimeBridge,
  countOnlineRoomParticipants,
} from "./collaboration-realtime-bridge";

vi.mock("@/core/auth/api", () => ({ getToken: () => "room-token" }));
vi.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
  getBackendWebSocketBaseURL: () => "ws://collab.test",
}));

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readonly protocols?: string | string[];
  readyState = FakeWebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = protocols;
    FakeWebSocket.instances.push(this);
  }

  send = vi.fn();

  close = vi.fn(() => {
    this.readyState = FakeWebSocket.CLOSED;
  });

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  receive(payload: Record<string, unknown>) {
    this.onmessage?.(
      new MessageEvent("message", { data: JSON.stringify(payload) }),
    );
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("countOnlineRoomParticipants", () => {
  it("counts unique active room members", () => {
    expect(
      countOnlineRoomParticipants([
        { id: "alice", status: "active" },
        { id: "alice", status: "online" },
        { id: "bob", status: "offline" },
        { participant_id: "carol", status: "online" },
        { id: "removed", status: "removed" },
      ]),
    ).toBe(2);
  });

  it("connects the open workspace and refreshes its canonical session", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const invalidate = vi
      .spyOn(queryClient, "invalidateQueries")
      .mockResolvedValue(undefined);
    const view = render(
      <QueryClientProvider client={queryClient}>
        <CollaborationRealtimeBridge
          roomId="room one"
          threadId="thread-1"
          participantId="alice"
          displayName="Alice"
        />
      </QueryClientProvider>,
    );

    const socket = FakeWebSocket.instances[0];
    expect(socket.url).toBe(
      "ws://collab.test/api/teams/room%20one/ws?participant_id=alice&display_name=Alice&thread_id=thread-1",
    );
    expect(socket.protocols).toEqual(["bearer.b64", "cm9vbS10b2tlbg"]);

    act(() => {
      socket.open();
      socket.receive({
        type: "presence",
        participants: [{ id: "alice", display_name: "Alice" }],
      });
    });
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ["cowork", "session", "thread-1"],
      }),
    );

    view.unmount();
    expect(socket.close).toHaveBeenCalled();
  });
});
