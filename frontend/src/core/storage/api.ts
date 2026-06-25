import { getBackendBaseURL } from "@/core/config";

export type NASMode = "efficiency" | "privacy";

export interface NASManifest {
  service: string;
  version: string;
  role: string;
  capabilities: string[];
}

export interface NASPolicy {
  mode: NASMode;
  allow_cloud_answering: boolean;
  allow_snippet_export: boolean;
  max_exported_snippets: number;
  max_snippet_chars: number;
  redact_file_paths_for_cloud: boolean;
}

export interface NASSource {
  source_id: string;
  path: string;
  display_name: string;
  recursive: boolean;
  include_globs: string[];
  exclude_globs: string[];
  status: "authorized" | "indexing" | "ready" | "error";
  file_count: number;
  chunk_count: number;
  last_indexed_at: string | null;
  created_at: string;
}

export interface NASModel {
  model_id: string;
  role: "embedding" | "reranker" | "ocr" | "vision" | "answer";
  display_name: string;
  provider: string;
  status: "not_configured" | "available" | "loading" | "running" | "error";
  endpoint: string | null;
  context_tokens: number | null;
  embedding_dimensions: number | null;
  quantization: string | null;
  notes: string | null;
}

export interface NASIndexJob {
  job_id: string;
  source_ids: string[];
  status: "pending" | "running" | "complete" | "failed";
  full_rescan: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  message: string | null;
}

export interface NASSearchHit {
  chunk_id: string;
  source_id: string;
  path: string;
  title: string;
  snippet: string;
  score: number;
  citation: Record<string, unknown>;
}

export interface NASSearchResponse {
  query: string;
  mode: NASMode;
  hits: NASSearchHit[];
  message: string | null;
}

export interface NASAnswerResponse {
  answer: string;
  mode: NASMode;
  citations: NASSearchHit[];
  cloud_used: boolean;
  message: string;
}

export interface NASServiceStartResponse {
  ok: boolean;
  status: "started" | "already_running" | "not_found" | "error" | string;
  base_url: string;
  auth_token?: string | null;
}

const DEFAULT_STORAGE_URL = "http://127.0.0.1:8767";
const STORAGE_KEY = "octopus.storage.base-url";
const LEGACY_STORAGE_KEY = "octopus.nas.base-url";
const STORAGE_TOKEN_KEY = "octopus.storage.auth-token";

function normalizeBaseURL(value: string | null | undefined): string {
  if (!value) return DEFAULT_STORAGE_URL;
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return DEFAULT_STORAGE_URL;
    }
    return url.toString().replace(/\/+$/, "");
  } catch {
    return DEFAULT_STORAGE_URL;
  }
}

export function getNASBaseURL(): string {
  const fromEnv =
    (import.meta.env.VITE_STORAGE_BASE_URL as string | undefined) ??
    (import.meta.env.VITE_NAS_BASE_URL as string | undefined);
  if (fromEnv) return normalizeBaseURL(fromEnv);
  if (typeof window === "undefined") return DEFAULT_STORAGE_URL;
  return normalizeBaseURL(
    window.localStorage.getItem(STORAGE_KEY) ??
      window.localStorage.getItem(LEGACY_STORAGE_KEY),
  );
}

export function setNASBaseURL(value: string): string {
  const normalized = normalizeBaseURL(value);
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, normalized);
  }
  return normalized;
}

export function setNASAuthToken(value: string | null | undefined): void {
  if (typeof window === "undefined" || !value) return;
  window.sessionStorage.setItem(STORAGE_TOKEN_KEY, value);
}

function getNASAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = window.sessionStorage.getItem(STORAGE_TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getNASBaseURL()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...getNASAuthHeaders(),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(
      `NAS ${path} failed: ${response.status}${text ? ` - ${text}` : ""}`,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function startNASService(): Promise<NASServiceStartResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/local-brain/storage/start`,
    { method: "POST" },
  );
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(
      `Storage start failed: ${response.status}${text ? ` - ${text}` : ""}`,
    );
  }
  const body = (await response.json()) as NASServiceStartResponse;
  setNASAuthToken(body.auth_token);
  return body;
}

export function getNASManifest(): Promise<NASManifest> {
  return request("/v1/manifest");
}

export function getNASPolicy(): Promise<NASPolicy> {
  return request("/v1/policy");
}

export function listNASModels(): Promise<NASModel[]> {
  return request("/v1/models");
}

export function updateNASPolicy(policy: NASPolicy): Promise<NASPolicy> {
  return request("/v1/policy", {
    method: "PUT",
    body: JSON.stringify(policy),
  });
}

export function listNASSources(): Promise<NASSource[]> {
  return request("/v1/sources");
}

export function createNASSource(path: string): Promise<NASSource> {
  return request("/v1/sources", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export function deleteNASSource(sourceId: string): Promise<void> {
  return request(`/v1/sources/${encodeURIComponent(sourceId)}`, {
    method: "DELETE",
  });
}

export function createNASIndexJob(
  sourceIds: string[] = [],
): Promise<NASIndexJob> {
  return request("/v1/index/jobs", {
    method: "POST",
    body: JSON.stringify({ source_ids: sourceIds, full_rescan: false }),
  });
}

export function searchNAS(query: string): Promise<NASSearchResponse> {
  return request("/v1/search", {
    method: "POST",
    body: JSON.stringify({ query, top_k: 8, source_ids: [] }),
  });
}

export function answerNAS(query: string): Promise<NASAnswerResponse> {
  return request("/v1/answer", {
    method: "POST",
    body: JSON.stringify({ query, top_k: 8, source_ids: [] }),
  });
}
