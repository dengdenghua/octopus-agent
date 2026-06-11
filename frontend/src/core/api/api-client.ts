import { OctopusClient } from "./client";
import { getOctopusBaseURL } from "../config";
import { getToken } from "../auth/api";

const _clients = new Map<string, OctopusClient>();

export function getAPIClient(isMock?: boolean): OctopusClient {
  const cacheKey = isMock ? "mock" : "default";
  let client = _clients.get(cacheKey);
  if (!client) {
    client = new OctopusClient({
      apiUrl: getOctopusBaseURL(isMock),
      getToken,
    });
    _clients.set(cacheKey, client);
  }
  return client;
}

// Singleton instance for direct import
export const apiClient = getAPIClient();
