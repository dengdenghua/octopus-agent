import {
  AlertTriangleIcon,
  CheckCircle2Icon,
  InfoIcon,
  EyeIcon,
  EyeOffIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  Trash2Icon,
  WifiIcon,
  XCircleIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { swallow } from "@/core/utils/log";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { useAuth } from "@/providers/AuthProvider";
import {
  clearThreadModelReferences,
  getLocalSettings,
  saveLocalSettings,
} from "@/core/settings/local";
import { registerPageAgentCapability } from "@/core/page-agent-bridge";
import { ModelCookbook } from "@/components/workspace/model-cookbook";

import { MixSettingsSection } from "./mix-settings-section";
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
    label: "Kimi Coding",
    value: "kimi-coding",
    baseUrl: "https://api.kimi.com/coding/v1",
    protocol: "openai",
    consoleUrl: "https://platform.moonshot.cn/console/api-keys",
    suggestedModels: ["K2.7-Code", "kimi-k2.7-code"],
  },
  {
    label: "Zhipu · GLM",
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
    label: "Alibaba Cloud · Tongyi Qwen (Qwen)",
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
    label: "Tencent Cloud · Hunyuan",
    value: "tencent",
    baseUrl: "https://api.hunyuan.cloud.tencent.com/v1",
    protocol: "openai",
    consoleUrl: "https://console.cloud.tencent.com/hunyuan/api-key",
    suggestedModels: ["hunyuan-turbos-latest", "hunyuan-large", "hunyuan-lite"],
  },
  {
    label: "Volcano Engine · Doubao (Ark)",
    value: "volcengine",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    protocol: "openai",
    consoleUrl: "https://console.volcengine.com/ark",
    suggestedModels: [
      "doubao-pro-256k",
      "doubao-1-5-pro-256k",
      "doubao-pro-32k",
    ],
  },
  {
    label: "Baichuan",
    value: "baichuan",
    baseUrl: "https://api.baichuan-ai.com/v1",
    protocol: "openai",
    consoleUrl: "https://platform.baichuan-ai.com/console/apikey",
    suggestedModels: ["Baichuan4", "Baichuan3-Turbo"],
  },
  {
    label: "01.AI · Yi",
    value: "lingyiwanwu",
    baseUrl: "https://api.lingyiwanwu.com/v1",
    protocol: "openai",
    consoleUrl: "https://platform.lingyiwanwu.com/",
    suggestedModels: ["yi-lightning", "yi-large"],
  },
  {
    label: "StepFun",
    value: "stepfun",
    baseUrl: "https://api.stepfun.com/v1",
    protocol: "openai",
    consoleUrl: "https://platform.stepfun.com/",
    suggestedModels: ["step-2-mini", "step-1-8k"],
  },
  {
    label: "SiliconFlow",
    value: "siliconflow",
    baseUrl: "https://api.siliconflow.cn/v1",
    protocol: "openai",
    consoleUrl: "https://cloud.siliconflow.cn/account/ak",
    suggestedModels: [
      "deepseek-ai/DeepSeek-V3",
      "Qwen/Qwen3-Coder-480B-A35B-Instruct",
    ],
  },
  {
    label: "Baidu · Qianfan",
    value: "qianfan",
    baseUrl: "https://qianfan.baidubce.com/v2",
    protocol: "openai",
    consoleUrl:
      "https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application",
    suggestedModels: ["ernie-4.5-turbo-128k", "ernie-x1-turbo-32k"],
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
  default_header_names?: string[];
  has_default_headers?: boolean;
  max_tokens?: number | null;
}

interface CompatDiagnosticUpstream {
  model: string;
  profile?: string | null;
  profile_display_name?: string | null;
  profile_summary?: {
    id?: string;
    display_name?: string;
    compat_score?: number;
    normalization_hints?: string[];
    notes?: string[];
  };
  compat_score?: number | null;
  normalization_hints?: string[];
  compatibility_notes?: string[];
  normalization?: {
    removed_fields?: string[];
    added_fields?: string[];
    changed_fields?: string[];
    normalized_fields?: string[];
  };
  fallback_retries?: Array<{
    reason?: string;
    removed_fields?: string[];
    added_fields?: string[];
    changed_fields?: string[];
  }>;
}

interface CompatDiagnostic {
  id: string;
  provider?: string | null;
  applicable: boolean;
  reason?: string | null;
  has_api_key?: boolean;
  default_header_names?: string[];
  built_in?: boolean;
  sample_base_url?: string;
  upstreams?: CompatDiagnosticUpstream[];
}

type CompatDiagnosticState =
  | { status: "idle" | "loading"; byId: Record<string, CompatDiagnostic> }
  | { status: "ready"; byId: Record<string, CompatDiagnostic> }
  | { status: "error"; byId: Record<string, CompatDiagnostic>; error: string };

type CompatProfileCatalogState =
  | { status: "idle" | "loading"; items: CompatDiagnostic[] }
  | { status: "ready"; items: CompatDiagnostic[] }
  | { status: "error"; items: CompatDiagnostic[]; error: string };

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

// Mirror of the backend base_url guard (config_router._validate_base_url)
// for instant feedback before the network round-trip. Loopback / private
// hosts stay allowed (local servers like Ollama / LM Studio); only
// non-http(s) schemes and link-local / cloud-metadata endpoints are
// rejected. Returns an error reason, or null when acceptable (empty
// included — the backend owns the per-provider "required" check).
function validateBaseUrl(url: string): string | null {
  if (!url) return null;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return "invalid base_url: unparseable URL";
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return `invalid base_url: scheme must be http/https (got ${parsed.protocol.replace(":", "")})`;
  }
  const host = parsed.hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (host === "metadata.google.internal" || host === "metadata.goog") {
    return "invalid base_url: blocked cloud-metadata host";
  }
  if (/^169\.254\./.test(host) || host.startsWith("fe80:")) {
    return "invalid base_url: blocked link-local address";
  }
  return null;
}

function collectCompatFields(
  diagnostic: CompatDiagnostic | undefined,
  key: "removed_fields" | "added_fields" | "changed_fields",
): string[] {
  const seen = new Set<string>();
  for (const upstream of diagnostic?.upstreams ?? []) {
    const values = upstream.normalization?.[key] ?? [];
    for (const value of values) {
      if (typeof value === "string" && value.trim()) seen.add(value);
    }
  }
  return Array.from(seen).sort();
}

function countCompatRetries(diagnostic: CompatDiagnostic | undefined): number {
  return (diagnostic?.upstreams ?? []).reduce(
    (total, upstream) =>
      total +
      (Array.isArray(upstream.fallback_retries)
        ? upstream.fallback_retries.length
        : 0),
    0,
  );
}

function summarizeCompatProfiles(
  diagnostic: CompatDiagnostic | undefined,
): string[] {
  const seen = new Set<string>();
  for (const upstream of diagnostic?.upstreams ?? []) {
    const label = upstream.profile_display_name || upstream.profile;
    if (typeof label === "string" && label.trim()) seen.add(label);
  }
  return Array.from(seen);
}

function summarizeCompatRetryReasons(
  diagnostic: CompatDiagnostic | undefined,
): string[] {
  const seen = new Set<string>();
  for (const upstream of diagnostic?.upstreams ?? []) {
    for (const retry of upstream.fallback_retries ?? []) {
      if (retry.reason) seen.add(retry.reason);
    }
  }
  return Array.from(seen).sort();
}

function summarizeCompatScoreRange(
  diagnostic: CompatDiagnostic | undefined,
): { min: number; max: number } | null {
  const scores: number[] = [];
  for (const upstream of diagnostic?.upstreams ?? []) {
    const candidates = [
      upstream.compat_score,
      upstream.profile_summary?.compat_score,
    ];
    for (const value of candidates) {
      if (typeof value === "number" && Number.isFinite(value)) {
        scores.push(Math.round(value));
      }
    }
  }
  if (scores.length === 0) return null;
  return {
    min: Math.min(...scores),
    max: Math.max(...scores),
  };
}

function collectCompatProfileText(
  diagnostic: CompatDiagnostic | undefined,
  key: "normalization_hints" | "compatibility_notes",
): string[] {
  const seen = new Set<string>();
  for (const upstream of diagnostic?.upstreams ?? []) {
    const direct =
      key === "normalization_hints"
        ? upstream.normalization_hints
        : upstream.compatibility_notes;
    const summary =
      key === "normalization_hints"
        ? upstream.profile_summary?.normalization_hints
        : upstream.profile_summary?.notes;
    for (const value of [...(direct ?? []), ...(summary ?? [])]) {
      if (typeof value === "string" && value.trim()) seen.add(value);
    }
  }
  return Array.from(seen).sort();
}

const MODEL_SETTINGS_PAGE_COPY: Record<
  "zh" | "en" | "ja" | "ko",
  {
    overviewTitle: string;
    overviewSubtitle: string;
    currentDefault: string;
    noDefault: string;
    configuredModels: string;
    gateway: string;
    gatewayConnected: string;
    gatewayDisconnected: string;
    gatewayChecking: string;
    addApiModel: string;
    scanLocalModels: string;
    diagnoseGateway: string;
    advancedTitle: string;
    advancedSubtitle: string;
    compatDetails: string;
    deletingDefault: (replacement: string | null) => string;
    deletedAndSwitched: (replacement: string) => string;
    deletedAndReset: string;
  }
> = {
  zh: {
    overviewTitle: "模型入口总览",
    overviewSubtitle:
      "先决定 Octopus 默认用哪个模型；需要接 API 就添加自定义模型，需要本地推理就扫描本地模型，高级兼容诊断放在下方。",
    currentDefault: "当前默认",
    noDefault: "未设置",
    configuredModels: "已接入模型",
    gateway: "模型网关",
    gatewayConnected: "已连接",
    gatewayDisconnected: "未连接",
    gatewayChecking: "检查中",
    addApiModel: "接入 API 模型",
    scanLocalModels: "扫描本地模型",
    diagnoseGateway: "诊断网关",
    advancedTitle: "高级能力与兼容诊断",
    advancedSubtitle:
      "Cookbook、Octopus Mix 和 OpenAI-compatible 矩阵偏专家向，默认收在这里，避免干扰日常配置。",
    compatDetails: "查看兼容处理规则",
    deletingDefault: (replacement) =>
      replacement
        ? `这是当前默认模型。删除后将自动切换到“${replacement}”。`
        : "这是当前默认模型。删除后将恢复为自动选择可用模型。",
    deletedAndSwitched: (replacement) =>
      `模型已删除，默认模型已切换到“${replacement}”。`,
    deletedAndReset: "模型已删除，默认模型已恢复为自动选择。",
  },
  en: {
    overviewTitle: "Model setup overview",
    overviewSubtitle:
      "Pick the default model first. Add a custom API model for hosted providers, scan local models for on-device inference, and keep compatibility diagnostics below.",
    currentDefault: "Current default",
    noDefault: "Not set",
    configuredModels: "Configured models",
    gateway: "Model gateway",
    gatewayConnected: "Connected",
    gatewayDisconnected: "Disconnected",
    gatewayChecking: "Checking",
    addApiModel: "Add API model",
    scanLocalModels: "Scan local models",
    diagnoseGateway: "Diagnose gateway",
    advancedTitle: "Advanced capabilities and diagnostics",
    advancedSubtitle:
      "Cookbook, Octopus Mix, and the OpenAI-compatible matrix are expert tools, so they stay grouped away from everyday setup.",
    compatDetails: "View compatibility rules",
    deletingDefault: (replacement) =>
      replacement
        ? `This is the current default. Deleting it will switch the default to “${replacement}”.`
        : "This is the current default. Deleting it will restore automatic model selection.",
    deletedAndSwitched: (replacement) =>
      `Model deleted. The default is now “${replacement}”.`,
    deletedAndReset:
      "Model deleted. The default has returned to automatic selection.",
  },
  ja: {
    overviewTitle: "モデル設定の概要",
    overviewSubtitle:
      "まず既定モデルを決めます。API 接続はカスタムモデル、ローカル推論はローカルスキャン、互換診断は下の高度な設定にまとめています。",
    currentDefault: "現在の既定",
    noDefault: "未設定",
    configuredModels: "設定済みモデル",
    gateway: "モデルゲートウェイ",
    gatewayConnected: "接続済み",
    gatewayDisconnected: "未接続",
    gatewayChecking: "確認中",
    addApiModel: "API モデルを追加",
    scanLocalModels: "ローカルモデルをスキャン",
    diagnoseGateway: "ゲートウェイ診断",
    advancedTitle: "高度な機能と互換診断",
    advancedSubtitle:
      "Cookbook、Octopus Mix、OpenAI 互換マトリクスは上級者向けなので、日常設定とは分けています。",
    compatDetails: "互換処理ルールを表示",
    deletingDefault: (replacement) =>
      replacement
        ? `現在の既定モデルです。削除後は「${replacement}」へ自動的に切り替わります。`
        : "現在の既定モデルです。削除後は利用可能なモデルの自動選択に戻ります。",
    deletedAndSwitched: (replacement) =>
      `モデルを削除し、既定モデルを「${replacement}」に切り替えました。`,
    deletedAndReset: "モデルを削除し、既定モデルを自動選択に戻しました。",
  },
  ko: {
    overviewTitle: "모델 설정 개요",
    overviewSubtitle:
      "먼저 기본 모델을 정하세요. API 제공자는 사용자 모델 추가, 로컬 추론은 로컬 모델 스캔, 호환성 진단은 아래 고급 영역에 모았습니다.",
    currentDefault: "현재 기본값",
    noDefault: "미설정",
    configuredModels: "설정된 모델",
    gateway: "모델 게이트웨이",
    gatewayConnected: "연결됨",
    gatewayDisconnected: "연결 안 됨",
    gatewayChecking: "확인 중",
    addApiModel: "API 모델 추가",
    scanLocalModels: "로컬 모델 스캔",
    diagnoseGateway: "게이트웨이 진단",
    advancedTitle: "고급 기능 및 호환성 진단",
    advancedSubtitle:
      "Cookbook, Octopus Mix, OpenAI 호환 매트릭스는 전문가용 도구이므로 일반 설정과 분리했습니다.",
    compatDetails: "호환 처리 규칙 보기",
    deletingDefault: (replacement) =>
      replacement
        ? `현재 기본 모델입니다. 삭제하면 기본 모델이 “${replacement}”(으)로 자동 전환됩니다.`
        : "현재 기본 모델입니다. 삭제하면 사용 가능한 모델 자동 선택으로 돌아갑니다.",
    deletedAndSwitched: (replacement) =>
      `모델을 삭제했고 기본 모델을 “${replacement}”(으)로 전환했습니다.`,
    deletedAndReset: "모델을 삭제했고 기본 모델을 자동 선택으로 되돌렸습니다.",
  },
};

function modelSettingsPageCopy(locale: string) {
  const lang = (locale || "en").slice(0, 2).toLowerCase();
  if (lang === "zh") return MODEL_SETTINGS_PAGE_COPY.zh;
  if (lang === "ja") return MODEL_SETTINGS_PAGE_COPY.ja;
  if (lang === "ko") return MODEL_SETTINGS_PAGE_COPY.ko;
  return MODEL_SETTINGS_PAGE_COPY.en;
}

const LOCAL_MODEL_SCAN_EVENT = "octopus:model-settings:scan-local";

function ModelSettingsOverview({
  copy,
  defaultModelName,
  customModelCount,
  gatewayStatus,
  onAddModel,
  onScanLocal,
  onDiagnoseGateway,
}: {
  copy: ReturnType<typeof modelSettingsPageCopy>;
  defaultModelName: string;
  customModelCount: number;
  gatewayStatus: "connected" | "disconnected" | "checking";
  onAddModel: () => void;
  onScanLocal: () => void;
  onDiagnoseGateway: () => void;
}) {
  const gatewayLabel =
    gatewayStatus === "connected"
      ? copy.gatewayConnected
      : gatewayStatus === "checking"
        ? copy.gatewayChecking
        : copy.gatewayDisconnected;

  return (
    <section className="rounded-2xl border border-border bg-card/60 p-4 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <h2 className="text-base font-semibold">{copy.overviewTitle}</h2>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-muted-foreground">
            {copy.overviewSubtitle}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={onAddModel}>
            <PlusIcon className="mr-1.5 size-3.5" />
            {copy.addApiModel}
          </Button>
          <Button size="sm" variant="outline" onClick={onScanLocal}>
            <WifiIcon className="mr-1.5 size-3.5" />
            {copy.scanLocalModels}
          </Button>
          <Button size="sm" variant="outline" onClick={onDiagnoseGateway}>
            <SearchIcon className="mr-1.5 size-3.5" />
            {copy.diagnoseGateway}
          </Button>
        </div>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        <div className="rounded-xl border border-border bg-background/65 p-3">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {copy.currentDefault}
          </div>
          <div className="mt-1 truncate font-mono text-sm text-foreground">
            {defaultModelName || copy.noDefault}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-background/65 p-3">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {copy.configuredModels}
          </div>
          <div className="mt-1 text-sm font-semibold text-foreground">
            {customModelCount}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-background/65 p-3">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {copy.gateway}
          </div>
          <div
            className={cn(
              "mt-1 inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
              gatewayStatus === "connected" &&
                "bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400",
              gatewayStatus === "checking" &&
                "bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400",
              gatewayStatus === "disconnected" &&
                "bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400",
            )}
          >
            {gatewayLabel}
          </div>
        </div>
      </div>
    </section>
  );
}

// ── Main page ──────────────────────────────────────────────────
export default function ModelSettingsPage() {
  const { t, locale } = useI18n();
  const pageCopy = modelSettingsPageCopy(locale);
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [compatDiagnostics, setCompatDiagnostics] =
    useState<CompatDiagnosticState>({
      status: "idle",
      byId: {},
    });
  const [compatProfileCatalog, setCompatProfileCatalog] =
    useState<CompatProfileCatalogState>({
      status: "idle",
      items: [],
    });
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editingModel, setEditingModel] = useState<string | null>(null);
  const [modelToDelete, setModelToDelete] = useState<string | null>(null);

  // Gateway connection state
  const [gatewayStatus, setGatewayStatus] = useState<
    "connected" | "disconnected" | "checking"
  >("checking");

  // List / CRUD all target the new hot-register dispatcher endpoints
  // (/api/config/custom-models/*). The legacy /api/models was the
  // OpenAI-compat gateway's *skills-as-models* listing and had no
  // writable CRUD on this backend — writing to it was silently no-op.
  const fetchCompatDiagnostics = useCallback(async () => {
    setCompatDiagnostics((prev) => ({
      status: "loading",
      byId: prev.byId,
    }));
    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/config/custom-models/compat-diagnostics`,
        {
          headers: authHeaders(),
        },
      );
      if (!res.ok) {
        throw new Error(
          `Failed to fetch compatibility diagnostics: ${res.status}`,
        );
      }
      const data = await res.json();
      const diagnostics = Array.isArray(data?.diagnostics)
        ? (data.diagnostics as CompatDiagnostic[])
        : [];
      const byId: Record<string, CompatDiagnostic> = {};
      for (const row of diagnostics) {
        if (typeof row?.id === "string" && row.id.trim()) {
          byId[row.id] = row;
        }
      }
      setCompatDiagnostics({ status: "ready", byId });
    } catch (error) {
      swallow(error);
      setCompatDiagnostics((prev) => ({
        status: "error",
        byId: prev.byId,
        error:
          error instanceof Error
            ? error.message
            : t.settings.model.compatDiagnostics.loadFailed,
      }));
    }
  }, [t.settings.model.compatDiagnostics.loadFailed]);

  const fetchCompatProfileCatalog = useCallback(async () => {
    setCompatProfileCatalog((prev) => ({
      status: "loading",
      items: prev.items,
    }));
    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/config/openai-compat-profiles`,
        {
          headers: authHeaders(),
        },
      );
      if (!res.ok) {
        throw new Error(`Failed to fetch profile catalog: ${res.status}`);
      }
      const data = await res.json();
      const items = Array.isArray(data?.diagnostics)
        ? (data.diagnostics as CompatDiagnostic[])
        : [];
      setCompatProfileCatalog({ status: "ready", items });
    } catch (error) {
      swallow(error);
      setCompatProfileCatalog((prev) => ({
        status: "error",
        items: prev.items,
        error:
          error instanceof Error
            ? error.message
            : t.settings.model.compatDiagnostics.loadFailed,
      }));
    }
  }, [t.settings.model.compatDiagnostics.loadFailed]);

  const fetchModels = useCallback(async () => {
    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/config/custom-models`,
        {
          headers: authHeaders(),
        },
      );
      if (!res.ok) {
        throw new Error(`Failed to fetch models: ${res.status}`);
      }
      const data = await res.json();
      const list = data.models || [];
      setModels(list);
      void fetchCompatDiagnostics();
      void fetchCompatProfileCatalog();
    } catch (error) {
      console.error(error);
      toast.error(t.settings.model.loadFailed);
    } finally {
      setLoading(false);
    }
  }, [
    fetchCompatDiagnostics,
    fetchCompatProfileCatalog,
    t.settings.model.loadFailed,
  ]);

  const checkGateway = useCallback(async () => {
    setGatewayStatus("checking");
    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/config/custom-models`,
        {
          headers: authHeaders(),
          signal: AbortSignal.timeout(5000),
        },
      );
      setGatewayStatus(res.ok ? "connected" : "disconnected");
    } catch (e) {
      swallow(e);
      setGatewayStatus("disconnected");
    }
  }, []);

  useEffect(() => {
    fetchModels();
    checkGateway();
  }, [fetchModels, checkGateway]);

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
      toast.success(t.settings.model.setDefaultSuccess);
      await fetchModels();
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : t.settings.model.setDefaultFailed,
      );
    }
  };

  const [deletingModel, setDeletingModel] = useState(false);

  const reconcileDeletedModel = useCallback(
    (name: string) => {
      clearThreadModelReferences(name);
      const settings = getLocalSettings();
      if (settings.context.model_name !== name) {
        setModels((current) => current.filter((model) => model.name !== name));
        return null;
      }

      const replacement =
        models.find((model) => model.name !== name)?.name ?? "";
      saveLocalSettings({
        ...settings,
        context: {
          ...settings.context,
          model_name: replacement,
        },
      });
      setModels((current) => current.filter((model) => model.name !== name));
      return replacement;
    },
    [models],
  );

  const doDeleteModel = async (name: string) => {
    setDeletingModel(true);
    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/config/custom-models/${encodeURIComponent(name)}`,
        {
          method: "DELETE",
          headers: authHeaders(),
        },
      );
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Delete failed: ${res.status}`);
      }
      const replacement = reconcileDeletedModel(name);
      if (replacement === null) {
        toast.success(t.settings.model.deleteSuccess);
      } else if (replacement) {
        toast.success(pageCopy.deletedAndSwitched(replacement));
      } else {
        toast.success(pageCopy.deletedAndReset);
      }
      await fetchModels();
      return true;
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.settings.model.deleteFailed,
      );
      return false;
    } finally {
      setDeletingModel(false);
    }
  };

  const handleDelete = (name: string) => {
    setModelToDelete(name);
  };

  const handleReconnect = () => {
    checkGateway();
  };

  const handleDiagnose = async () => {
    const issues: string[] = [];
    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/config/custom-models`,
        {
          headers: authHeaders(),
          signal: AbortSignal.timeout(5000),
        },
      );
      if (!res.ok) issues.push(t.settings.model.gatewayReturned(res.status));
    } catch (e) {
      swallow(e);
      issues.push(t.settings.model.cannotReachGateway);
    }

    if (issues.length === 0) {
      toast.success(t.settings.model.diagnoseHealthy);
    } else {
      toast.error(
        t.settings.model.diagnoseIssues(issues.map((i) => `• ${i}`).join(" ")),
      );
    }
  };

  const scrollToSection = useCallback((id: string) => {
    requestAnimationFrame(() => {
      document
        .getElementById(id)
        ?.scrollIntoView({ block: "start", behavior: "smooth" });
    });
  }, []);

  const handleOverviewAddModel = useCallback(() => {
    setEditingModel(null);
    setShowAdd(true);
    scrollToSection("model-settings-custom");
  }, [scrollToSection]);

  const handleOverviewScanLocal = useCallback(() => {
    scrollToSection("model-settings-local");
    window.dispatchEvent(new Event(LOCAL_MODEL_SCAN_EVENT));
  }, [scrollToSection]);

  const handleOverviewDiagnoseGateway = useCallback(() => {
    scrollToSection("model-settings-gateway");
    void handleDiagnose();
  }, [handleDiagnose, scrollToSection]);

  const { isGuest } = useAuth();

  // Implementation note.
  const defaultModelName = getLocalSettings().context.model_name;

  useEffect(() => {
    const unregisters = [
      registerPageAgentCapability({
        id: "models.custom.list",
        label: "List custom models",
        description:
          "Return current custom model summaries and gateway status.",
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
            compat_diagnostic: compatDiagnostics.byId[model.name] ?? null,
          })),
          builtInCompatProfiles: compatProfileCatalog.items.map((item) => ({
            id: item.id,
            profile: item.upstreams?.[0]?.profile,
            score: item.upstreams?.[0]?.compat_score,
            model: item.upstreams?.[0]?.model,
            fallbackCount: countCompatRetries(item),
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
          const res = await fetch(
            `${getBackendBaseURL()}/api/config/custom-models/test`,
            {
              method: "POST",
              headers: jsonAuthHeaders(),
              body: JSON.stringify({ id: name }),
              signal: AbortSignal.timeout(8000),
            },
          );
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
          const res = await fetch(
            `${getBackendBaseURL()}/api/config/custom-models/${encodeURIComponent(name)}`,
            {
              method: "DELETE",
              headers: authHeaders(),
            },
          );
          if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            throw new Error(data.detail || `Delete failed: ${res.status}`);
          }
          const replacement = reconcileDeletedModel(name);
          await fetchModels();
          return {
            deleted: name,
            defaultModelName:
              replacement === null ? defaultModelName : replacement,
          };
        },
      }),
    ];
    return () => {
      unregisters.forEach((unregister) => unregister());
    };
  }, [
    checkGateway,
    compatDiagnostics.byId,
    compatProfileCatalog.items,
    defaultModelName,
    fetchModels,
    gatewayStatus,
    models,
    reconcileDeletedModel,
  ]);

  const deletingCurrentDefault =
    modelToDelete !== null && modelToDelete === defaultModelName;
  const deleteReplacementModel = deletingCurrentDefault
    ? models.find((model) => model.name !== modelToDelete)
    : undefined;
  const deleteReplacement =
    deleteReplacementModel?.display_name ??
    deleteReplacementModel?.name ??
    null;

  return (
    <div className="space-y-8">
      <ModelSettingsOverview
        copy={pageCopy}
        defaultModelName={defaultModelName ?? ""}
        customModelCount={models.length}
        gatewayStatus={gatewayStatus}
        onAddModel={handleOverviewAddModel}
        onScanLocal={handleOverviewScanLocal}
        onDiagnoseGateway={handleOverviewDiagnoseGateway}
      />

      {/* ── Models Section ── */}
      <SettingsSection
        className="scroll-mt-6"
        title={
          <div
            id="model-settings-custom"
            className="flex w-full items-center justify-between"
          >
            <span>{t.settings.model.customModels}</span>
            {!showAdd && !editingModel && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowAdd(true)}
              >
                <PlusIcon className="mr-1 h-3 w-3" />{" "}
                {t.settings.model.addCustomModel}
              </Button>
            )}
          </div>
        }
      >
        {loading ? (
          <div className="text-muted-foreground text-sm">
            {t.common.loading}
          </div>
        ) : (
          <div className="flex w-full flex-col">
            {/* Model list */}
            <div className="rounded-lg border border-border divide-y divide-border">
              {models.map((m) => {
                const list = Array.isArray(m.models) ? m.models : [];
                const diagnostic = compatDiagnostics.byId[m.name];
                const displayName = m.display_name || m.name;
                const isDefault = defaultModelName === m.name;
                return (
                  <div
                    key={m.name}
                    className={cn(
                      "flex flex-col items-stretch justify-between gap-4 px-4 py-4 sm:flex-row sm:items-start sm:px-5",
                      isDefault && "bg-emerald-500/[0.035]",
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <div className="truncate text-sm font-medium">
                          {displayName}
                        </div>
                        <span
                          className="shrink-0 rounded-md border border-border bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground dark:border-muted-foreground/40 dark:bg-muted-foreground/10 dark:text-muted-foreground"
                          title={t.settings.model.modelList.hint}
                        >
                          {t.settings.model.modelCount(list.length)}
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
                                {idx === 0
                                  ? "★"
                                  : idx === list.length - 1
                                    ? "▴"
                                    : "·"}
                              </span>
                              <code className="truncate rounded bg-muted/60 px-1.5 py-0.5">
                                {id}
                              </code>
                            </li>
                          ))}
                        </ul>
                      )}
                      <CompatDiagnosticSummary
                        diagnostic={diagnostic}
                        status={compatDiagnostics.status}
                      />
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center justify-end gap-x-3 gap-y-2 sm:max-w-64">
                      {isDefault ? (
                        <span className="inline-flex items-center rounded-lg bg-green-100 px-3 py-1 text-xs font-medium text-green-700 dark:bg-green-500/20 dark:text-green-400">
                          {t.settings.model.systemDefault}
                        </span>
                      ) : (
                        <button
                          className="text-xs font-medium text-muted-foreground hover:text-foreground"
                          onClick={() => handleSetDefault(m.name)}
                          aria-label={`${t.settings.model.setAsDefault}: ${displayName}`}
                        >
                          {t.settings.model.setAsDefault}
                        </button>
                      )}
                      <button
                        className="text-xs font-medium text-orange-500 hover:text-orange-600"
                        onClick={() =>
                          setEditingModel(
                            editingModel === m.name ? null : m.name,
                          )
                        }
                        aria-label={`${t.common.edit}: ${displayName}`}
                      >
                        {t.common.edit}
                      </button>
                      <button
                        className="text-xs font-medium text-orange-500 hover:text-orange-600"
                        onClick={() => handleDelete(m.name)}
                        aria-label={`${t.common.delete}: ${displayName}`}
                      >
                        {t.common.delete}
                      </button>
                    </div>
                  </div>
                );
              })}
              {models.length === 0 && (
                <div className="px-5 py-8 text-center text-sm text-muted-foreground">
                  {t.settings.model.emptyCustomModels}
                </div>
              )}
            </div>

            {/* Edit form (inline under the list) */}
            {editingModel && (
              <div className="mt-4">
                <EditModelForm
                  modelName={editingModel}
                  onCancel={() => setEditingModel(null)}
                  onSaved={() => {
                    setEditingModel(null);
                    fetchModels();
                  }}
                />
              </div>
            )}

            {/* Add form */}
            {showAdd && (
              <div className="mt-4">
                <AddModelForm
                  onCancel={() => setShowAdd(false)}
                  onSaved={() => {
                    setShowAdd(false);
                    fetchModels();
                  }}
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
      <div id="model-settings-local" className="scroll-mt-6">
        <LocalModelsSection onImported={fetchModels} />
      </div>

      {/* Official models */}
      {!isGuest && <OfficialModelsSection />}

      {/* ── Gateway Connection Section ── */}
      <SettingsSection
        className="scroll-mt-6"
        title={
          <span id="model-settings-gateway">{t.settings.model.gatewayUrl}</span>
        }
      >
        <div className="space-y-4">
          {/* Status bar */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium">
                {t.settings.model.gatewayUrl}
              </span>
              {gatewayStatus === "connected" && (
                <span className="inline-flex items-center rounded-lg bg-green-100 dark:bg-green-500/20 px-3 py-1 text-xs font-medium text-green-700 dark:text-green-400">
                  {t.settings.model.connected}
                </span>
              )}
              {gatewayStatus === "disconnected" && (
                <span className="inline-flex items-center rounded-lg bg-red-100 dark:bg-red-500/20 px-3 py-1 text-xs font-medium text-red-700 dark:text-red-400">
                  {t.settings.model.disconnected}
                </span>
              )}
              {gatewayStatus === "checking" && (
                <span className="inline-flex items-center gap-1 rounded-lg bg-blue-100 dark:bg-blue-500/20 px-3 py-1 text-xs font-medium text-blue-700 dark:text-blue-400">
                  <Loader2Icon className="h-3 w-3 animate-spin" />{" "}
                  {t.common.loading}
                </span>
              )}
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={handleReconnect}>
                <RefreshCwIcon className="mr-1 h-3 w-3" />{" "}
                {t.settings.model.reconnect}
              </Button>
              <Button variant="outline" size="sm" onClick={handleDiagnose}>
                <SearchIcon className="mr-1 h-3 w-3" />{" "}
                {t.settings.model.diagnose}
              </Button>
            </div>
          </div>

          {/* Read-only backend target */}
          <div className="rounded-lg border border-border p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium">
                  {t.settings.model.port}
                </div>
                <div className="text-xs text-muted-foreground mt-1">
                  {t.settings.model.backendUrlHint}
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
              {t.settings.model.connectionHelp}
            </div>
            <ul className="space-y-1 text-blue-700 dark:text-blue-400 text-xs">
              <li>{t.settings.model.connectionHelpReconnect}</li>
              <li>{t.settings.model.setDefaultHint}</li>
              <li>{t.settings.model.connectionHelpDiagnose}</li>
            </ul>
          </div>
        </div>
      </SettingsSection>

      <details className="group rounded-2xl border border-border bg-card/40 p-4">
        <summary className="cursor-pointer list-none">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-lg font-semibold">
                {pageCopy.advancedTitle}
              </div>
              <div className="mt-1 text-sm text-muted-foreground">
                {pageCopy.advancedSubtitle}
              </div>
            </div>
            <span className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground transition-colors group-open:bg-muted">
              Advanced
            </span>
          </div>
        </summary>
        <div className="mt-6 space-y-8">
          {/* Hardware-aware local-model recommendations + one-click pull */}
          <ModelCookbook />

          {/* Octopus Mix · mixture-of-agents composer */}
          <MixSettingsSection />

          <BuiltInCompatProfilesCard catalog={compatProfileCatalog} />
        </div>
      </details>

      <Dialog
        open={modelToDelete !== null}
        onOpenChange={(nextOpen) => {
          if (!nextOpen && !deletingModel) setModelToDelete(null);
        }}
      >
        <DialogContent
          showCloseButton={false}
          className="w-[min(360px,calc(100vw-2rem))] gap-3 rounded-lg p-4 shadow-xl sm:max-w-[360px]"
        >
          <DialogHeader className="gap-1 text-left">
            <DialogTitle className="text-[15px]">
              {t.settings.model.deleteModelTitle}
            </DialogTitle>
            <DialogDescription className="text-[12.5px] leading-5">
              {modelToDelete
                ? t.settings.model.deleteConfirm(modelToDelete)
                : ""}
            </DialogDescription>
            {deletingCurrentDefault && (
              <div className="mt-2 flex gap-2 rounded-md border border-amber-200 bg-amber-50 p-2.5 text-[12px] leading-5 text-amber-800 dark:border-amber-500/25 dark:bg-amber-500/10 dark:text-amber-300">
                <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
                <span>{pageCopy.deletingDefault(deleteReplacement)}</span>
              </div>
            )}
          </DialogHeader>
          <DialogFooter className="mt-1 flex-row justify-end gap-2">
            <button
              type="button"
              disabled={deletingModel}
              onClick={() => setModelToDelete(null)}
              className="inline-flex h-8 items-center justify-center rounded-md border border-border bg-background px-3 text-[12.5px] font-medium text-foreground/80 transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-60"
            >
              {t.common.cancel}
            </button>
            <button
              type="button"
              disabled={deletingModel}
              onClick={async () => {
                if (!modelToDelete) return;
                const target = modelToDelete;
                const deleted = await doDeleteModel(target);
                if (deleted) setModelToDelete(null);
              }}
              className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-destructive/25 bg-destructive/[0.07] px-3 text-[12.5px] font-medium text-destructive transition-colors hover:border-destructive/35 hover:bg-destructive/[0.11] disabled:pointer-events-none disabled:opacity-60"
            >
              {deletingModel ? (
                <span className="size-3 animate-spin rounded-full border border-current border-t-transparent" />
              ) : (
                <Trash2Icon className="size-3.5" />
              )}
              {t.common.delete}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function BuiltInCompatProfilesCard({
  catalog,
}: {
  catalog: CompatProfileCatalogState;
}) {
  const visible = catalog.items.slice(0, 8);
  const remaining = Math.max(0, catalog.items.length - visible.length);
  const loaded = catalog.status === "ready" || catalog.items.length > 0;

  return (
    <SettingsSection
      title={
        <div className="flex w-full items-center justify-between gap-3">
          <span>OpenAI-compatible profile matrix</span>
          <span className="text-xs font-normal text-muted-foreground">
            {loaded ? `${catalog.items.length} profiles` : "loading"}
          </span>
        </div>
      }
    >
      <div className="space-y-3">
        <div className="text-sm leading-6 text-muted-foreground">
          Built-in dry-run matrix for domestic and proxy OpenAI-compatible
          providers. It shows request normalization and fallback retries before
          an API key is configured.
        </div>
        {catalog.status === "loading" && catalog.items.length === 0 ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2Icon className="size-4 animate-spin" />
            Loading compatibility profiles
          </div>
        ) : catalog.status === "error" && catalog.items.length === 0 ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <AlertTriangleIcon className="size-4 text-amber-500" />
            Compatibility profile catalog unavailable
          </div>
        ) : (
          <div className="grid gap-2 xl:grid-cols-2">
            {visible.map((item) => {
              const upstream = item.upstreams?.[0];
              const score = summarizeCompatScoreRange(item);
              const removed = collectCompatFields(item, "removed_fields");
              const retryReasons = summarizeCompatRetryReasons(item);
              const hints = collectCompatProfileText(
                item,
                "normalization_hints",
              );
              return (
                <div
                  key={item.id}
                  className="rounded-lg border border-border-default bg-background/50 px-3 py-2"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate text-sm font-medium">
                          {upstream?.profile_display_name || item.id}
                        </span>
                        {score && (
                          <span className="rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                            compat{" "}
                            {score.min === score.max
                              ? score.min
                              : `${score.min}-${score.max}`}
                          </span>
                        )}
                      </div>
                      <div className="mt-1 truncate font-mono text-[11px] text-muted-foreground">
                        {upstream?.model || item.id}
                      </div>
                    </div>
                    <span className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                      {countCompatRetries(item)} fallback
                    </span>
                  </div>
                  <div className="mt-2 space-y-1 text-[11px] text-muted-foreground">
                    {hints.length > 0 && (
                      <div title={hints.join(", ")}>
                        normalize {hints.slice(0, 4).join(", ")}
                        {hints.length > 4 ? "..." : ""}
                      </div>
                    )}
                    {removed.length > 0 && (
                      <div title={removed.join(", ")}>
                        drops {removed.slice(0, 5).join(", ")}
                        {removed.length > 5 ? "..." : ""}
                      </div>
                    )}
                    {retryReasons.length > 0 && (
                      <div title={retryReasons.join(", ")}>
                        retries {retryReasons.slice(0, 4).join(", ")}
                        {retryReasons.length > 4 ? "..." : ""}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
        {remaining > 0 && (
          <div className="text-xs text-muted-foreground">
            +{remaining} more profiles in the backend catalog.
          </div>
        )}
      </div>
    </SettingsSection>
  );
}

function CompatDiagnosticSummary({
  diagnostic,
  status,
}: {
  diagnostic?: CompatDiagnostic;
  status: CompatDiagnosticState["status"];
}) {
  const { t, locale } = useI18n();
  const pageCopy = modelSettingsPageCopy(locale);

  if (status === "loading" && !diagnostic) {
    return (
      <div className="mt-3 flex items-center gap-2 text-[11px] text-muted-foreground">
        <Loader2Icon className="size-3 animate-spin" />
        {t.settings.model.compatDiagnostics.loading}
      </div>
    );
  }

  if (!diagnostic) {
    return status === "error" ? (
      <div className="mt-3 flex items-center gap-2 text-[11px] text-muted-foreground">
        <AlertTriangleIcon className="size-3.5 text-amber-500" />
        {t.settings.model.compatDiagnostics.unavailable}
      </div>
    ) : null;
  }

  if (!diagnostic.applicable) {
    return (
      <div className="mt-3 flex items-center gap-2 text-[11px] text-muted-foreground">
        <InfoIcon className="size-3.5" />
        <span>
          {diagnostic.reason ||
            t.settings.model.compatDiagnostics.notApplicable}
        </span>
      </div>
    );
  }

  const profiles = summarizeCompatProfiles(diagnostic);
  const removed = collectCompatFields(diagnostic, "removed_fields");
  const changed = collectCompatFields(diagnostic, "changed_fields");
  const added = collectCompatFields(diagnostic, "added_fields");
  const fallbackCount = countCompatRetries(diagnostic);
  const retryReasons = summarizeCompatRetryReasons(diagnostic);
  const scoreRange = summarizeCompatScoreRange(diagnostic);
  const normalizationHints = collectCompatProfileText(
    diagnostic,
    "normalization_hints",
  );
  const compatibilityNotes = collectCompatProfileText(
    diagnostic,
    "compatibility_notes",
  );
  const headerNames = diagnostic.default_header_names ?? [];
  const scoreLabel = scoreRange
    ? scoreRange.min === scoreRange.max
      ? `${scoreRange.min}`
      : `${scoreRange.min}-${scoreRange.max}`
    : null;
  const hasDetails =
    removed.length > 0 ||
    changed.length > 0 ||
    added.length > 0 ||
    normalizationHints.length > 0 ||
    compatibilityNotes.length > 0 ||
    retryReasons.length > 0;

  return (
    <div className="mt-3 space-y-2 border-l border-border pl-3 text-[11px] text-muted-foreground">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="inline-flex items-center gap-1 font-medium text-foreground/80">
          <CheckCircle2Icon className="size-3.5 text-emerald-500" />
          {t.settings.model.compatDiagnostics.title}
        </span>
        {profiles.length > 0 && (
          <span className="rounded border border-border px-1.5 py-0.5">
            {profiles.join(", ")}
          </span>
        )}
        <span className="rounded border border-border px-1.5 py-0.5">
          {t.settings.model.compatDiagnostics.fallbacks(fallbackCount)}
        </span>
        {scoreLabel && (
          <span className="rounded border border-border px-1.5 py-0.5">
            {t.settings.model.compatDiagnostics.compatScore(scoreLabel)}
          </span>
        )}
        {headerNames.length > 0 && (
          <span className="rounded border border-border px-1.5 py-0.5">
            {t.settings.model.compatDiagnostics.headers(headerNames.join(", "))}
          </span>
        )}
      </div>
      {hasDetails && (
        <details className="group/compat">
          <summary className="w-fit cursor-pointer select-none rounded px-1 py-0.5 font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground">
            {pageCopy.compatDetails}
          </summary>
          <div className="mt-2 space-y-1.5 rounded-md bg-muted/35 p-2.5">
            {(removed.length > 0 || changed.length > 0 || added.length > 0) && (
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {removed.length > 0 && (
                  <span title={removed.join(", ")}>
                    {t.settings.model.compatDiagnostics.removedFields(
                      removed.slice(0, 5).join(", "),
                      removed.length,
                    )}
                  </span>
                )}
                {changed.length > 0 && (
                  <span title={changed.join(", ")}>
                    {t.settings.model.compatDiagnostics.changedFields(
                      changed.slice(0, 5).join(", "),
                      changed.length,
                    )}
                  </span>
                )}
                {added.length > 0 && (
                  <span title={added.join(", ")}>
                    {t.settings.model.compatDiagnostics.addedFields(
                      added.slice(0, 5).join(", "),
                      added.length,
                    )}
                  </span>
                )}
              </div>
            )}
            {normalizationHints.length > 0 && (
              <div title={normalizationHints.join(", ")}>
                {t.settings.model.compatDiagnostics.normalizationHints(
                  normalizationHints.slice(0, 5).join(", "),
                  normalizationHints.length,
                )}
              </div>
            )}
            {compatibilityNotes.length > 0 && (
              <div title={compatibilityNotes.join("; ")}>
                {t.settings.model.compatDiagnostics.compatibilityNotes(
                  compatibilityNotes.slice(0, 2).join("; "),
                  compatibilityNotes.length,
                )}
              </div>
            )}
            {retryReasons.length > 0 && (
              <div title={retryReasons.join(", ")}>
                {t.settings.model.compatDiagnostics.retryReasons(
                  retryReasons.slice(0, 4).join(", "),
                  retryReasons.length,
                )}
              </div>
            )}
          </div>
        </details>
      )}
    </div>
  );
}

// Official models from the account-backed gateway.
//
// Reads from the oct gateway model list when the official gateway is enabled.
// When the bridge is disabled (503) or the user hasn't linked their account
// yet (404), hides the section entirely.
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
  const [unavailableReason, setUnavailableReason] = useState<string | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(
          `${getBackendBaseURL()}/api/oct/openai/v1/models`,
          { headers: authHeaders() },
        );
        if (cancelled) return;
        if (r.status === 404) {
          setUnavailableReason(t.settings.model.accountNotLinked);
          setModels([]);
          return;
        }
        if (r.status === 503) {
          setUnavailableReason(t.settings.model.gatewayNotEnabled);
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
          setUnavailableReason(
            err instanceof Error ? err.message : String(err),
          );
          setModels([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t.settings.model.gatewayNotEnabled, t.settings.model.accountNotLinked]);

  if (loading) {
    return (
      <SettingsSection title={t.settings.model.officialModels}>
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
    .filter((m) => !/^auto$/i.test(m.id))
    .map((m) => ({ upstream: m }));

  return (
    <SettingsSection title={t.settings.model.officialModels}>
      <div className="rounded-lg border border-border divide-y divide-border">
        {rows.length === 0 && (
          <div className="px-5 py-8 text-center text-sm text-muted-foreground">
            {t.settings.model.noOfficialModels}
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
              <div className="text-xs text-muted-foreground">{upstream.id}</div>
            </div>
            <div className="flex items-center gap-3">
              <span className="rounded-lg bg-muted px-2 py-0.5 text-xs tabular-nums text-muted-foreground">
                {upstream.multiplier ?? "1.0x"}
              </span>
              <span className="text-[10px] text-muted-foreground">
                {t.settings.model.gatewayHosted}
              </span>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        {t.settings.model.officialModelsHint}
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
function EditModelForm({
  modelName,
  onCancel,
  onSaved,
}: {
  modelName: string;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const [displayName, setDisplayName] = useState("");
  // Open-ended list of upstream model ids this entry can dispatch
  // to. Index 0 is the picker default, index -1 is the strongest
  // slot for Auto mode's performance verdict. Mirrors the
  // ``models`` field on the custom-model entry.
  const [models, setModels] = useState<string[]>([""]);
  const [apiKey, setApiKey] = useState("");
  const [apiKeyPlaceholder, setApiKeyPlaceholder] = useState(
    t.settings.model.apiKeyPlaceholder,
  );
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
    if (u.includes("googleapis.com") || u.includes("generativelanguage"))
      return "gemini";
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
        const list = (await res.json()).models as Array<
          Record<string, unknown>
        >;
        const d = list.find((m) => m.id === modelName) ?? {};
        if (cancelled) return;
        setDisplayName((d.display_name as string) || (d.name as string) || "");
        const rawModels = Array.isArray(d.models)
          ? (d.models as unknown[])
          : [];
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
            ? `••• · ${t.settings.model.keepApiKeyHint}`
            : t.settings.model.apiKeyPlaceholder,
        );
      } catch (e) {
        swallow(e);
        if (!cancelled)
          setError(
            e instanceof Error ? e.message : t.settings.model.networkError,
          );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [
    modelName,
    t.settings.model.apiKeyPlaceholder,
    t.settings.model.keepApiKeyHint,
    t.settings.model.networkError,
  ]);

  const handleModelChange = (idx: number, value: string) => {
    setModels((prev) => prev.map((m, i) => (i === idx ? value : m)));
  };
  const handleModelAdd = () => {
    setModels((prev) => [...prev, ""]);
  };
  const handleModelRemove = (idx: number) => {
    setModels((prev) =>
      prev.length <= 1 ? prev : prev.filter((_, i) => i !== idx),
    );
  };

  const handleSave = async () => {
    setSaving(true);
    setError("");
    // Drop empty rows before persisting so the backend never sees
    // a trailing blank in the models list. The UI still shows the
    // last row even if it's empty, so the user can keep typing.
    const cleanedModels = models
      .map((m) => m.trim())
      .filter((m) => m.length > 0);
    if (cleanedModels.length === 0) {
      setError(t.settings.model.modelList.empty);
      setSaving(false);
      return;
    }
    const baseUrlErr = validateBaseUrl(baseUrl);
    if (baseUrlErr) {
      setError(baseUrlErr);
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
        setError(data.detail || t.settings.model.updateFailed);
        return;
      }
      toast.success(t.settings.model.saveSuccess);
      onSaved();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t.settings.model.networkError);
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    if (!baseUrl) {
      setTestStatus("fail");
      setTestMessage(t.settings.model.fillRequiredBeforeTest);
      return;
    }
    const baseUrlErr = validateBaseUrl(baseUrl);
    if (baseUrlErr) {
      setTestStatus("fail");
      setTestMessage(baseUrlErr);
      return;
    }
    setTestStatus("testing");
    setTestMessage("");
    setTestLatency(null);
    const started = performance.now();
    // Test against the first non-empty model id (the picker default).
    const firstModel =
      models.map((m) => m.trim()).find((m) => m.length > 0) || modelName;
    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/config/custom-models/test`,
        {
          method: "POST",
          headers: jsonAuthHeaders(),
          body: JSON.stringify({
            id: modelName,
            base_url: baseUrl,
            api_key: apiKey || undefined,
            model: firstModel,
            provider: baseUrl.includes("anthropic.com")
              ? "anthropic"
              : undefined,
            default_headers: parseHeadersText(headersText),
          }),
          signal: AbortSignal.timeout(8000),
        },
      );
      const latency = Math.round(performance.now() - started);
      setTestLatency(latency);
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        setTestStatus("fail");
        setTestMessage(data.error || `HTTP ${res.status}`);
      } else {
        setTestStatus("success");
        setTestMessage(data.message || t.settings.model.saveSuccess);
      }
    } catch (e: unknown) {
      setTestStatus("fail");
      setTestMessage(
        e instanceof Error ? e.message : t.settings.model.networkError,
      );
    }
  };

  return (
    <div className="rounded-lg border border-border p-4 space-y-3">
      <div className="text-sm font-medium">
        {t.settings.model.editModelTitle(modelName)}
      </div>
      {loading ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2Icon className="size-3.5 animate-spin" />
          {t.common.loading}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-muted-foreground">
                {t.settings.model.providerLabel}
              </label>
              <div className="flex h-9 items-center rounded-md border border-input bg-muted/40 px-3 text-sm">
                <span className="font-mono">{detectedProvider}</span>
                <span className="ml-2 text-[10px] text-muted-foreground/70">
                  {t.settings.model.providerAutoHint}
                </span>
              </div>
            </div>
            <div>
              <label className="text-xs text-muted-foreground">
                {t.settings.model.keepApiKeyHint}
              </label>
              <div className="relative">
                <Input
                  className="pr-10"
                  type={showKey ? "text" : "password"}
                  placeholder={apiKeyPlaceholder}
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
                <button
                  type="button"
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  onClick={() => setShowKey(!showKey)}
                >
                  {showKey ? (
                    <EyeOffIcon className="size-4" />
                  ) : (
                    <EyeIcon className="size-4" />
                  )}
                </button>
              </div>
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground">
              {t.settings.model.baseUrlLabel}
            </label>
            <Input
              placeholder={t.settings.model.baseUrlPlaceholder}
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </div>

          <div>
            <div className="mb-1.5 flex items-baseline justify-between">
              <label className="text-xs text-muted-foreground">
                {t.settings.model.modelList.label}
              </label>
              <span className="text-[10px] text-muted-foreground/70">
                {t.settings.model.modelList.hint}
              </span>
            </div>
            <ul className="space-y-1.5">
              {models.map((id, idx) => (
                <li
                  key={`edit-model-${idx}`}
                  className="flex items-center gap-1.5"
                >
                  <span
                    className="w-4 shrink-0 text-right text-[11px] text-muted-foreground/60 tabular-nums"
                    title={
                      idx === 0
                        ? t.settings.model.modelList.label
                        : idx === models.length - 1
                          ? t.settings.model.modelList.label
                          : ""
                    }
                  >
                    {idx === 0 ? "★" : idx === models.length - 1 ? "▴" : "·"}
                  </span>
                  <Input
                    className="flex-1 font-mono text-xs"
                    placeholder={t.settings.model.modelList.label}
                    value={id}
                    onChange={(e) => handleModelChange(idx, e.target.value)}
                    disabled={loading}
                  />
                  <button
                    type="button"
                    className={cn(
                      "flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border-default text-muted-foreground transition-colors",
                      "hover:border-destructive/50 hover:bg-destructive/10 hover:text-destructive",
                      "disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border-default disabled:hover:bg-transparent disabled:hover:text-muted-foreground",
                    )}
                    onClick={() => handleModelRemove(idx)}
                    disabled={loading || models.length <= 1}
                    title={t.settings.model.modelList.removeTooltip}
                    aria-label={t.settings.model.modelList.removeTooltip}
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
              <PlusIcon className="mr-1 h-3 w-3" />{" "}
              {t.settings.model.modelList.addButton}
            </Button>
          </div>

          <div className="rounded-lg border border-border-default bg-muted/20">
            <button
              type="button"
              onClick={() => setShowHeaders((v) => !v)}
              className="flex w-full items-center justify-between px-3 py-2 text-xs font-medium hover:bg-muted/40"
            >
              <span>
                {t.settings.model.extraHeadersTitle}
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
              <div className="space-y-2 border-t border-border-default px-3 py-3">
                <textarea
                  value={headersText}
                  onChange={(e) => setHeadersText(e.target.value)}
                  placeholder={t.settings.model.extraHeadersPlaceholder}
                  spellCheck={false}
                  rows={3}
                  className="w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
                <p className="text-[11px] text-muted-foreground">
                  {t.settings.model.extraHeadersHint}
                </p>
              </div>
            )}
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div className="flex items-center gap-2 pt-5">
              <Switch checked={thinking} onCheckedChange={setThinking} />{" "}
              <span className="text-xs">{t.settings.model.thinkingLabel}</span>
            </div>
            <div className="flex items-center gap-2 pt-5">
              <Switch checked={vision} onCheckedChange={setVision} />{" "}
              <span className="text-xs">{t.settings.model.visionLabel}</span>
            </div>
          </div>

          {/* Test status + buttons */}
          <div className="flex items-center justify-between rounded-lg border border-border px-4 py-3">
            <div className="flex items-center gap-2 text-sm">
              {testStatus === "idle" && (
                <>
                  <div className="h-2.5 w-2.5 rounded-lg bg-muted-foreground/40" />
                  <span className="text-muted-foreground">
                    {t.settings.model.testFailed}
                  </span>
                </>
              )}
              {testStatus === "testing" && (
                <>
                  <Loader2Icon className="h-4 w-4 animate-spin text-blue-500" />
                  <span className="text-blue-500">{t.common.loading}</span>
                </>
              )}
              {testStatus === "success" && (
                <>
                  <CheckCircle2Icon className="h-4 w-4 text-green-500" />
                  <span className="text-green-500">
                    {testMessage}
                    {testLatency != null ? ` (${testLatency}ms)` : ""}
                  </span>
                </>
              )}
              {testStatus === "fail" && (
                <>
                  <XCircleIcon className="h-4 w-4 text-destructive" />
                  <span className="text-destructive">{testMessage}</span>
                </>
              )}
              <span className="text-xs text-muted-foreground ml-2">
                {t.settings.model.testEndpointHint}
              </span>
            </div>
            <div className="flex gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={handleTest}
                disabled={testStatus === "testing" || loading}
              >
                <WifiIcon className="mr-1 h-3 w-3" />{" "}
                {t.settings.model.diagnose}
              </Button>
            </div>
          </div>
        </>
      )}
      {error && <div className="text-xs text-destructive">{error}</div>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel}>
          {t.common.cancel}
        </Button>
        <Button
          size="sm"
          className="bg-orange-500 hover:bg-orange-600 text-white"
          onClick={handleSave}
          disabled={saving || loading}
        >
          {saving ? t.common.loading : t.common.save}
        </Button>
      </div>
    </div>
  );
}

// ── Add model form ─────────────────────────────────────────────
function AddModelForm({
  onCancel,
  onSaved,
}: {
  onCancel: () => void;
  onSaved: () => void;
}) {
  const { t } = useI18n();
  const getProviderLabel = (value: string): string => {
    switch (value) {
      case "zhipu":
        return t.settings.model.providers.zhipu;
      case "aliyun":
        return t.settings.model.providers.aliyun;
      case "tencent":
        return t.settings.model.providers.tencent;
      case "volcengine":
        return t.settings.model.providers.volcengine;
      default:
        return PROVIDERS.find((p) => p.value === value)?.label ?? value;
    }
  };
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
    if (preset) {
      setBaseUrl(preset.baseUrl);
      setProtocol(preset.protocol);
    }
  };

  const handleModelChange = (idx: number, value: string) => {
    setModels((prev) => prev.map((m, i) => (i === idx ? value : m)));
  };
  const handleModelAdd = () => {
    setModels((prev) => [...prev, ""]);
  };
  const handleModelRemove = (idx: number) => {
    setModels((prev) =>
      prev.length <= 1 ? prev : prev.filter((_, i) => i !== idx),
    );
  };

  const handleTest = async () => {
    const firstModel = models.map((m) => m.trim()).find((m) => m.length > 0);
    if (!apiKey || !baseUrl || !firstModel) {
      setTestStatus("fail");
      setTestMessage(t.settings.model.fillRequiredBeforeTest);
      return;
    }
    const baseUrlErr = validateBaseUrl(baseUrl);
    if (baseUrlErr) {
      setTestStatus("fail");
      setTestMessage(baseUrlErr);
      return;
    }
    setTestStatus("testing");
    setTestMessage("");
    setTestLatency(null);
    const started = performance.now();
    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/config/custom-models/test`,
        {
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
        },
      );
      const latency = Math.round(performance.now() - started);
      setTestLatency(latency);
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) {
        setTestStatus("fail");
        setTestMessage(data.error || `HTTP ${res.status}`);
      } else {
        setTestStatus("success");
        setTestMessage(data.message || t.settings.model.saveSuccess);
      }
    } catch (e: unknown) {
      setTestStatus("fail");
      setTestMessage(
        e instanceof Error ? e.message : t.settings.model.networkError,
      );
    }
  };

  const handleSave = async () => {
    const cleanedModels = models
      .map((m) => m.trim())
      .filter((m) => m.length > 0);
    if (!apiKey || !baseUrl || cleanedModels.length === 0) {
      setError(
        cleanedModels.length === 0
          ? t.settings.model.modelList.empty
          : t.settings.model.requiredFields,
      );
      return;
    }
    setSaving(true);
    setError("");
    const baseUrlErr = validateBaseUrl(baseUrl);
    if (baseUrlErr) {
      setError(baseUrlErr);
      setSaving(false);
      return;
    }
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
      if (!res.ok) {
        const data = await res.json();
        setError(data.detail || t.settings.model.updateFailed);
        return;
      }
      toast.success(t.settings.model.saveSuccess);
      onSaved();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t.settings.model.networkError);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-lg border border-border p-5 space-y-4">
      <div className="flex items-center gap-2 rounded-lg bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-sm text-amber-600 dark:text-amber-400">
        <AlertTriangleIcon className="h-4 w-4 shrink-0" />
        <span>{t.settings.model.externalModelRisk}</span>
      </div>

      <div>
        <label className="text-sm font-medium">
          <span className="text-destructive">*</span>{" "}
          {t.settings.model.provider}
        </label>
        <select
          className="mt-1 flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          value={provider}
          onChange={(e) => handleProviderChange(e.target.value)}
        >
          {PROVIDERS.map((p) => (
            <option key={p.value} value={p.value}>
              {getProviderLabel(p.value)}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="text-sm font-medium">
          <span className="text-destructive">*</span>{" "}
          {t.settings.model.modelList.label}
        </label>
        <p className="mt-0.5 text-[11px] text-muted-foreground">
          {t.settings.model.modelList.hint}
        </p>
        <ul className="mt-2 space-y-1.5">
          {models.map((id, idx) => (
            <li key={`add-model-${idx}`} className="flex items-center gap-1.5">
              <span className="w-4 shrink-0 text-right text-xs text-muted-foreground/60 tabular-nums">
                {idx === 0 ? "★" : idx === models.length - 1 ? "▴" : "·"}
              </span>
              <Input
                className="flex-1 font-mono text-xs"
                placeholder={
                  idx === 0
                    ? t.settings.model.modelIdPlaceholder
                    : t.settings.model.modelIdPlaceholder
                }
                value={id}
                onChange={(e) => handleModelChange(idx, e.target.value)}
              />
              <button
                type="button"
                className={cn(
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border-default text-muted-foreground transition-colors",
                  "hover:border-destructive/50 hover:bg-destructive/10 hover:text-destructive",
                  "disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-border-default disabled:hover:bg-transparent disabled:hover:text-muted-foreground",
                )}
                onClick={() => handleModelRemove(idx)}
                disabled={models.length <= 1}
                title={t.settings.model.modelList.removeTooltip}
                aria-label={t.settings.model.modelList.removeTooltip}
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
          <PlusIcon className="mr-1 h-3 w-3" />{" "}
          {t.settings.model.modelList.addButton}
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
                  className="rounded-md border border-border-default bg-muted/40 px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                  title={t.settings.model.fillModelId ?? "Fill this model ID"}
                >
                  {m}
                </button>
              ))}
            </div>
          );
        })()}
      </div>

      <div>
        <label className="text-sm font-medium">
          {t.settings.model.displayName}
        </label>
        <Input
          className="mt-1"
          placeholder={t.settings.model.displayNamePlaceholder}
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-sm font-medium flex items-center justify-between gap-2">
            <span>
              {getProviderLabel(provider) || t.settings.model.provider}{" "}
              {t.settings.model.apiKey}
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
                  {t.settings.model.getApiKey}
                </a>
              );
            })()}
          </label>
          <div className="relative mt-1">
            <Input
              className="pr-10"
              type={showKey ? "text" : "password"}
              placeholder={t.settings.model.apiKeyPlaceholder}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <button
              type="button"
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              onClick={() => setShowKey(!showKey)}
            >
              {showKey ? (
                <EyeOffIcon className="size-4" />
              ) : (
                <EyeIcon className="size-4" />
              )}
            </button>
          </div>
        </div>
        <div>
          <label className="text-sm font-medium">
            {t.settings.model.apiProtocol}
          </label>
          <select
            className="mt-1 flex h-9 w-full rounded-lg border border-input bg-transparent px-3 py-1 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            value={protocol}
            onChange={(e) => setProtocol(e.target.value)}
          >
            {PROTOCOLS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="text-sm font-medium">
          {t.settings.model.baseUrlLabel}
        </label>
        <Input
          className="mt-1"
          placeholder={t.settings.model.baseUrlPlaceholder}
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
        />
      </div>

      {/* Extra HTTP headers — collapsed by default to keep the form
          uncluttered for the 95% case. Needed for APIs that gate on
          User-Agent (Kimi Coding) or require custom routing headers. */}
      <div className="rounded-lg border border-border-default bg-muted/20">
        <button
          type="button"
          onClick={() => setShowHeaders((v) => !v)}
          className="flex w-full items-center justify-between px-3 py-2 text-sm font-medium hover:bg-muted/40"
        >
          <span>
            {t.settings.model.extraHeadersTitle}
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
          <div className="space-y-2 border-t border-border-default px-3 py-3">
            <textarea
              value={headersText}
              onChange={(e) => setHeadersText(e.target.value)}
              placeholder={t.settings.model.extraHeadersPlaceholder}
              spellCheck={false}
              rows={3}
              className="w-full resize-y rounded-md border border-input bg-transparent px-3 py-2 font-mono text-xs shadow-xs focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
            <p className="text-[11px] text-muted-foreground">
              {t.settings.model.extraHeadersHint}
            </p>
          </div>
        )}
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="flex items-center gap-2 pt-6">
          <Switch checked={thinking} onCheckedChange={setThinking} />{" "}
          <span className="text-sm">{t.settings.model.thinkingLabel}</span>
        </div>
        <div className="flex items-center gap-2 pt-6">
          <Switch checked={vision} onCheckedChange={setVision} />{" "}
          <span className="text-sm">{t.settings.model.visionLabel}</span>
        </div>
      </div>

      {/* Test status + buttons */}
      <div className="flex items-center justify-between rounded-lg border border-border px-4 py-3">
        <div className="flex items-center gap-2 text-sm">
          {testStatus === "idle" && (
            <>
              <div className="h-2.5 w-2.5 rounded-lg bg-muted-foreground/40" />
              <span className="text-muted-foreground">
                {t.settings.model.testFailed}
              </span>
            </>
          )}
          {testStatus === "testing" && (
            <>
              <Loader2Icon className="h-4 w-4 animate-spin text-blue-500" />
              <span className="text-blue-500">{t.common.loading}</span>
            </>
          )}
          {testStatus === "success" && (
            <>
              <CheckCircle2Icon className="h-4 w-4 text-green-500" />
              <span className="text-green-500">
                {testMessage}
                {testLatency != null ? ` (${testLatency}ms)` : ""}
              </span>
            </>
          )}
          {testStatus === "fail" && (
            <>
              <XCircleIcon className="h-4 w-4 text-destructive" />
              <span className="text-destructive">{testMessage}</span>
            </>
          )}
          <span className="text-xs text-muted-foreground ml-2">
            {t.settings.model.testEndpointHint}
          </span>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            className="text-destructive border-destructive hover:bg-destructive/10"
            onClick={onCancel}
          >
            {t.common.cancel}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleTest}
            disabled={testStatus === "testing"}
          >
            <WifiIcon className="mr-1 h-3 w-3" /> {t.settings.model.diagnose}
          </Button>
        </div>
      </div>

      {error && <div className="text-sm text-destructive">{error}</div>}

      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          {t.common.cancel}
        </Button>
        <Button
          className="bg-orange-500 hover:bg-orange-600 text-white"
          onClick={handleSave}
          disabled={saving}
        >
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
  const [scanStatus, setScanStatus] = useState<
    "idle" | "scanning" | "done" | "error"
  >("idle");
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

  useEffect(() => {
    const handler = () => {
      void handleScan();
    };
    window.addEventListener(LOCAL_MODEL_SCAN_EVENT, handler);
    return () => window.removeEventListener(LOCAL_MODEL_SCAN_EVENT, handler);
  }, [handleScan]);

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
            `${t.settings.model.localModels.importFailed}: ${
              data.error || `HTTP ${res.status}`
            }`,
          );
          return;
        }
        toast.success(t.settings.model.localModels.imported);
        onImported?.();
      } catch (e) {
        swallow(e);
        toast.error(t.settings.model.localModels.importFailed);
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
      t.settings.model.localModels.importFailed,
      t.settings.model.localModels.imported,
    ],
  );

  return (
    <SettingsSection
      title={t.settings.model.localModels.title}
      description={t.settings.model.localModels.subtitle}
    >
      <div className="rounded-lg border border-border overflow-hidden">
        {/* Header bar · scan button + live status badge. Lives
            outside the collapsible so the operator can see whether
            a scan has run at a glance, even when the results list
            is collapsed. */}
        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">
              {t.settings.model.localModels.providerHint}
            </span>
            {scanStatus === "scanning" && (
              <Loader2Icon className="size-3.5 animate-spin text-blue-500" />
            )}
            {scanStatus === "done" && services.length > 0 && (
              <span className="inline-flex items-center rounded-md border border-green-200 bg-green-50 px-1.5 py-0.5 text-[10px] font-medium text-green-700 dark:border-green-500/40 dark:bg-green-500/10 dark:text-green-400">
                {t.settings.model.localModels.modelsCount(services.length)}
              </span>
            )}
            {scanStatus === "done" && services.length === 0 && (
              <span className="inline-flex items-center rounded-md border border-border bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground dark:border-muted-foreground/40 dark:bg-muted-foreground/10 dark:text-muted-foreground">
                {t.settings.model.localModels.empty}
              </span>
            )}
            {scanStatus === "error" && (
              <span className="inline-flex items-center rounded-md border border-destructive/30 bg-destructive/10 px-1.5 py-0.5 text-[10px] font-medium text-destructive">
                {t.settings.model.localModels.serviceStatus.error}
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
              ? t.settings.model.localModels.scanButtonScanning
              : t.settings.model.localModels.scanButton}
          </Button>
        </div>

        {/* Results list · only renders after a scan has been run.
            Empty state is inline rather than a separate screen so
            the operator's eye doesn't have to leave the section. */}
        {scanStatus !== "idle" && (
          <div className="border-t border-border divide-y divide-border">
            {services.length === 0 ? (
              <div className="px-4 py-6 text-sm text-muted-foreground">
                {t.settings.model.localModels.emptyHint}
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
                            {t.settings.model.localModels.serviceStatus.ok}
                          </span>
                        )}
                        {svc.status === "empty" && (
                          <span className="inline-flex shrink-0 items-center rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:border-amber-500/40 dark:bg-amber-500/10 dark:text-amber-400">
                            {t.settings.model.localModels.serviceStatus.empty}
                          </span>
                        )}
                        {svc.status === "error" && (
                          <span className="inline-flex shrink-0 items-center rounded-md border border-destructive/30 bg-destructive/10 px-1.5 py-0.5 text-[10px] font-medium text-destructive">
                            {t.settings.model.localModels.serviceStatus.error}
                          </span>
                        )}
                      </div>
                      <div className="mt-0.5 text-xs text-muted-foreground">
                        {svc.status === "ok" &&
                          t.settings.model.localModels.modelsCount(
                            svc.models.length,
                          )}
                        {svc.status === "empty" &&
                          t.settings.model.localModels.serviceStatus.empty}
                        {svc.error &&
                          `${t.settings.model.localModels.serviceStatus.error}: ${svc.error}`}
                      </div>
                    </div>
                    <Button
                      variant="default"
                      size="sm"
                      onClick={() => handleImport(svc)}
                      disabled={!canImport}
                    >
                      {busy
                        ? t.settings.model.localModels.importingButton
                        : t.settings.model.localModels.importButton}
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
