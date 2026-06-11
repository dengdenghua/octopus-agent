// Realtime WebSocket client.
//
// One client per thread (or per conversation). Owns:
//
//   * The WebSocket lifecycle — connect, exponential reconnect, close.
//   * JSON-RPC id minting + pending request tracker.
//   * Approval handler — server-initiated requests are routed to a
//     caller-supplied callback that returns the decision; the client
//     replies on the same channel.
//   * Notification dispatch — pushed events go through the supplied
//     reducer; observers subscribe to state snapshots.
//
// Designed to live behind a React hook (see ``useRealtimeThread``)
// that exposes ``state``, ``send``, ``startTurn``, ``resolveApproval``.

import { swallow } from "@/core/utils/log";
import {
  type Envelope,
  type JsonRpcError,
  type JsonRpcId,
  type JsonRpcRequest,
  type JsonRpcResponse,
  type Notification,
  isNotification,
  isRequest,
  isResponse,
} from "./envelope";

export interface RealtimeClientOptions {
  url: string;
  onIncomingRequest: (request: JsonRpcRequest) => Promise<unknown>;
  onNotification: (note: Notification) => void;
  onOpen?: () => void;
  onClose?: (code: number, reason: string) => void;
  onError?: (err: Event | Error) => void;
  // Reconnect schedule. Each retry waits the indexed delay (ms) until
  // ``maxBackoffMs`` is reached, then plateaus there.
  initialBackoffMs?: number;
  maxBackoffMs?: number;
  // Bearer token resolver. Called per-connect so a refreshed token is
  // picked up after reconnect without restarting the page.
  authToken?: () => string | null;
}

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason: JsonRpcError | Error) => void;
}

const DEFAULT_INITIAL_BACKOFF = 500;
const DEFAULT_MAX_BACKOFF = 15_000;
const GUEST_AUTH_TOKEN = "__guest__";

// Delta notification methods that participate in delta-coalescing.
// Used by the coalesce step (which merges N consecutive deltas with the
// same itemId into one). Snapshot-style notifications (item/started,
// item/completed) are batched too — see BATCHED_METHODS — but never
// merged.
const DELTA_METHODS = new Set([
  "item/agentMessage/delta",
  "item/reasoning/textDelta",
  "item/plan/delta",
  "item/commandExecution/outputDelta",
]);

// Application-level heartbeat interval. Keeps proxies and firewalls from
// silently closing idle WebSocket connections during long tool executions.
const HEARTBEAT_INTERVAL_MS = 25_000;
// If we don't see a pong for this long, the connection is considered
// wedged (silent TCP half-open, proxy black-hole, etc) and we force-close
// it so the reconnect path runs. Two missed pings + slack.
const PONG_TIMEOUT_MS = 70_000;

// Methods coalesced/batched on the next animation frame to keep React
// renders down. Includes both delta methods AND the lifecycle envelopes
// (item/started, item/completed) so the dispatch order matches the
// websocket arrival order even though item/* land synchronously and
// deltas hop through requestAnimationFrame. Without buffering started/
// completed too, a frame boundary between ``started`` and the deltas
// reorders them: completed lands first, the reducer's status guard
// then drops the deltas as "stale" and the user sees an empty bubble.
const BATCHED_METHODS = new Set([
  "item/started",
  "item/completed",
  "item/agentMessage/delta",
  "item/reasoning/textDelta",
  "item/plan/delta",
  "item/commandExecution/outputDelta",
]);

export class RealtimeClient {
  private ws: WebSocket | null = null;
  private nextId = 1;
  private pending = new Map<JsonRpcId, PendingRequest>();
  private opts: RealtimeClientOptions;
  private closed = false;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private outbox: string[] = [];
  // Backoff bounds, captured once so changing the option after construct
  // doesn't behave inconsistently mid-flight.
  private readonly initialBackoff: number;
  private readonly maxBackoff: number;
  // Delta batching: buffer high-frequency delta notifications and flush
  // them together in a single animation frame to reduce React re-renders.
  private deltaBuffer: Notification[] = [];
  private deltaFlushPending = false;
  // Heartbeat timer — cleared on close and reconnect.
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  // Timestamp of the last pong (or open). Used by the heartbeat tick to
  // decide whether the connection should be considered dead.
  private lastPongAt: number = 0;

  constructor(opts: RealtimeClientOptions) {
    this.opts = opts;
    this.initialBackoff = opts.initialBackoffMs ?? DEFAULT_INITIAL_BACKOFF;
    this.maxBackoff = opts.maxBackoffMs ?? DEFAULT_MAX_BACKOFF;
  }

  // ── Lifecycle ──────────────────────────────────────────────

  connect(): void {
    if (this.closed) return;
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    const url = this.buildUrl();
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch (err) {
      swallow(err);
      this.opts.onError?.(err as Error);
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.lastPongAt = Date.now();
      this.flushOutbox();
      this.startHeartbeat();
      this.opts.onOpen?.();
    };
    ws.onmessage = ev => {
      this.dispatch(typeof ev.data === "string" ? ev.data : "");
    };
    ws.onerror = ev => {
      this.opts.onError?.(ev);
    };
    ws.onclose = ev => {
      this.stopHeartbeat();
      this.flushDeltaBuffer();
      this.opts.onClose?.(ev.code, ev.reason);
      this.failPending(new Error(`websocket closed (${ev.code} ${ev.reason || "no reason"})`));
      // Clear the outbox on disconnect. Anything that was buffered
      // for "send on next open" was a request whose Promise has now
      // been rejected by failPending; replaying those frames after a
      // reconnect would re-send turn/start (or an interrupt, etc.)
      // with no caller listening for the response — duplicate work
      // on the server, ghost UI on the client. Leave the buffer
      // empty so callers re-issue requests explicitly when they want
      // them.
      this.outbox.length = 0;
      this.ws = null;
      if (!this.closed) {
        this.scheduleReconnect();
      }
    };
  }

  close(): void {
    this.closed = true;
    this.stopHeartbeat();
    this.flushDeltaBuffer();
    if (this.reconnectTimer != null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.failPending(new Error("client closed"));
  }

  // ── Send paths ─────────────────────────────────────────────

  request<R = unknown>(method: string, params: Record<string, unknown> = {}): Promise<R> {
    const id = this.nextId++;
    const envelope: JsonRpcRequest = { jsonrpc: "2.0", id, method, params };
    return new Promise<R>((resolve, reject) => {
      this.pending.set(id, {
        resolve: (v: unknown) => resolve(v as R),
        reject,
      });
      this.send(envelope);
    });
  }

  notify(method: string, params: Record<string, unknown> = {}): void {
    this.send({ jsonrpc: "2.0", method, params });
  }

  // Reply to a server-initiated request. Bypasses the pending tracker —
  // we are the *responder*, not the requester.
  reply(id: JsonRpcId, result: unknown, error?: JsonRpcError): void {
    const env: JsonRpcResponse = error
      ? { jsonrpc: "2.0", id, error }
      : { jsonrpc: "2.0", id, result };
    this.send(env);
  }

  // ── Internal ───────────────────────────────────────────────

  private buildUrl(): string {
    const token = this.opts.authToken?.() ?? null;
    if (!token || token === GUEST_AUTH_TOKEN) return this.opts.url;
    const sep = this.opts.url.includes("?") ? "&" : "?";
    return `${this.opts.url}${sep}token=${encodeURIComponent(token)}`;
  }

  private send(env: Envelope): void {
    const text = JSON.stringify(env);
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(text);
      return;
    }
    // Buffer; flushed on next ``onopen``. Bound the buffer so a
    // perpetually-disconnected client doesn't grow without limit.
    if (this.outbox.length >= 256) {
      this.outbox.shift();
    }
    this.outbox.push(text);
  }

  private flushOutbox(): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    const pending = this.outbox.splice(0, this.outbox.length);
    for (const text of pending) {
      this.ws.send(text);
    }
  }

  private dispatch(text: string): void {
    if (!text) return;
    let env: Envelope;
    try {
      env = JSON.parse(text) as Envelope;
    } catch (err) {
      swallow(err);
      this.opts.onError?.(err as Error);
      return;
    }
    if (isResponse(env)) {
      const handler = this.pending.get(env.id);
      if (!handler) return;
      this.pending.delete(env.id);
      if (env.error) {
        handler.reject(env.error);
      } else {
        handler.resolve(env.result);
      }
      return;
    }
    if (isRequest(env)) {
      // Server-initiated. Route to the caller and reply with the
      // decision. Errors are translated to a JSON-RPC error response so
      // the server's awaiting future doesn't hang.
      this.opts.onIncomingRequest(env)
        .then(result => this.reply(env.id, result))
        .catch((err: unknown) => {
          const message = err instanceof Error ? err.message : String(err);
          this.reply(env.id, null, { code: -32603, message });
        });
      return;
    }
    if (isNotification(env)) {
      // Server-side liveness reply. Updating the watermark must happen
      // *before* any further routing — pong should never reach the
      // application reducer.
      if (env.method === "pong") {
        this.lastPongAt = Date.now();
        return;
      }
      if (BATCHED_METHODS.has(env.method)) {
        this.deltaBuffer.push(env);
        if (!this.deltaFlushPending) {
          this.deltaFlushPending = true;
          requestAnimationFrame(() => this.flushDeltaBuffer());
        }
      } else {
        this.opts.onNotification(env);
      }
    }
  }

  private flushDeltaBuffer(): void {
    this.deltaFlushPending = false;
    if (this.deltaBuffer.length === 0) return;
    const batch = coalesceDeltaNotifications(this.deltaBuffer.splice(0));
    for (const note of batch) {
      // A single bad notification (reducer bug, listener throw) used
      // to abort the whole RAF batch and silently drop subsequent
      // deltas — including the agentMessage chunks the user is
      // staring at. Isolate each handler call so one bad apple
      // doesn't poison the rest of the frame.
      try {
        this.opts.onNotification(note);
      } catch (err) {
        swallow(err);
        this.opts.onError?.(err as Error);
      }
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      // Detect a wedged connection: server is alive enough for the
      // socket to stay open but stopped responding (proxy half-open,
      // load-balancer ghost session). Force-close so onclose triggers
      // the reconnect path.
      if (this.lastPongAt > 0 && Date.now() - this.lastPongAt > PONG_TIMEOUT_MS) {
        this.ws?.close(4000, "pong timeout");
        return;
      }
      this.notify("ping", {});
    }, HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer != null) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.closed) return;
    if (this.reconnectTimer != null) return;
    const idx = Math.min(this.reconnectAttempts, 12);
    const base = Math.min(this.initialBackoff * 2 ** idx, this.maxBackoff);
    // Full jitter: pick uniformly in [0, base]. Keeps thundering-herd
    // away when many clients reconnect after a server bounce.
    const wait = Math.floor(Math.random() * base);
    this.reconnectAttempts++;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, wait);
  }

  private failPending(reason: Error): void {
    if (this.pending.size === 0) return;
    for (const handler of this.pending.values()) {
      handler.reject(reason);
    }
    this.pending.clear();
  }
}

// Convenience builder: returns a wired client with sensible defaults
// for an octopus-agent backend.
export function createDefaultClient(args: {
  baseURL: string;
  threadId?: string;
  authToken?: () => string | null;
  onIncomingRequest: RealtimeClientOptions["onIncomingRequest"];
  onNotification: RealtimeClientOptions["onNotification"];
  onOpen?: RealtimeClientOptions["onOpen"];
  onClose?: RealtimeClientOptions["onClose"];
  onError?: RealtimeClientOptions["onError"];
}): RealtimeClient {
  const wsUrl = toWebSocketURL(args.baseURL, "/api/realtime");
  return new RealtimeClient({
    url: wsUrl,
    authToken: args.authToken,
    onIncomingRequest: args.onIncomingRequest,
    onNotification: args.onNotification,
    onOpen: args.onOpen,
    onClose: args.onClose,
    onError: args.onError,
  });
}

function toWebSocketURL(httpBase: string, path: string): string {
  const trimmed = (httpBase || "").replace(/\/+$/, "");
  if (!trimmed) {
    // Same-origin (vite dev proxy routes /api/* through to backend).
    if (typeof window !== "undefined") {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      return `${proto}//${window.location.host}${path}`;
    }
    return `ws://localhost:8000${path}`;
  }
  if (trimmed.startsWith("https://")) return `wss://${trimmed.slice(8)}${path}`;
  if (trimmed.startsWith("http://")) return `ws://${trimmed.slice(7)}${path}`;
  return `${trimmed}${path}`;
}

function coalesceDeltaNotifications(batch: Notification[]): Notification[] {
  const merged: Notification[] = [];
  for (const note of batch) {
    const last = merged[merged.length - 1];
    if (last && canMergeDeltaNotifications(last, note)) {
      const previousParams = last.params as Record<string, unknown>;
      const nextParams = note.params as Record<string, unknown>;
      merged[merged.length - 1] = {
        ...last,
        params: {
          ...previousParams,
          delta: String(previousParams.delta ?? "") + String(nextParams.delta ?? ""),
        },
      };
      continue;
    }
    merged.push(note);
  }
  return merged;
}

function canMergeDeltaNotifications(left: Notification, right: Notification): boolean {
  if (left.method !== right.method) return false;
  // Only delta-style notifications carry appendable text. ``item/started``
  // / ``item/completed`` snapshots must never merge — they replace,
  // not append, so coalescing two of them would silently drop one.
  if (!DELTA_METHODS.has(left.method)) return false;
  const leftParams = left.params as Record<string, unknown>;
  const rightParams = right.params as Record<string, unknown>;
  if (left.method === "item/reasoning/textDelta") {
    return (
      leftParams.threadId === rightParams.threadId &&
      leftParams.turnId === rightParams.turnId &&
      leftParams.itemId === rightParams.itemId &&
      leftParams.contentIndex === rightParams.contentIndex
    );
  }
  return (
    leftParams.threadId === rightParams.threadId &&
    leftParams.turnId === rightParams.turnId &&
    leftParams.itemId === rightParams.itemId
  );
}
