// JSON-RPC 2.0 envelope types — wire-level shape mirroring runtime/protocol/envelope.py.
//
// This file is the single source of truth for the realtime protocol on the
// client side. Every other module in core/realtime imports from here.
// Keep field names matching the Python side exactly (camelCase preserved
// across the wire by Pydantic alias_generator settings server-side).

export type JsonRpcId = number | string;

export interface JsonRpcRequest<P = Record<string, unknown>> {
  jsonrpc: "2.0";
  id: JsonRpcId;
  method: string;
  params: P;
}

export interface JsonRpcResponse<R = unknown> {
  jsonrpc: "2.0";
  id: JsonRpcId;
  result?: R;
  error?: JsonRpcError;
}

export interface JsonRpcError {
  code: number;
  message: string;
  data?: unknown;
}

export interface Notification<P = Record<string, unknown>> {
  jsonrpc: "2.0";
  method: string;
  params: P;
}

export type Envelope = JsonRpcRequest | JsonRpcResponse | Notification;

export const JsonRpcErrorCode = {
  PARSE_ERROR: -32700,
  INVALID_REQUEST: -32600,
  METHOD_NOT_FOUND: -32601,
  INVALID_PARAMS: -32602,
  INTERNAL_ERROR: -32603,
  APPROVAL_DENIED: -32000,
  APPROVAL_TIMEOUT: -32001,
  THREAD_NOT_FOUND: -32010,
  TURN_NOT_ACTIVE: -32011,
  UNAUTHORIZED: -32020,
} as const;

export type JsonRpcErrorCode =
  (typeof JsonRpcErrorCode)[keyof typeof JsonRpcErrorCode];

// Type guards. Wire data is untrusted: JSON.parse can return null, a scalar,
// or an array, so these predicates deliberately accept ``unknown`` and fully
// establish the minimum shape promised by their return type.

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isJsonRpcId(value: unknown): value is JsonRpcId {
  return (
    typeof value === "string" ||
    (typeof value === "number" && Number.isFinite(value))
  );
}

function hasBaseEnvelopeShape(
  msg: unknown,
): msg is Record<string, unknown> & { jsonrpc: "2.0" } {
  return isRecord(msg) && msg.jsonrpc === "2.0";
}

function hasParamsObject(
  msg: Record<string, unknown>,
): msg is Record<string, unknown> & { params: Record<string, unknown> } {
  return isRecord(msg.params);
}

function isJsonRpcError(value: unknown): value is JsonRpcError {
  return (
    isRecord(value) &&
    typeof value.code === "number" &&
    Number.isFinite(value.code) &&
    typeof value.message === "string"
  );
}

export function isResponse(msg: unknown): msg is JsonRpcResponse {
  if (!hasBaseEnvelopeShape(msg) || !isJsonRpcId(msg.id) || "method" in msg) {
    return false;
  }
  const hasResult = Object.prototype.hasOwnProperty.call(msg, "result");
  const hasError = Object.prototype.hasOwnProperty.call(msg, "error");
  return hasResult !== hasError && (hasResult || isJsonRpcError(msg.error));
}

export function isRequest(msg: unknown): msg is JsonRpcRequest {
  return (
    hasBaseEnvelopeShape(msg) &&
    isJsonRpcId(msg.id) &&
    typeof msg.method === "string" &&
    msg.method.length > 0 &&
    hasParamsObject(msg)
  );
}

export function isNotification(msg: unknown): msg is Notification {
  return (
    hasBaseEnvelopeShape(msg) &&
    !("id" in msg) &&
    typeof msg.method === "string" &&
    msg.method.length > 0 &&
    hasParamsObject(msg)
  );
}
