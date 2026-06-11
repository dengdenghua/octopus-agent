/**
 * Custom hook for VLM (Vision-Language Model) screen analysis.
 *
 * Wraps the `POST /api/tentacle/devices/:id/analyze` endpoint and
 * exposes `{ state, analyze, clear }` for use in the Mobile page.
 */

import { useCallback, useState } from "react";

import { analyzeDevice, type ScreenAnalysis } from "./api";

// ── Types ──────────────────────────────────────────────

export interface VlmAnalysisState {
  analysis: ScreenAnalysis | null;
  isAnalyzing: boolean;
  error: string | null;
}

// ── Hook ───────────────────────────────────────────────

export function useVlmAnalysis(): {
  state: VlmAnalysisState;
  analyze: (tentacleId: string, task: string) => Promise<void>;
  clear: () => void;
} {
  const [analysis, setAnalysis] = useState<ScreenAnalysis | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const analyze = useCallback(async (tentacleId: string, task: string) => {
    const trimmed = task.trim();
    if (!trimmed) return;
    setIsAnalyzing(true);
    setError(null);
    try {
      const result = await analyzeDevice(tentacleId, trimmed);
      setAnalysis(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setIsAnalyzing(false);
    }
  }, []);

  const clear = useCallback(() => {
    setAnalysis(null);
    setError(null);
  }, []);

  return { state: { analysis, isAnalyzing, error }, analyze, clear };
}
