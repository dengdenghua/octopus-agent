import { getBackendBaseURL } from "@/core/config";
import { authHeaders } from "@/core/auth/api";

export async function reflexFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(authHeaders());
  new Headers(init?.headers).forEach((value, name) => headers.set(name, value));
  const res = await fetch(`${getBackendBaseURL()}${path}`, {
    ...init,
    headers,
  });
  if (!res.ok) {
    throw new Error(
      `Reflex API ${path} failed: ${res.status} ${res.statusText}`,
    );
  }
  return res.json() as Promise<T>;
}
