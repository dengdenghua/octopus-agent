/**
 * useInvariants · read-only catalog of constitution rules + their
 * enforcers, sourced from ``GET /api/invariants``.
 */

import { swallow } from "@/core/utils/log";
import { useCallback, useEffect, useState } from "react";

export interface InvariantEnforcer {
  module: string;
  qualname: string;
}

export interface InvariantRule {
  rule_id: string;
  enforcers: InvariantEnforcer[];
}

export interface InvariantsState {
  rules: InvariantRule[];
  totalRules: number;
  totalEnforcers: number;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  rebuild: () => Promise<void>;
}

export interface UseInvariantsOptions {
  baseUrl?: string;
  auto?: boolean;
}

export function useInvariants(
  options: UseInvariantsOptions = {},
): InvariantsState {
  const { baseUrl = "", auto = true } = options;
  const [rules, setRules] = useState<InvariantRule[]>([]);
  const [totalRules, setTotalRules] = useState(0);
  const [totalEnforcers, setTotalEnforcers] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchCatalog = useCallback(
    async (refresh: boolean) => {
      setLoading(true);
      setError(null);
      try {
        const url = `${baseUrl}/api/invariants${refresh ? "/refresh" : ""}`;
        const resp = await fetch(url, {
          method: refresh ? "POST" : "GET",
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const body = await resp.json();
        setRules(Array.isArray(body.rules) ? body.rules : []);
        setTotalRules(Number(body.total_rules ?? 0));
        setTotalEnforcers(Number(body.total_enforcers ?? 0));
      } catch (exc) {
        swallow(exc);
        setError(exc instanceof Error ? exc.message : String(exc));
        setRules([]);
      } finally {
        setLoading(false);
      }
    },
    [baseUrl],
  );

  const refresh = useCallback(() => fetchCatalog(false), [fetchCatalog]);
  const rebuild = useCallback(() => fetchCatalog(true), [fetchCatalog]);

  useEffect(() => {
    if (auto) void refresh();
  }, [auto, refresh]);

  return {
    rules,
    totalRules,
    totalEnforcers,
    loading,
    error,
    refresh,
    rebuild,
  };
}
