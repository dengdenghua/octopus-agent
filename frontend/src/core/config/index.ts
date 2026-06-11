import { swallow } from "@/core/utils/log";
function getBaseOrigin() {
  if (typeof window !== "undefined") {
    return window.location.origin;
  }
  return "http://localhost:3000";
}

const RUNTIME_BACKEND_PARAM = "octopusBackend";

function normalizeBaseURL(value: string) {
  return value.replace(/\/+$/, "");
}

function normalizeBackendBaseURL(value: string | undefined | null) {
  if (!value) {
    return "";
  }
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return "";
    }
    return normalizeBaseURL(url.toString());
  } catch (e) {
    swallow(e);
    return "";
  }
}

function getRuntimeBackendBaseURL() {
  if (typeof window === "undefined") {
    return "";
  }

  try {
    const params = new URLSearchParams(window.location.search);
    const fromURL = params.get(RUNTIME_BACKEND_PARAM);
    if (fromURL) {
      const normalized = normalizeBackendBaseURL(fromURL);
      if (!normalized) {
        return "";
      }
      window.sessionStorage?.setItem(RUNTIME_BACKEND_PARAM, normalized);
      return normalized;
    }
    const fromElectron = normalizeBackendBaseURL(window.octopus?.backendBaseURL);
    if (fromElectron) {
      window.sessionStorage?.setItem(RUNTIME_BACKEND_PARAM, fromElectron);
      return fromElectron;
    }
    if (window.octopus?.isElectron || window.location.protocol === "file:") {
      window.sessionStorage?.removeItem(RUNTIME_BACKEND_PARAM);
      return "";
    }
    return window.sessionStorage?.getItem(RUNTIME_BACKEND_PARAM) || "";
  } catch (e) {
    swallow(e);
    return "";
  }
}

export function getBackendBaseURL() {
  // In dev mode, always use relative paths so requests go through Vite proxy.
  // This prevents CORS issues (e.g. localhost:3001 -> localhost:8001).
  if (import.meta.env.DEV) {
    return "";
  }

  const runtimeBackend = getRuntimeBackendBaseURL();
  if (runtimeBackend) {
    return runtimeBackend;
  }

  const val = import.meta.env.VITE_BACKEND_BASE_URL;
  if (val) {
    try {
      return normalizeBaseURL(new URL(val, getBaseOrigin()).toString());
    } catch {
      console.warn("[config] Invalid BACKEND_BASE_URL:", val);
    }
  }

  // Last-resort Electron fallback for old desktop shells that do not inject a runtime URL.
  if (typeof window !== "undefined" && window.location.protocol === "file:") {
    return "http://127.0.0.1:8000";
  }

  return "";
}

export function getOctopusBaseURL(_isMock?: boolean) {
  if (import.meta.env.DEV) {
    return "/api";
  }

  const runtimeBackend = getRuntimeBackendBaseURL();
  if (runtimeBackend) {
    return `${runtimeBackend}/api`;
  }

  const val = import.meta.env.VITE_OCTOPUS_BASE_URL;
  if (val) {
    try {
      return normalizeBaseURL(new URL(val, getBaseOrigin()).toString());
    } catch {
      console.warn("[config] Invalid OCTOPUS_BASE_URL:", val);
    }
  }

  const backend = getBackendBaseURL();
  if (backend) {
    return `${backend}/api`;
  }

  return "/api";
}

// Public-facing URLs
//
// Canonical GitHub repo URL. Previously hard-coded in several places as the
// placeholder `https://github.com/octopus` (which points at a random account,
// not this project). Centralize here and override via `VITE_GITHUB_URL` in
// deployments that fork to a different URL.
export const GITHUB_URL: string =
  (import.meta.env.VITE_GITHUB_URL as string | undefined) ??
  "https://github.com/octopus-agent/octopus-agent";
