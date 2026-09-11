import { useQuery } from "@tanstack/react-query";

import { loadModels } from "./api";

export function useModels({ enabled = true }: { enabled?: boolean } = {}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["models"],
    queryFn: () => loadModels(),
    enabled,
    refetchOnWindowFocus: true,
    // Team catalogs can change while settings are closed. Refresh the shared
    // query without issuing a separate request for every mounted picker.
    refetchInterval: 60 * 1000,
    staleTime: 5 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  });
  return { models: data ?? [], isLoading, error };
}
