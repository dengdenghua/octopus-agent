/**
 * Custom hook for managing PC screen-stream WebSocket connection.
 *
 * Connects to `WS /api/tentacle/pc-screen/stream`, receives binary frames
 * of the PC desktop, and renders them onto a <canvas>.
 *
 * Also supports sending remote input events (tap, swipe, type) back to
 * the PC via `POST /api/tentacle/remote-input`.
 *
 * Binary frame format is the same as device screen stream:
 *   byte 0-1   : tentacle_id length (uint16 BE)
 *   byte 2     : frame type (0x01 | 0x02 | 0x03)
 *   byte 3     : flags (bit 0 = keyframe)
 *   byte 4..   : tentacle_id (UTF-8)
 *   byte 4+len : frame payload
 */

import { useCallback, useEffect, useRef, useState } from "react";

// ── Types ──────────────────────────────────────────────

export interface PcScreenStreamState {
  isConnected: boolean;
  frameCount: number;
  error: string | null;
  fps: number;
}

export interface RemoteInputEvent {
  action: "tap" | "double_tap" | "long_press" | "swipe" | "type_text" | "key_press";
  x?: number;
  y?: number;
  x2?: number;
  y2?: number;
  duration_ms?: number;
  text?: string;
  key?: string;
}

// ── Frame header constants ─────────────────────────────

const FRAME_TYPE_JPEG = 0x02;
const FRAME_TYPE_WEBP = 0x03;

// ── Helpers ────────────────────────────────────────────

function buildPcWsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/tentacle/pc-screen/stream`;
}

function parseFrameHeader(buf: ArrayBuffer): {
  idLen: number;
  frameType: number;
  flags: number;
  tentacleId: string;
  payload: ArrayBuffer;
} | null {
  if (buf.byteLength < 4) return null;
  const view = new DataView(buf);
  const idLen = view.getUint16(0, false);
  if (buf.byteLength < 4 + idLen) return null;
  const frameType = view.getUint8(2);
  const flags = view.getUint8(3);
  const decoder = new TextDecoder();
  const tentacleId = decoder.decode(new Uint8Array(buf, 4, idLen));
  const payload = buf.slice(4 + idLen);
  return { idLen, frameType, flags, tentacleId, payload };
}

// ── Hook ───────────────────────────────────────────────

export function usePcScreenStream(
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
): PcScreenStreamState & { sendInput: (event: RemoteInputEvent) => Promise<void> } {
  const [isConnected, setIsConnected] = useState(false);
  const [frameCount, setFrameCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [fps, setFps] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const fpsFramesRef = useRef<number[]>([]);

  // ── Render JPEG / WebP frame ────────────────────────

  const renderImageFrame = useCallback(
    (payload: ArrayBuffer, frameType: number) => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }

      const mime = frameType === FRAME_TYPE_WEBP ? "image/webp" : "image/jpeg";
      const blob = new Blob([payload], { type: mime });
      const url = URL.createObjectURL(blob);
      objectUrlRef.current = url;

      const img = new Image();
      img.onload = () => {
        const canvas = canvasRef.current;
        if (canvas) {
          const ctx = canvas.getContext("2d");
          if (ctx) {
            if (canvas.width !== img.naturalWidth || canvas.height !== img.naturalHeight) {
              canvas.width = img.naturalWidth;
              canvas.height = img.naturalHeight;
            }
            ctx.drawImage(img, 0, 0);
          }
        }
      };
      img.src = url;
    },
    [canvasRef],
  );

  // ── Handle incoming binary message ──────────────────

  const handleMessage = useCallback(
    (data: ArrayBuffer) => {
      const parsed = parseFrameHeader(data);
      if (!parsed) return;

      const { frameType, payload } = parsed;

      if (frameType === FRAME_TYPE_JPEG || frameType === FRAME_TYPE_WEBP) {
        renderImageFrame(payload, frameType);
      }

      setFrameCount((c) => c + 1);

      const now = performance.now();
      fpsFramesRef.current.push(now);
      fpsFramesRef.current = fpsFramesRef.current.filter((t) => now - t < 1000);
      setFps(fpsFramesRef.current.length);
    },
    [renderImageFrame],
  );

  // ── Send remote input event ────────────────────────

  const sendInput = useCallback(async (event: RemoteInputEvent) => {
    try {
      const res = await fetch("/api/tentacle/remote-input", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(event),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        console.error("Remote input failed:", body.detail || res.statusText);
      }
    } catch (e) {
      console.error("Remote input error:", e);
    }
  }, []);

  // ── Connect / disconnect ────────────────────────────

  const connect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    const ws = new WebSocket(buildPcWsUrl());
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      setError(null);
    };

    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) {
        handleMessage(ev.data);
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      // Auto-reconnect after 3s
      reconnectTimerRef.current = setTimeout(() => {
        connect();
      }, 3000);
    };

    ws.onerror = () => {
      setError("PC screen WebSocket connection error");
      ws.close();
    };
  }, [handleMessage]);

  // ── Lifecycle ───────────────────────────────────────

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
      setIsConnected(false);
      setFrameCount(0);
      setFps(0);
      setError(null);
    };
  }, [connect]);

  return { isConnected, frameCount, error, fps, sendInput };
}
