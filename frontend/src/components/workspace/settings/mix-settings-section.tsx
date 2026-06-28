import { useCallback, useEffect, useState } from "react";
import { Loader2Icon, SaveIcon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useModels } from "@/core/models/hooks";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

const MIX_ID = "octopus-mix";

interface MixConfig {
  proposers: string[];
  aggregator: string;
  n: number;
}

/**
 * Compose the built-in Octopus Mix model: pick the proposer pool + an
 * aggregator. Persists via PUT /api/mix-config (run-time resolution is
 * config → env → default, see openai_gateway/mix.py). Selecting "Octopus
 * Mix" in the model picker then answers via this mixture.
 */
export function MixSettingsSection() {
  const { models } = useModels();
  const [proposers, setProposers] = useState<string[]>([]);
  const [aggregator, setAggregator] = useState("");
  const [n, setN] = useState(3);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Selectable models = everything the picker offers except Mix itself
  // (no recursion) and the "auto" sentinel.
  const candidates = models.filter((m) => m.name !== MIX_ID && m.name !== "auto");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${getBackendBaseURL()}/api/mix-config`, {
          headers: authHeaders(),
        });
        if (!r.ok) return;
        const cfg = (await r.json()) as MixConfig;
        if (cancelled) return;
        setProposers(Array.isArray(cfg.proposers) ? cfg.proposers : []);
        setAggregator(cfg.aggregator || "");
        setN(typeof cfg.n === "number" ? cfg.n : 3);
      } catch {
        /* keep defaults on error */
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleProposer = useCallback((name: string) => {
    setProposers((prev) =>
      prev.includes(name) ? prev.filter((x) => x !== name) : [...prev, name],
    );
  }, []);

  const save = useCallback(async () => {
    setSaving(true);
    try {
      const r = await fetch(`${getBackendBaseURL()}/api/mix-config`, {
        method: "PUT",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({ proposers, aggregator, n }),
      });
      if (!r.ok) throw new Error(`保存失败 (${r.status})`);
      toast.success("Octopus Mix 配置已保存");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }, [proposers, aggregator, n]);

  return (
    <SettingsSection
      title="Octopus Mix · 多模型协同"
      description="选 2+ 个模型作为 proposer(各自独立起草、无工具),再选一个 aggregator 综合出最终答案。聊天里选 “Octopus Mix” 即走此配置;proposer 留空则用默认模型 × 数量。"
    >
      <div className="space-y-4">
        <div>
          <div className="mb-2 text-sm font-medium">Proposers(参与起草的模型)</div>
          {loading ? (
            <Loader2Icon className="size-4 animate-spin text-muted-foreground" />
          ) : candidates.length === 0 ? (
            <div className="text-sm text-muted-foreground">暂无可选模型</div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {candidates.map((m) => {
                const active = proposers.includes(m.name);
                return (
                  <button
                    key={m.name}
                    type="button"
                    onClick={() => toggleProposer(m.name)}
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs transition-colors",
                      active
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border text-muted-foreground hover:border-primary/50",
                    )}
                  >
                    {m.display_name || m.name}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-6">
          <label className="flex items-center gap-2 text-sm">
            Aggregator
            <select
              value={aggregator}
              onChange={(e) => setAggregator(e.target.value)}
              className="rounded-md border border-border bg-background px-2 py-1 text-sm"
            >
              <option value="">默认</option>
              {candidates.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.display_name || m.name}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-2 text-sm">
            无池时数量
            <input
              type="number"
              min={1}
              max={6}
              value={n}
              onChange={(e) =>
                setN(Math.max(1, Math.min(6, Number(e.target.value) || 3)))
              }
              className="w-16 rounded-md border border-border bg-background px-2 py-1 text-sm"
            />
          </label>
        </div>

        <Button onClick={() => void save()} disabled={saving} size="sm" className="gap-1.5">
          {saving ? (
            <Loader2Icon className="size-4 animate-spin" />
          ) : (
            <SaveIcon className="size-4" />
          )}
          保存
        </Button>
      </div>
    </SettingsSection>
  );
}
