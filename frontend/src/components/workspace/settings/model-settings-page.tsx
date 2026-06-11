
import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  EyeIcon,
  EyeOffIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  WifiIcon,
  XCircleIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { swallow } from "@/core/utils/log";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { useAuth } from "@/providers/AuthProvider";
import { getLocalSettings, saveLocalSettings } from "@/core/settings/local";
import { registerPageAgentCapability } from "@/core/page-agent-bridge";

import { SettingsSection } from "./settings-section";

// ── Provider presets ────────────────────────────────────────────
//
// Each preset auto-fills base URL + protocol when selected. Optional
// Implementation note.
// API key input · ``suggestedModels`` shows a small hint below the
// Model ID field so users don't have to remember model names.
//
// Compatibility note · all entries work with Octopus's native
// tool_use pipeline as long as the backing model supports function
// calling (see docs/custom-models.md for per-provider gotchas).
interface ProviderPreset {
  label: string;
  value: string;
  baseUrl: string;
  protocol: "openai" | "anthropic";
  consoleUrl?: string;
  suggestedModels?: string[];
}

const PROVIDERS: readonly ProviderPreset[] = [
  // Implementation note.
  {
    label: "OpenAI",
    value: "openai",
    baseUrl: "https://api.openai.com/v1",
    protocol: "openai",
    consoleUrl: "https://platform.openai.com/api-keys",
    suggestedModels: ["gpt-4o-mini", "gpt-4o", "o1", "o3-mini"],
  },
  {
    label: "Anthropic (Claude)",
    value: "anthropic",
    baseUrl: "https://api.anthropic.com/v1",
    protocol: "anthropic",
    consoleUrl: "https://console.anthropic.com/",
    suggestedModels: [
      "claude-sonnet-4-6-20250514",
      "claude-haiku-4-5-20251001",
      "claude-opus-4-7-20250805",
    ],
  },
  {
    label: "Google Gemini",
    value: "gemini",
    baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
    protocol: "openai",
    consoleUrl: "https://aistudio.google.com/apikey",
    suggestedModels: ["gemini-2.5-flash", "gemini-2.5-pro"],
  },
  {
    label: "xAI (Grok)",
    value: "xai",
    baseUrl: "https://api.x.ai/v1",
    protocol: "openai",
    consoleUrl: "https://console.x.ai/",
    suggestedModels: ["grok-4-mini", "grok-4"],
  },
  {
    label: "DeepSeek",
    value: "deepseek",
    baseUrl: "https://api.deepseek.com/v1",
    protocol: "openai",
    consoleUrl: "https://platform.deepseek.com/",
    suggestedModels: ["deepseek-chat", "deepseek-reasoner"],
  },

  // Implementation note.
  {
    label: "Moonshot · Kimi",
    value: "kimi",
    baseUrl: "https://api.moonshot.cn/v1",
    protocol: "openai",
    consoleUrl: "https://platform.moonshot.cn/console/api-keys",
    suggestedModels: [
      "kimi-k2-0711-preview",
      "moonshot-v1-128k",
      "moonshot-v1-32k",
    ],
  },
  {
    label: "智谱 · GLM",
    value: "zhipu",
    baseUrl: "https://open.bigmodel.cn/api/paas/v4",
    protocol: "openai",
    consoleUrl: "https://bigmodel.cn/usercenter/apikeys",
    suggestedModels: ["glm-4.6", "glm-4-flash", "glm-4-plus", "glm-4v-plus"],
  },
  {
    label: "MiniMax",
    value: "minimax",
    baseUrl: "https://api.minimaxi.com/v1",
    protocol: "openai",
    consoleUrl:
      "https://platform.minimaxi.com/user-center/basic-information/interface-key",
    suggestedModels: ["MiniMax-M2", "abab7-chat-preview"],
  },
  {
    label: "阿里云 · 通义千问 (Qwen)",
    value: "aliyun",
    // NB · must be ``compatible-mode`` · DashScope native proto
    // does not support the standard ``tools`` field shape.
    baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    protocol: "openai",
    consoleUrl: "https://bailian.console.aliyun.com/?tab=model#/api-key",
    suggestedModels: [
      "qwen-max-latest",
      "qwen-plus",
      "qwen-turbo",
      "qwen3-max",
      "qvq-max-latest",
    ],
  },
  {
    label: "腾讯云 · 混元",
    value: "tencent",
    baseUrl: "https://api.hunyuan.cloud.tencent.com/v1",
    protocol: "openai",
    consoleUrl: "https://console.cloud.tencent.com/hunyuan/api-key",
    suggestedModels: [
      "hunyuan-turbos-latest",
      "hunyuan-large",
      "hunyuan-lite",
    ],
  },
  {
    label: "火山 · 豆包 (Ark)",
    value: "volcengine",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    protocol: "openai",
    consoleUrl: "https://console.volcengine.com/ark",
    // Implementation note.
    // Implementation note.
    suggestedModels: [
      "doubao-pro-256k",
      "doubao-1-5-pro-256k",
      "doubao-pro-32k",
    ],
  },

  // Implementation note.
  {
    label: "Ollama (local)",
    value: "ollama",
    baseUrl: "http://localhost:11434/v1",
    protocol: "openai",
    consoleUrl: "https://ollama.com",
    suggestedModels: [
      "llama3.3:70b",
      "qwen3:7b",
      "qwen3-coder:32b",
      "deepseek-r1:7b",
    ],
  },
  {
    label: "LM Studio (local)",
    value: "lmstudio",
    baseUrl: "http://localhost:1234/v1",
    protocol: "openai",
  },
  {
    label: "OpenRouter (200+ models)",
    value: "openrouter",
    baseUrl: "https://openrouter.ai/api/v1",
    protocol: "openai",
    consoleUrl: "https://openrouter.ai/keys",
  },
  {
    label: "Agnes AI (gateway)",
    value: "agnes",
    baseUrl: "https://apihub.agnes-ai.com/v1",
    protocol: "openai",
    consoleUrl: "https://agnes-ai.com/dashboard",
    suggestedModels: [
      "agnes-2.0-flash",
      "agnes-1.5-flash",
      "agnes-image-2.1-flash",
      "agnes-image-2.0-flash",
      "agnes-video-v2.0",
    ],
  },
  { label: "Custom", value: "custom", baseUrl: "", protocol: "openai" },
] as const;

const PROTOCOLS = [
  { label: "OpenAI", value: "openai" },
  { label: "Anthropic", value: "anthropic" },
] as const;

type TestStatus = "idle" | "testing" | "success" | "fail";

interface ModelConfig {
  id?: string;
  name: string;
  /** Open-ended list of upstream model ids this entry can dispatch
   *  to. Index 0 is the picker default, index -1 is the strongest
   *  slot for Auto mode's performance verdict. Backend stores this
   *  as ``models`` on the custom-model entry. */
  models: string[];
  display_name?: string | null;
  description?: string | null;
  provider?: string | null;
  supports_thinking?: boolean;
  supports_vision?: boolean;
  base_url?: string;
  has_api_key?: boolean;
  max_tokens?: number | null;
}

// Parse `Header-Name: value` lines into a dict. Blank lines and lines
// lacking a colon are ignored so users can leave helper comments.
function parseHeadersText(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const idx = line.indexOf(":");
    if (idx <= 0) continue;
    const k = line.slice(0, idx).trim();
    const v = line.slice(idx + 1).trim();
    if (k && v) out[k] = v;
  }
  return out;
}

// ── Main page ──────────────────────────────────────────────────
export default function ModelSettingsPage() {
  const { t } = useI18n();
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editingModel, setEditingModel] = useState<string | null>(null);

  // Gateway connection state
  const [gatewayStatus, setGatewayStatus] = useState<"connected" | "disconnected" | "checking">("checking");

  // List / CRUD all target the new hot-register dispatcher endpoints
  // (/api/config/custom-models/*). The legacy /api/models was the
  // OpenAI-compat gateway's *skills-as-models* listing and had no
  // writable CRUD on this backend — writing to it was silently no-op.
  const fetchModels = useCallback(async () => {
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/config/custom-models`, {
        headers: authHeaders(),
      });
      if (!res.ok) {
        throw new Error(`Failed to fetch models: ${res.status}`);
      }
      const data = await res.json();
      const list = data.models || [];
      setModels(list);
    } catch (error) {
      console.error(error);
      toast.error(t.modelSettings.loadFailed);
    } finally { setLoading(false); }
  }, []);

  const checkGateway = useCallback(async () => {
    setGatewayStatus("checking");
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/config/custom-models`, {
        headers: authHeaders(),
        signal: AbortSignal.timeout(5000),
      });
      setGatewayStatus(res.ok ? "connected" : "disconnected");
    } catch (e) {
      swallow(e);
      setGatewayStatus("disconnected");
    }
  }, []);

  useEffect(() => { fetchModels(); checkGateway(); }, [fetchModels, checkGateway]);

  const handleSetDefault = async (name: string) => {
    try {
      // Implementation note.
      const settings = getLocalSettings();
      saveLocalSettings({
        ...settings,
        context: {
          ...settings.context,
          model_name: name,
        },
      });
      toast.success(t.modelSettings.setDefaultSuccess);
      await fetchModels();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t.modelSettings.setDefaultFailed);
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(t.modelSettings.deleteConfirm(name))) return;
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/config/custom-models/${encodeURIComponent(name)}`, {
        method: "DELETE",
        headers: authHeaders(),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Delete failed: ${res.status}`);
      }
      toast.success(t.modelSettings.deleteSuccess);
      await fetchModels();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t.modelSettings.deleteFailed);
    }
  };

  const handleReconnect = () => { checkGateway(); };

  const handleDiagnose = async () => {
    const issues: string[] = [];
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/config/custom-models`, {
        headers: authHeaders(),
        signal: AbortSignal.timeout(5000),
      });
      if (!res.ok) issues.push(t.modelSettings.gatewayReturned(res.status));
    } catch (e) { swallow(e); issues.push(t.modelSettings.cannotReachGateway); }

    if (issues.length === 0) {
      toast.success(t.modelSettings.diagnoseHealthy);
    } else {
      toast.error(
        t.modelSettings.diagnoseIssues(issues.map((i) => `• ${i}`).join(" ")),
      );
    }
  };

  const { isGuest } = useAuth();
  
  // Implementation note.
  const defaultModelName = getLocalSettings().context.model_name;

  useEffect(() => {
    const unregisters = [
      registerPageAgentCapability({
        id: "models.custom.list",
        label: "List custom models",
        description: "Return current custom model summaries and gateway status.",
        risk: "low",
        riskReasons: [],
        requiresConfirmation: false,
        run: () => ({
          gatewayStatus,
          defaultModelName,
          models: models.map((model) => ({
            name: model.name,
            display_name: model.display_name,
            provider: model.provider,
            base_url: model.base_url,
            models: model.models,
            supports_thinking: model.supports_thinking,
            supports_vision: model.supports_vision,
            isDefault: model.name === defaultModelName,
          })),
        }),
      }),
      registerPageAgentCapability({
        id: "models.custom.openAdd",
        label: "Open add custom model form",
        description: "Open the custom model creation form.",
        risk: "low",
        riskReasons: [],
        requiresConfirmation: false,
        run: () => {
          setEditingModel(null);
          setShowAdd(true);
          return { opened: true };
        },
      }),
      registerPageAgentCapability({
        id: "models.custom.diagnoseGateway",
        label: "Diagnose custom model gateway",
        description: "Check whether the custom model backend API is reachable.",
        risk: "low",
        riskReasons: [],
        requiresConfirmation: false,
        run: async () => {
          await checkGateway();
          return { requested: true };
        },
      }),
      registerPageAgentCapability({
        id: "models.custom.testExisting",
        label: "Test existing custom model",
        description: "Run the backend diagnostic for an existing custom model.",
        risk: "low",
        riskReasons: [],
        requiresConfirmation: false,
        inputSchema: {
          type: "object",
          required: ["name"],
          properties: {
            name: { type: "string" },
          },
        },
        run: async (input) => {
          const name = String(input?.name || "").trim();
          if (!name) throw new Error("name is required");
          const started = performance.now();
          const res = await fetch(`${getBackendBaseURL()}/api/config/custom-models/test`, {
            method: "POST",
            headers: jsonAuthHeaders(),
            body: JSON.stringify({ id: name }),
            signal: AbortSignal.timeout(8000),
          });
          const data = await res.json().catch(() => ({}));
          return {
            ok: res.ok && data.ok !== false,
            status: res.status,
            latencyMs: Math.round(performance.now() - started),
            ...data,
          };
        },
      }),
      registerPageAgentCapability({
        id: "models.custom.setDefault",
        label: "Set default custom model",
        description: "Set the local default model by custom model name.",
        risk: "medium",
        riskReasons: ["save"],
        requiresConfirmation: false,
        inputSchema: {
          type: "object",
          required: ["name"],
          properties: {
            name: { type: "string" },
          },
        },
        run: async (input) => {
          const name = String(input?.name || "").trim();
          if (!name) throw new Error("name is required");
          if (!models.some((model) => model.name === name)) {
            throw new Error(`custom model not found: ${name}`);
          }
          const settings = getLocalSettings();
          saveLocalSettings({
            ...settings,
            context: {
              ...settings.context,
              model_name: name,
            },
          });
          await fetchModels();
          return { defaultModelName: name };
        },
      }),
      registerPageAgentCapability({
        id: "models.custom.delete",
        label: "Delete custom model",
        description: "Delete a custom model configuration by name.",
        risk: "high",
        riskReasons: ["delete"],
        requiresConfirmation: true,
        inputSchema: {
          type: "object",
          required: ["name"],
          properties: {
            name: { type: "string" },
          },
        },
        run: async (input) => {
          const name = String(input?.name || "").trim();
          if (!name) throw new Error("name is required");
          if (!models.some((model) => model.name === name)) {
            throw new Error(`custom model not found: ${name}`);
          }
          const res = await fetch(`${getBackendBaseURL()}/api/config/custom-models/${encodeURIComponent(name)}`, {
            method: "DELETE",
            headers: authHeaders(),
          });
          if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.detail || `Delete failed: ${res.status}`);
          }
          await fetchModels();
          return { deleted: name };
        },
      }),
    ];
    return () => {
      unregisters.forEach((unregister) => unregister());
    };
  }, [checkGateway, defaultModelName, fetchModels, gatewayStatus, models]);

  return (
    <div className="space-y-8">
      {/* Official models */}
      {!isGuest && <OfficialModelsSection />}

      {/* ── Models Section ── */}
      <SettingsSection
        title={
          <div className="flex items-center justify-between w-full">
            <span>{t.modelSettings.customModels}</span>
            {!showAdd && !editingModel && (
              <Button variant="outline" size="sm" onClick={() => setShowAdd(true)}>
                <PlusIcon className="mr-1 h-3 w-3" /> {t.modelSettings.addCustomModel}
              </Button>
            )}
          </div>
        }
      >
        {loading ? (
          <div className="text-muted-foreground text-sm">{t.common.loading}</div>
        ) : (
          <div className="flex w-full flex-col">
            {/* Model list */}
            <div className="rounded-lg border border-border divide-y divide-border">
              {models.map((m) => {
                const list = Array.isArray(m.models) ? m.models : [];
                return (
                  <div
                    key={m.name}
                    className="flex items-center justify-between gap-4 px-5 py-4"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <div className="truncate text-sm font-medium">
                          {m.display_name || m.name}
                        </div>
                        <span
                          className="shrink-0 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-medium text-slate-600 dark:border-slate-500/40 dark:bg-slate-500/10 dark:text-slate-400"
                          title={t.modelSettings.modelList.hint}
                        >
                          {list.length} {list.length === 1 ? "model" : "models"}
                        </span>
                      </div>
                      <div className="mt-0.5 truncate text-xs text-muted-foreground">
                        {m.name}
                      </div>
                      {list.length > 0 && (
                        <ul className="mt-1.5 space-y-0.5 font-mono text-[11px] text-foreground/80">
                          {list.map((id, idx) => (
                            <li
                              key={`${m.name}:${idx}:${id}`}
                              className="flex items-center gap-2"
                            >
                              <span className="w-4 shrink-0 text-right text-muted-foreground/60 tabular-nums">
                                {idx === 0 ? "★" : idx === list.length - 1 ? "▴" : "·"}
                              </span>
                              <code className="truncate rounded bg-muted/60 px-1.5 py-0.5">
                                {id}
                              </code>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      {defaultModelName === m.name ? (
                        <span className="inline-flex items-center rounded-lg bg-green-100 px-3 py-1 text-xs font-medium text-green-700 dark:bg-green-500/20 dark:text-green-400">
                          {t.modelSettings.systemDefault}
                        </span>
                      ) : (
                        <button
                          className="text-xs font-medium text-muted-foreground hover:text-foreground"
                          onClick={() => handleSetDefault(m.name)}
                        >
                          {t.modelSettings.setAsDefault}
                        </button>
                      )}
                      <button
                        className="text-xs font-medium text-orange-500 hover:text-orange-600"
                        onClick={() => setEditingModel(editingModel === m.name ? null : m.name)}
                      >
                        {t.common.edit}
                      </button>
                      <button
                        className="text-xs font-medium text-orange-500 hover:text-orange-600"
                        onClick={() => handleDelete(m.name)}
                      >
                        {t.common.delete}
                      </button>
                    </div>
                  </div>
                );
              })}
              {models.length === 0 && (
                <div className="px-5 py-8 text-center text-sm text-muted-foreground">
                  {t.modelSettings.emptyCustomModels}
                </div>
              )}
            </div>

            {/* Edit form (inline under the list) */}
            {editingModel && (
              <div className="mt-4">
                <EditModelForm
                  modelName={editingModel}
                  onCancel={() => setEditingModel(null)}
                  onSaved={() => { setEditingModel(null); fetchModels(); }}
                />
              </div>
            )}

            {/* Add form */}
            {showAdd && (
              <div className="mt-4">
                <AddModelForm
                  onCancel={() => setShowAdd(false)}
                  onSaved={() => { setShowAdd(false); fetchModels(); }}
                />
              </div>
            )}
          </div>
        )}
      </SettingsSection>

      {/* ── Local-model one-click import ──
          Sits between the custom-models list and the gateway config
          because it's the lowest-friction path *into* the
          custom-models list — a successful import re-runs
          ``fetchModels`` via ``onImported`` so the new row appears
          in the section above without a manual refresh. */}
      <LocalModelsSection onImported={fetchModels} />

      {/* ── Gateway Connection Section ── */}
      <SettingsSection title={t.modelSettings.gatewayUrl}>
        <div className="space-y-4">
          {/* Status bar */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium">{t.modelSettings.gatewayUrl}</span>
              {gatewayStatus === "connected" && (
                <span className="inline-flex items-center rounded-lg bg-green-100 dark:bg-green-500/20 px-3 py-1 text-xs font-medium text-green-700 dark:text-green-400">
                  {t.modelSettings.connected}
                </span>
              )}
              {gatewayStatus === "disconnected" && (
                <span className="inline-flex items-center rounded-lg bg-red-100 dark:bg-red-500/20 px-3 py-1 text-xs font-medium text-red-700 dark:text-red-400">
                  {t.modelSettings.disconnected}
                </span>
              )}
              {gatewayStatus === "checking" && (
                <span className="inline-flex items-center gap-1 rounded-lg bg-blue-100 dark:bg-blue-500/20 px-3 py-1 text-xs font-medium text-blue-700 dark:text-blue-400">
                  <Loader2Icon className="h-3 w-3 animate-spin" /> {t.common.loading}
                </span>
              )}
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={handleReconnect}>
                <RefreshCwIcon className="mr-1 h-3 w-3" /> {t.modelSettings.reconnect}
              </Button>
              <Button variant="outline" size="sm" onClick={handleDiagnose}>
                <SearchIcon className="mr-1 h-3 w-3" /> {t.modelSettings.diagnose}
              </Button>
            </div>
          </div>

          {/* Read-only backend target */}
          <div className="rounded-lg border border-border p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium">{t.modelSettings.port}</div>
                <div className="text-xs text-muted-foreground mt-1">
                  {t.modelSettings.backendUrlHint}
                </div>
              </div>
              <Input
                className="w-56 text-right"
                value={getBackendBaseURL() || "same-origin proxy"}
                readOnly
              />
            </div>
          </div>

          {/* Troubleshooting tips */}
          <div className="rounded-lg bg-blue-50 dark:bg-blue-500/10 border border-blue-200 dark:border-blue-500/20 p-4 text-sm">
            <div className="font-medium text-blue-800 dark:text-blue-300 mb-2">
              {t.modelSettings.connectionHelp}
            </div>
            <ul className="space-y-1 text-blue-700 dark:text-blue-400 text-xs">
              <li>{t.modelSettings.connectionHelpReconnect}</li>
              <li>{t.modelSettings.setDefaultHint}</li>
              <li>{t.modelSettings.connectionHelpDiagnose}</li>
            </ul>
          </div>
        </div>
      </SettingsSection>
    </div>
  );
}

// Official models from the account-backed gateway.
//
// Reads from the OpenAI-compat shim (/api/molili/openai/v1/models)
// when the official gateway is enabled. When the bridge is disabled
// (503) or the user hasn't linked their account yet (404), hide the
// section entirely: there's nothing
// for them to do here, and the empty card would be confusing.
//
interface UpstreamModel {
  id: string;
  display_name?: string | null;
  owned_by?: string | null;
  multiplier?: string | null;
  recommended?: boolean;
}

function OfficialModelsSection() {
  const { t } = useI18n();
  const [models, setModels] = useState<UpstreamModel[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [unavailableReason, setUnavailableReason] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(
          `${getBackendBaseURL()}/api/molili/openai/v1/models`,
          { headers: authHeaders() },
        );
        if (cancelled) return;
        if (r.status === 404) {
          setUnavailableReason(t.modelSettings.moliliNotLinked);
          setModels([]);
          return;
        }
        if (r.status === 503) {
          setUnavailableReason(t.modelSettings.moliliNotEnabled);
          setModels([]);
          return;
        }
        if (!r.ok) {
          setUnavailableReason(`upstream ${r.status}`);
          setModels([]);
          return;
        }
        const j = await r.json();
        setModels(Array.isArray(j?.data) ? j.data : []);
      } catch (err) {
        swallow(err);
        if (!cancelled) {
          setUnavailableReason(err instanceof Error ? err.message : String(err));
          setModels([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <SettingsSection title={t.modelSettings.officialModels}>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2Icon className="size-4 animate-spin" /> {t.common.loading}
        </div>
      </SettingsSection>
    );
  }

  // Hide the whole section when the bridge isn't usable — the rest of
  // the settings page (custom models + gateway) is fully self-contained.
  if (unavailableReason) {
    return null;
  }

  // Build rows from the backend catalog. Skip the synthetic "auto"
  // / "molili" pseudo-model the gateway advertises.
  const rows = (models ?? [])
    .filter((m) => !/^(molili|auto)$/i.test(m.id))
    .map((m) => ({ upstream: m }));

  return (
    <SettingsSection title={t.modelSettings.officialModels}>
      <div className="rounded-lg border border-border divide-y divide-border">
        {rows.length === 0 && (
          <div className="px-5 py-8 text-center text-sm text-muted-foreground">
            {t.modelSettings.noOfficialModels}
          </div>
        )}
        {rows.map(({ upstream }) => (
          <div
            key={upstream.id}
            className="flex items-center justify-between px-5 py-4"
          >
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium">
                  {upstream.display_name || upstream.id}
                </span>
                {upstream.recommended && (
                  <span className="rounded border border-emerald-500/40 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                    {t.modelPicker.recommended}
                  </span>
                )}
              </div>
              <div className="text-xs text-muted-foreground">
                {upstream.id}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className="rounded-lg bg-muted px-2 py-0.5 text-xs tabular-nums text-muted-foreground">
                {upstream.multiplier ?? "1.0x"}
              </span>
              <span className="text-[10px] text-muted-foreground">
                {t.modelSettings.moliliHosted}
              </span>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        {t.modelSettings.officialModelsHint}
      </p>
    </SettingsSection>
  );
}

// ── Edit model form ────────────────────────────────────────────
//
// On mount, fetches the model's full config via the /edit endpoint so
// every field is round-tripped from config.yaml instead of showing blank
// placeholders. The API key itself is never returned in cleartext — if
// it was stored as `$ENV_VAR` the form displays the variable name (safe)
// and the user can leave the field blank to keep it; typing a new value
// overrides. Literal keys are shown as a "•••" placeholder.
function EditModelForm({ modelName, onCancel, onSaved }: { modelName: string; onCancel: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const [displayName, setDisplayName] = useState("");
  // Open-ended list of upstream model ids this entry can dispatch
  // to. Index 0 is the picker default, index -1 is the strongest
  // slot for Auto mode's performance verdict. Mirrors the
  // ``models`` field on the custom-model entry.
  const [models, setModels] = useState<string[]>([""]);
  const [apiKey, setApiKey] = useState("");
  const [apiKeyPlaceholder, setApiKeyPlaceholder] = useState(t.modelSettings.apiKeyPlaceholder);
  const [baseUrl, setBaseUrl] = useState("");
  const [thinking, setThinking] = useState(false);
  const [vision, setVision] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [headersText, setHeadersText] = useState("");
  const [showHeaders, setShowHeaders] = useState(false);
  const [loading, setLoading] = useState(true);
  // Provider is derived from the Base URL — no manual entry. Anthropic
  // base URLs need their own protocol; everything else speaks
  // OpenAI-compatible. The chip surfaces what the runtime will actually
  // do with this entry, so the user can spot a wrong base URL early.
  const detectedProvider = (() => {
    const u = (baseUrl || "").toLowerCase();
    if (!u) return "—";
    if (u.includes("anthropic.com")) return "anthropic";
    if (u.includes("googleapis.com") || u.includes("generativelanguage")) return "gemini";
    if (u.includes("ollama") || /:11434(\b|\/)/.test(u)) return "ollama";
    return "openai";
  })();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [testStatus, setTestStatus] = useState<TestStatus>("idle");
  const [testMessage, setTestMessage] = useState("");
  const [testLatency, setTestLatency] = useState<number | null>(null);

  // One-shot config fetch. Empty deps — the component remounts when a
  // different model is selected (key={modelName} at the call site).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Backend doesn't return api_key (stays on server). List
        // endpoint gives us everything else; we look up this model id.
        const res = await fetch(
          `${getBackendBaseURL()}/api/config/custom-models`,
          { headers: authHeaders() },
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const list = (await res.json()).models as Array<Record<string, unknown>>;
        const d = list.find((m) => m.id === modelName) ?? {};
        if (cancelled) return;
        setDisplayName((d.display_name as string) || (d.name as string) || "");
        const rawModels = Array.isArray(d.models) ? (d.models as unknown[]) : [];
        const normalised = rawModels
          .map((m) => (typeof m === "string" ? m.trim() : ""))
          .filter((m) => m.length > 0);
        setModels(normalised.length > 0 ? normalised : [""]);
        setBaseUrl((d.base_url as string) || "");
        setThinking(!!d.supports_thinking);
        setVision(!!d.supports_vision);
        setHeadersText("");
        setShowHeaders(false);
        setApiKeyPlaceholder(
          d.has_api_key
            ? `••• · ${t.modelSettings.keepApiKeyHint}`
            : t.modelSettings.apiKeyPlaceholder,
        );
      } catch (e) {
        swallow(e);
        if (!cancelled)
          setError(e instanceof Error ? e.message : t.modelSettings.networkError);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [modelName, t.modelSettings.apiKeyPlaceholder, t.modelSettings.keepApiKeyHint, t.modelSettings.networkError]);

  const handleModelChange = (idx: number, value: string) => {
    setModels((prev) => prev.map((m, i) => (i === idx ? value : m)));
  };
  const handleModelAdd = () => {
    setModels((prev) => [...prev, ""]);
  };
  const handleModelRemove = (idx: number) => {
    setModels((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== idx)));
  };

  const handleSave = async () => {
    setSaving(true);
    setError("");
    // Drop empty rows before persisting so the backend never sees
    // a trailing blank in the models list. The UI still shows the
    // last row even if it's empty, so the user can keep typing.
    const cleanedModels = models.map((m) => m.trim()).filter((m) => m.length > 0);
    if (cleanedModels.length === 0) {
      setError(t.modelSettings.modelList.empty);
      setSaving(false);
      return;
    }
    const body: Record<string, unknown> = {};
    // Auto-inject display_name from the entry id — the field used to
    // be user-editable but UX feedback was that it duplicated the
    // entry id 99% of the time. Setting it explicitly keeps the
    // backend contract intact (display_name is required-ish: many
    // older entries used it as the picker label) without making the
    // user fill in another field.
    body.display_name = displayName || modelName;
    if (apiKey) body.api_key = apiKey;
    if (baseUrl) body.base_url = baseUrl;
    body.supports_thinking = thinking;
    body.supports_vision = vision;
    // Always send the full models list — backend normalises and
    // persists verbatim, replacing any prior binding.
    body.models = cleanedModels;
    // Always send default_headers so clearing the textarea clears the
    // persisted yaml entry. The backend treats {} as "remove the key".
    body.default_headers = parseHeadersText(headersText);

    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/config/custom-models/${encodeURIComponent(modelName)}`,
        {
          method: "PUT",
          headers: jsonAuthHeaders(),
          body: JSON.stringify(body),
        },
      );
      if (!res.ok) {
        const data = await res.json();
        setError(data.detail || t.modelSettings.updateFailed);
        return;
      }
      toast.success(t.modelSettings.saveSuccess);
      onSaved();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t.modelSettings.networkError);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    if (!baseUrl) {
      setTestStatus("fail");
      setTestMessage(t.modelSettings.fillRequiredBeforeTest);
      return;
    }
    setTestStatus("testing");
    setTestMessage("");
    setTestLatency(null);
    const started = performance.now();
    // Test against the first non-empty model id (the picker default).
    const firstModel = models.map((m) => m.trim()).find((m) => m.length > 0) || modelName;
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/config/custom-models/test`, {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({
          id: modelName,
          base_url: baseUrl,
          api_key: apiKey || undefined,
          model: firstModel,
          provider: baseUrl.includes("anthropic.com") ? "anthropic" : undefined,
          default_headers: parseHeadersText(headersText),
        }),
        signal: AbortSignal.timeout(8000),
      });
      const latency = Math.round(performance.now() - started);
      setTestLatency(latency);
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        setTestStatus("fail");
        setTestMessage(data.error || `HTTP ${res.status}`);
      } else {
        setTestStatus("success");
        setTestMessage(data.message || t.modelSettings.saveSuccess);
      }
    } catch (e: unknown) {
      setTestStatus("fail");
      setTestMessage(e instanceof Error ? e.message : t.modelSettings.networkError);
    }
  };

  return (
    <div className="rounded-lg border border-border p-4 space-y-3">
      <div className="text-sm font-medium">{t.modelSettings.editModelTitle(modelName)}</div>
      {loading ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2Icon className="size-3.5 animate-spin" />
          {t.common.loading}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">{t.modelSettings.providerLabel}</label>
              <div className="flex h-9 items-center rounded-md border border-input bg-muted/40 px-3 text-sm">
                <span className="font-mono">{detectedProvider}</span>
                <span className="ml-2 text-[10px] text-muted-foreground/70">
                  {t.modelSettings.providerAutoHint}
                </span>
              </div>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">{t.modelSettings.keepApiKeyHint}</label>
              <div className="relative">
                <Input className="pr-10" type={showKey ? "text" : "password"} placeholder={apiKeyPlaceholder} value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
                <button type="button" className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" onClick={() => setShowKey(!showKey)}>
                  {showKey ? <EyeOffIcon className="size-4" /> : <EyeIcon className="size-4" />}
                </button>
              </div>
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">{t.modelSettings.baseUrlLabel}</label>
            <Input placeholder={t.modelSettings.baseUrlPlaceholder} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </div>

          <div>
            <div className="mb-1.5 flex items-baseline justify-between">
              <label className="text-xs text-muted-foreground">
                {t.modelSettings.modelList.label}
              </label>
              <span className="text-[10px] text-muted-foreground/70">
                {t.modelSettings.modelList.hint}
              </span>
            </div>
            <ul className="space-y-1.5">
              {models.map((id, idx) => (
                <li key={`edit-model-${idx}`} className="flex items-center gap-1.5">
                  <span
                    className="w-4 shrink-0 text-right text-[11px] text-muted-foreground/60 tabular-nums"
                    title={
                      idx === 0
                        ? t.modelSettings.modelList.label
                        : idx === models.length - 1
                          ? t.modelSettings.modelList.label
                          : ""
                    }
                  >
                    {idx === 0 ? "★" : idx === models.length - 1 ? "▴" : "·"}
                  </span>
                  <Input
                    className="flex-1 font-mono text-xs"
                    placeholder={t.modelSettings.modelList.label}
                    value={id}
                    onChange={(e) => handleModelChange(idx, e.target.value)}
                    disabled={loading}
                  />
                  <button
                    type="button"
                    className={cn(
                      "flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border/60 text-muted-foreground transition-colors",
                      "hover:border-destructive/50 hover:bg-destructive/10 hover:text-destructive",
                      "disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border/60 disabled:hover:bg-transparent disabled:hover:text-muted-foreground",
                    )}
                    onClick={() => handleModelRemove(idx)}
                    disabled={loading || models.length <= 1}
                    title={t.modelSettings.modelList.removeTooltip}
                    aria-label={t.modelSettings.modelList.removeTooltip}
                  >
                    <XCircleIcon className="size-4" />
                  </button>
                </li>
              ))}
            </ul>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-2 w-full border-dashed"
              onClick={handleModelAdd}
              disabled={loading}
            >
              <PlusIcon className="mr-1 h-3 w-3" /> {t.modelSettings.modelList.addButton}
            </Button>
          </div>

          <div className="rounded-lg border border-border/60 bg-muted/20">
            <button
              type="button"
              onClick={() => setShowHeaders((v) => !v)}
              className="flex w-full items-center justify-between px-3 py-2 text-xs font-medium hover:bg-muted/40"
            >
              <span>
                {t.modelSettings.extraHeadersTitle}
                {(() => {
                  const n = Object.keys(parseHeadersText(headersText)).length;
                  return n > 0 ? ` (${n})` : "";
                })()}
              </span>
              <span className="text-xs text-muted-foreground">
                {showHeaders ? "▾" : "▸"}
              </span>
            </button>
            {showHeaders && (
              <div className="space-y-2 border-t border-border/60 px-3 py-3">
                <textarea
                  value={headersText}
                  onChange={(e) => setHeadersText(e.target.value)}
                  placeholder={t.modelSettings.extraHeadersPlaceholder}
                  spellCheck={false}
                  rows={3}
                  className="w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
                <p className="text-[11px] text-muted-foreground">
                  {t.modelSettings.extraHeadersHint}
                </p>
              </div>
            )}
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="flex items-center gap-2 pt-5">
              <Switch checked={thinking} onCheckedChange={setThinking} /> <span className="text-xs">{t.modelSettings.thinkingLabel}</span>
            </div>
            <div className="flex items-center gap-2 pt-5">
              <Switch checked={vision} onCheckedChange={setVision} /> <span className="text-xs">{t.modelSettings.visionLabel}</span>
            </div>
          </div>

          {/* Test status + buttons */}
          <div className="flex items-center justify-between rounded-lg border border-border px-4 py-3">
            <div className="flex items-center gap-2 text-sm">
              {testStatus === "idle" && <><div className="h-2.5 w-2.5 rounded-lg bg-muted-foreground/40" /><span className="text-muted-foreground">{t.modelSettings.testFailed}</span></>}
              {testStatus === "testing" && <><Loader2Icon className="h-4 w-4 animate-spin text-blue-500" /><span className="text-blue-500">{t.common.loading}</span></>}
              {testStatus === "success" && <><CheckCircle2Icon className="h-4 w-4 text-green-500" /><span className="text-green-500">{testMessage}{testLatency != null ? ` (${testLatency}ms)` : ""}</span></>}
              {testStatus === "fail" && <><XCircleIcon className="h-4 w-4 text-destructive" /><span className="text-destructive">{testMessage}</span></>}
              <span className="text-xs text-muted-foreground ml-2">{t.modelSettings.testEndpointHint}</span>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={handleTest} disabled={testStatus === "testing" || loading}>
                <WifiIcon className="mr-1 h-3 w-3" /> {t.modelSettings.diagnose}
              </Button>
            </div>
          </div>
        </>
      )}
      {error && <div className="text-xs text-destructive">{error}</div>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel}>{t.common.cancel}</Button>
        <Button size="sm" className="bg-orange-500 hover:bg-orange-600 text-white" onClick={handleSave} disabled={saving || loading}>
          {saving ? t.common.loading : t.common.save}
        </Button>
      </div>
    </div>
  );
}

// ── Add model form ─────────────────────────────────────────────
function AddModelForm({ onCancel, onSaved }: { onCancel: () => void; onSaved: () => void }) {
  const { t } = useI18n();
  const [provider, setProvider] = useState("openai");
  const [protocol, setProtocol] = useState("openai");
  // Open-ended list of upstream model ids — matches the edit form
  // shape. Index 0 is the picker default, index -1 is the strongest
  // slot for Auto mode.
  const [models, setModels] = useState<string[]>([""]);
  const [displayName, setDisplayName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("https://api.openai.com/v1");
  const [thinking, setThinking] = useState(false);
  const [vision, setVision] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [testStatus, setTestStatus] = useState<TestStatus>("idle");
  const [testMessage, setTestMessage] = useState("");
  const [testLatency, setTestLatency] = useState<number | null>(null);
  // Extra HTTP headers. Stored as freeform text so users can paste
  // multiple lines; parsed into a dict only when submitting.
  const [headersText, setHeadersText] = useState("");
  const [showHeaders, setShowHeaders] = useState(false);

  const handleProviderChange = (value: string) => {
    setProvider(value);
    const preset = PROVIDERS.find((p) => p.value === value);
    if (preset) { setBaseUrl(preset.baseUrl); setProtocol(preset.protocol); }
  };

  const handleModelChange = (idx: number, value: string) => {
    setModels((prev) => prev.map((m, i) => (i === idx ? value : m)));
  };
  const handleModelAdd = () => {
    setModels((prev) => [...prev, ""]);
  };
  const handleModelRemove = (idx: number) => {
    setModels((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== idx)));
  };

  const handleTest = async () => {
    const firstModel = models.map((m) => m.trim()).find((m) => m.length > 0);
    if (!apiKey || !baseUrl || !firstModel) {
      setTestStatus("fail"); setTestMessage(t.modelSettings.fillRequiredBeforeTest); return;
    }
    setTestStatus("testing"); setTestMessage(""); setTestLatency(null);
    const started = performance.now();
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/config/custom-models/test`, {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({
          provider: protocol === "anthropic" ? "anthropic" : "openai",
          base_url: baseUrl,
          api_key: apiKey,
          model: firstModel,
          default_headers: parseHeadersText(headersText),
        }),
        signal: AbortSignal.timeout(8000),
      });
      const latency = Math.round(performance.now() - started);
      setTestLatency(latency);
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        setTestStatus("fail");
        setTestMessage(data.error || `HTTP ${res.status}`);
      } else {
        setTestStatus("success");
        setTestMessage(data.message || t.modelSettings.saveSuccess);
      }
    } catch (e: unknown) {
      setTestStatus("fail");
      setTestMessage(e instanceof Error ? e.message : t.modelSettings.networkError);
    }
  };

  const handleSave = async () => {
    const cleanedModels = models.map((m) => m.trim()).filter((m) => m.length > 0);
    if (!apiKey || !baseUrl || cleanedModels.length === 0) {
      setError(cleanedModels.length === 0 ? t.modelSettings.modelList.empty : t.modelSettings.requiredFields);
      return;
    }
    setSaving(true); setError("");
    // The first non-empty model id doubles as the entry id, since
    // ids have to be filename-safe and the picker shows the model
    // name the user just typed. Same convention as the previous
    // single-model layout. We already early-returned when
    // ``cleanedModels`` is empty, so index 0 is safe.
    const firstModel = cleanedModels[0] ?? "";
    const id = firstModel.replace(/[^a-zA-Z0-9._-]/g, "-");
    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/config/custom-models/${encodeURIComponent(id)}`,
        {
          method: "PUT",
          headers: jsonAuthHeaders(),
          body: JSON.stringify({
            name: id,
            display_name: displayName || firstModel,
            provider: protocol === "anthropic" ? "anthropic" : "openai",
            base_url: baseUrl,
            api_key: apiKey,
            models: cleanedModels,
            supports_thinking: thinking,
            supports_vision: vision,
            default_headers: parseHeadersText(headersText),
          }),
        },
      );
      if (!res.ok) { const data = await res.json(); setError(data.detail || t.modelSettings.updateFailed); return; }
      toast.success(t.modelSettings.saveSuccess);
      onSaved();
    } catch (e: unknown) { setError(e instanceof Error ? e.message : t.modelSettings.networkError); }
    finally { setSaving(false); }
  };

  return (
    <div className="rounded-lg border border-border p-5 space-y-4">
      <div className="flex items-center gap-2 rounded-lg bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-sm text-amber-600 dark:text-amber-400">
        <AlertTriangleIcon className="h-4 w-4 shrink-0" />
        <span>{t.modelSettings.externalModelRisk}</span>
      </div>

      <div>
        <label className="text-sm font-medium"><span className="text-destructive">*</span> {t.modelSettings.provider}</label>
        <select className="mt-1 flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" value={provider} onChange={(e) => handleProviderChange(e.target.value)}>
          {PROVIDERS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
        </select>
      </div>

      <div>
        <label className="text-sm font-medium"><span className="text-destructive">*</span> {t.modelSettings.modelList.label}</label>
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          {t.modelSettings.modelList.hint}
        </p>
        <ul className="mt-2 space-y-1.5">
          {models.map((id, idx) => (
            <li key={`add-model-${idx}`} className="flex items-center gap-1.5">
              <span
                className="w-4 shrink-0 text-right text-xs text-muted-foreground/60 tabular-nums"
              >
                {idx === 0 ? "★" : idx === models.length - 1 ? "▴" : "·"}
              </span>
              <Input
                className="flex-1 font-mono text-xs"
                placeholder={
                  idx === 0
                    ? t.modelSettings.modelIdPlaceholder
                    : t.modelSettings.modelIdPlaceholder
                }
                value={id}
                onChange={(e) => handleModelChange(idx, e.target.value)}
              />
              <button
                type="button"
                className={cn(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border/60 text-muted-foreground transition-colors",
                  "hover:border-destructive/50 hover:bg-destructive/10 hover:text-destructive",
                  "disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border/60 disabled:hover:bg-transparent disabled:hover:text-muted-foreground",
                )}
                onClick={() => handleModelRemove(idx)}
                disabled={models.length <= 1}
                title={t.modelSettings.modelList.removeTooltip}
                aria-label={t.modelSettings.modelList.removeTooltip}
              >
                <XCircleIcon className="size-4" />
              </button>
            </li>
          ))}
        </ul>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-2 w-full border-dashed"
          onClick={handleModelAdd}
        >
          <PlusIcon className="mr-1 h-3 w-3" /> {t.modelSettings.modelList.addButton}
        </Button>
        {/* Click-to-fill suggested model IDs · lets users skip
            "go look up the exact model name" · each chip populates
            the FIRST row of the models list. Renders only when the
            current preset ships a suggestion list. */}
        {(() => {
          const preset = PROVIDERS.find((p) => p.value === provider);
          if (!preset?.suggestedModels?.length) return null;
          return (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {preset.suggestedModels.map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => handleModelChange(0, m)}
                  className="rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                  title={t.modelSettings.fillModelId ?? "Fill this model ID"}
                >
                  {m}
                </button>
              ))}
            </div>
          );
        })()}
      </div>

      <div>
        <label className="text-sm font-medium">{t.modelSettings.displayName}</label>
        <Input className="mt-1" placeholder={t.modelSettings.displayNamePlaceholder} value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-sm font-medium flex items-center justify-between gap-2">
            <span>
              {PROVIDERS.find((p) => p.value === provider)?.label || t.modelSettings.provider} {t.modelSettings.apiKey}
            </span>
            {/* Console link · opens the provider's dashboard in a
                new tab so users don't have to hunt for the API
                key page. Renders only when the preset carries one. */}
            {(() => {
              const preset = PROVIDERS.find((p) => p.value === provider);
              if (!preset?.consoleUrl) return null;
              return (
                <a
                  href={preset.consoleUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[11px] text-primary hover:underline font-normal"
                >
                  {t.modelSettings.getApiKey}
                </a>
              );
            })()}
          </label>
          <div className="relative mt-1">
            <Input className="pr-10" type={showKey ? "text" : "password"} placeholder={t.modelSettings.apiKeyPlaceholder} value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
            <button type="button" className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground" onClick={() => setShowKey(!showKey)}>
              {showKey ? <EyeOffIcon className="size-4" /> : <EyeIcon className="size-4" />}
            </button>
          </div>
        </div>
        <div>
          <label className="text-sm font-medium">{t.modelSettings.apiProtocol}</label>
          <select className="mt-1 flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" value={protocol} onChange={(e) => setProtocol(e.target.value)}>
            {PROTOCOLS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </div>
      </div>

      <div>
        <label className="text-sm font-medium">{t.modelSettings.baseUrlLabel}</label>
        <Input className="mt-1" placeholder={t.modelSettings.baseUrlPlaceholder} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
      </div>

      {/* Extra HTTP headers — collapsed by default to keep the form
          uncluttered for the 95% case. Needed for APIs that gate on
          User-Agent (Kimi Coding) or require custom routing headers. */}
      <div className="rounded-lg border border-border/60 bg-muted/20">
        <button
          type="button"
          onClick={() => setShowHeaders((v) => !v)}
          className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium hover:bg-muted/40"
        >
          <span>
            {t.modelSettings.extraHeadersTitle}
            {(() => {
              const n = Object.keys(parseHeadersText(headersText)).length;
              return n > 0 ? ` (${n})` : "";
            })()}
          </span>
          <span className="text-xs text-muted-foreground">
            {showHeaders ? "▾" : "▸"}
          </span>
        </button>
        {showHeaders && (
          <div className="space-y-2 border-t border-border/60 px-3 py-3">
            <textarea
              value={headersText}
              onChange={(e) => setHeadersText(e.target.value)}
              placeholder={t.modelSettings.extraHeadersPlaceholder}
              spellCheck={false}
              rows={3}
              className="w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
            <p className="text-[11px] text-muted-foreground">
              {t.modelSettings.extraHeadersHint}
            </p>
          </div>
        )}
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="flex items-center gap-2 pt-6">
          <Switch checked={thinking} onCheckedChange={setThinking} /> <span className="text-sm">{t.modelSettings.thinkingLabel}</span>
        </div>
        <div className="flex items-center gap-2 pt-6">
          <Switch checked={vision} onCheckedChange={setVision} /> <span className="text-sm">{t.modelSettings.visionLabel}</span>
        </div>
      </div>

      {/* Test status + buttons */}
      <div className="flex items-center justify-between rounded-lg border border-border px-4 py-3">
        <div className="flex items-center gap-2 text-sm">
          {testStatus === "idle" && <><div className="h-2.5 w-2.5 rounded-lg bg-muted-foreground/40" /><span className="text-muted-foreground">{t.modelSettings.testFailed}</span></>}
          {testStatus === "testing" && <><Loader2Icon className="h-4 w-4 animate-spin text-blue-500" /><span className="text-blue-500">{t.common.loading}</span></>}
          {testStatus === "success" && <><CheckCircle2Icon className="h-4 w-4 text-green-500" /><span className="text-green-500">{testMessage}{testLatency != null ? ` (${testLatency}ms)` : ""}</span></>}
          {testStatus === "fail" && <><XCircleIcon className="h-4 w-4 text-destructive" /><span className="text-destructive">{testMessage}</span></>}
          <span className="text-xs text-muted-foreground ml-2">{t.modelSettings.testEndpointHint}</span>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="text-destructive border-destructive hover:bg-destructive/10" onClick={onCancel}>{t.common.cancel}</Button>
          <Button variant="outline" size="sm" onClick={handleTest} disabled={testStatus === "testing"}>
            <WifiIcon className="mr-1 h-3 w-3" /> {t.modelSettings.diagnose}
          </Button>
        </div>
      </div>

      {error && <div className="text-sm text-destructive">{error}</div>}

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>{t.common.cancel}</Button>
        <Button className="bg-orange-500 hover:bg-orange-600 text-white" onClick={handleSave} disabled={saving}>
          {saving ? t.common.loading : t.common.save}
        </Button>
      </div>
    </div>
  );
}

// ─── Local-model one-click import ─────────────────────────────
//
// Backs the "本地模型" SettingsSection. Sits next to the custom-
// models list so the operator's path from "I have Ollama running
// on my box" to "Octopus is routing to it" is one click: scan →
// import. The scan probes a small set of well-known ports in
// parallel; the import writes directly into ``custom_models_state``
// (same on-disk shape as the manual add form), and re-runs the
// parent's ``fetchModels`` so the new row appears in the list
// above without a manual refresh.
//
// The header row carries a live status badge so the operator can
// see whether a scan has run and what it found without expanding
// the results list. Hard-cut borders (not fade / height
// animation) read as "real section boundary" rather than "fancy
// dropdown" — the section is short enough that animation would
// just be visual noise.
interface DiscoveredService {
  provider: string;
  base_url: string;
  probe_path: string;
  models: string[];
  status: "ok" | "empty" | "error";
  error?: string;
}

function LocalModelsSection({ onImported }: { onImported?: () => void }) {
  const { t } = useI18n();
  const [services, setServices] = useState<DiscoveredService[]>([]);
  const [scanStatus, setScanStatus] = useState<"idle" | "scanning" | "done" | "error">("idle");
  // Per-row import-in-flight flag, keyed by base_url so a slow
  // import on one service doesn't lock out importing the others.
  const [importing, setImporting] = useState<Record<string, boolean>>({});

  const handleScan = useCallback(async () => {
    setScanStatus("scanning");
    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/config/local-models/scan`,
        { headers: authHeaders() },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setServices(Array.isArray(data.services) ? data.services : []);
      setScanStatus("done");
    } catch (e) {
      swallow(e);
      setScanStatus("error");
    }
  }, []);

  const handleImport = useCallback(
    async (svc: DiscoveredService) => {
      if (svc.status !== "ok" || svc.models.length === 0) return;
      setImporting((prev) => ({ ...prev, [svc.base_url]: true }));
      try {
        const res = await fetch(
          `${getBackendBaseURL()}/api/config/local-models/import`,
          {
            method: "POST",
            headers: jsonAuthHeaders(),
            body: JSON.stringify({
              base_url: svc.base_url,
              models: svc.models,
              // Display name falls back to the first model id; the
              // operator can rename in the edit form afterwards.
              display_name: svc.models[0] ?? svc.base_url,
            }),
          },
        );
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
          toast.error(
            `${t.modelSettings.localModels.importFailed}: ${
              data.error || `HTTP ${res.status}`
            }`,
          );
          return;
        }
        toast.success(t.modelSettings.localModels.imported);
        onImported?.();
      } catch (e) {
        swallow(e);
        toast.error(t.modelSettings.localModels.importFailed);
      } finally {
        setImporting((prev) => {
          const next = { ...prev };
          delete next[svc.base_url];
          return next;
        });
      }
    },
    [
      onImported,
      t.modelSettings.localModels.importFailed,
      t.modelSettings.localModels.imported,
    ],
  );

  return (
    <SettingsSection
      title={t.modelSettings.localModels.title}
      description={t.modelSettings.localModels.subtitle}
    >
      <div className="rounded-lg border border-border overflow-hidden">
        {/* Header bar · scan button + live status badge. Lives
            outside the collapsible so the operator can see whether
            a scan has run at a glance, even when the results list
            is collapsed. */}
        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">
              {t.modelSettings.localModels.providerHint}
            </span>
            {scanStatus === "scanning" && (
              <Loader2Icon className="size-3.5 animate-spin text-blue-500" />
            )}
            {scanStatus === "done" && services.length > 0 && (
              <span className="inline-flex items-center rounded-md border border-green-200 bg-green-50 px-1.5 py-0.5 text-[10px] font-medium text-green-700 dark:border-green-500/40 dark:bg-green-500/10 dark:text-green-400">
                {t.modelSettings.localModels.modelsCount(services.length)}
              </span>
            )}
            {scanStatus === "done" && services.length === 0 && (
              <span className="inline-flex items-center rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-medium text-slate-600 dark:border-slate-500/40 dark:bg-slate-500/10 dark:text-slate-400">
                {t.modelSettings.localModels.empty}
              </span>
            )}
            {scanStatus === "error" && (
              <span className="inline-flex items-center rounded-md border border-destructive/30 bg-destructive/10 px-1.5 py-0.5 text-[10px] font-medium text-destructive">
                {t.modelSettings.localModels.serviceStatus.error}
              </span>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleScan}
            disabled={scanStatus === "scanning"}
          >
            {scanStatus === "scanning" ? (
              <Loader2Icon className="mr-1.5 size-3.5 animate-spin" />
            ) : (
              <RefreshCwIcon className="mr-1.5 size-3.5" />
            )}
            {scanStatus === "scanning"
              ? t.modelSettings.localModels.scanButtonScanning
              : t.modelSettings.localModels.scanButton}
          </Button>
        </div>

        {/* Results list · only renders after a scan has been run.
            Empty state is inline rather than a separate screen so
            the operator's eye doesn't have to leave the section. */}
        {scanStatus !== "idle" && (
          <div className="border-t border-border divide-y divide-border">
            {services.length === 0 ? (
              <div className="px-4 py-6 text-sm text-muted-foreground">
                {t.modelSettings.localModels.emptyHint}
              </div>
            ) : (
              services.map((svc) => {
                const busy = !!importing[svc.base_url];
                const canImport =
                  svc.status === "ok" && svc.models.length > 0 && !busy;
                return (
                  <div
                    key={svc.base_url}
                    className="flex items-center gap-3 px-4 py-3"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <code className="truncate font-mono text-sm">
                          {svc.base_url}
                        </code>
                        {svc.status === "ok" && (
                          <span className="inline-flex shrink-0 items-center rounded-md border border-green-200 bg-green-50 px-1.5 py-0.5 text-[10px] font-medium text-green-700 dark:border-green-500/40 dark:bg-green-500/10 dark:text-green-400">
                            {t.modelSettings.localModels.serviceStatus.ok}
                          </span>
                        )}
                        {svc.status === "empty" && (
                          <span className="inline-flex shrink-0 items-center rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-400">
                            {t.modelSettings.localModels.serviceStatus.empty}
                          </span>
                        )}
                        {svc.status === "error" && (
                          <span className="inline-flex shrink-0 items-center rounded-md border border-destructive/30 bg-destructive/10 px-1.5 py-0.5 text-[10px] font-medium text-destructive">
                            {t.modelSettings.localModels.serviceStatus.error}
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {svc.status === "ok" &&
                          t.modelSettings.localModels.modelsCount(svc.models.length)}
                        {svc.status === "empty" &&
                          t.modelSettings.localModels.serviceStatus.empty}
                        {svc.error &&
                          `${t.modelSettings.localModels.serviceStatus.error}: ${svc.error}`}
                      </div>
                    </div>
                    <Button
                      variant="default"
                      size="sm"
                      onClick={() => handleImport(svc)}
                      disabled={!canImport}
                    >
                      {busy
                        ? t.modelSettings.localModels.importingButton
                        : t.modelSettings.localModels.importButton}
                    </Button>
                  </div>
                );
              })
            )}
          </div>
        )}
      </div>
    </SettingsSection>
  );
}
