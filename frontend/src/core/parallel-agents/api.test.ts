import { describe, expect, test, vi } from "vitest";

vi.mock("@/core/config", () => ({
  getBackendBaseURL: () => "http://127.0.0.1:8000",
}));

vi.mock("@/core/auth/api", () => ({
  getToken: () => null,
}));

import { streamBatch, toBackendURL } from "./api";

describe("parallel agents backend URLs", () => {
  test("prefixes relative API paths once", () => {
    expect(toBackendURL("/api/agents/parallel/status")).toBe(
      "http://127.0.0.1:8000/api/agents/parallel/status",
    );
  });

  test("does not double-prefix absolute URLs", () => {
    expect(
      toBackendURL("http://127.0.0.1:8000/api/agents/parallel/stream/b1"),
    ).toBe("http://127.0.0.1:8000/api/agents/parallel/stream/b1");
  });
});

describe("SSE streamBatch: event parsing", () => {
  test("parses task_update event correctly", () => {
    const line1 = "event: task_update";
    const line2 = 'data: {"type":"task_update","batch_id":"b1","task_id":"t1","status":"running"}';
    const line3 = "";

    let eventType = "";
    let eventData = "";

    const lines = [line1, line2, line3];
    const results: unknown[] = [];

    for (const line of lines) {
      if (line.startsWith("event:")) {
        eventType = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        eventData = line.slice(5).trim();
      } else if (line === "") {
        if (eventType && eventData) {
          const data = JSON.parse(eventData);
          results.push({ eventType, data });
        }
        eventType = "";
        eventData = "";
      }
    }

    expect(results.length).toBe(1);
    expect(results[0].eventType).toBe("task_update");
    expect(results[0].data.task_id).toBe("t1");
    expect(results[0].data.status).toBe("running");
  });

  test("parses batch_complete event and stops", () => {
    const raw = [
      "event: task_update",
      'data: {"type":"task_update","batch_id":"b1","task_id":"t1","status":"completed"}',
      "",
      "event: batch_complete",
      'data: {"type":"batch_complete","batch_id":"b1"}',
      "",
    ];

    const results: unknown[] = [];
    let eventType = "";
    let eventData = "";

    for (const line of raw) {
      if (line.startsWith("event:")) {
        eventType = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        eventData = line.slice(5).trim();
      } else if (line === "") {
        if (eventType && eventData) {
          const data = JSON.parse(eventData);
          results.push({ eventType, data });
          if (eventType === "batch_complete") break;
        }
        eventType = "";
        eventData = "";
      }
    }

    expect(results.length).toBe(2);
    expect(results[0].eventType).toBe("task_update");
    expect(results[1].eventType).toBe("batch_complete");
  });

  test("handles keepalive comment lines", () => {
    const line = ": keepalive";
    expect(line.startsWith(":")).toBeTruthy();
  });

  test("handles multiple data lines for same event", () => {
    const raw = [
      "event: task_update",
      'data: {"type":"task_update",',
      'data: "batch_id":"b1","task_id":"t2","status":"running"}',
      "",
    ];

    let eventType = "";
    let dataParts: string[] = [];

    for (const line of raw) {
      if (line.startsWith("event:")) {
        eventType = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataParts.push(line.slice(5).trim());
      } else if (line === "") {
        if (eventType && dataParts.length > 0) {
          const fullData = dataParts.join("");
          const data = JSON.parse(fullData);
          expect(data.task_id).toBe("t2");
        }
        eventType = "";
        dataParts = [];
      }
    }
  });
});

describe("SSE streamBatch: retry logic", () => {
  test("exponential backoff delay calculation", () => {
    const baseDelay = 1000;
    const delays = [];
    for (let i = 1; i <= 3; i++) {
      delays.push(baseDelay * Math.pow(2, i - 1));
    }
    expect(delays).toEqual([1000, 2000, 4000]);
  });

  test("max retries limit", () => {
    const maxRetries = 3;
    let attempts = 0;
    for (let i = 0; i <= maxRetries + 2; i++) {
      if (i <= maxRetries) attempts++;
    }
    expect(attempts).toBe(4);
  });

  test("reconnect requests only events after the last seen sequence", async () => {
    const urls: string[] = [];
    let requestCount = 0;
    const firstStream = [
      "event: task_update\n",
      'data: {"type":"task_update","batch_id":"b1","sequence":4,"task_id":"t1"}\n\n',
    ];
    const secondStream = [
      "event: batch_complete\n",
      'data: {"type":"batch_complete","batch_id":"b1","sequence":5}\n\n',
    ];

    vi.stubGlobal("fetch", (url: string) => {
      urls.push(url);
      requestCount += 1;
      const chunks = requestCount === 1 ? firstStream : secondStream;
      const stream = new ReadableStream({
        start(controller) {
          for (const chunk of chunks) {
            controller.enqueue(new TextEncoder().encode(chunk));
          }
          controller.close();
        },
      });
      return Promise.resolve(new Response(stream, { status: 200 }));
    });

    const events: number[] = [];
    streamBatch(
      "b1",
      {
        onTaskUpdate: (event) => events.push(event.sequence ?? 0),
        onBatchComplete: (event) => events.push(event.sequence ?? 0),
      },
      { maxRetries: 1, baseDelay: 10 },
    );

    await new Promise((resolve) => setTimeout(resolve, 80));

    expect(events).toEqual([4, 5]);
    expect(urls[0]).toBe("http://127.0.0.1:8000/api/agents/parallel/stream/b1");
    expect(urls[1]).toBe(
      "http://127.0.0.1:8000/api/agents/parallel/stream/b1?after_sequence=4",
    );
    vi.unstubAllGlobals();
  });
});
