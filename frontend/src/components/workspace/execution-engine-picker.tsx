import { CheckIcon, SparklesIcon } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import { engineVerificationLabel, type EngineCapabilityChecks } from "@/core/agents/engine-capability-checks";
import type { ExecutionEnginePreference } from "@/core/realtime/execution-policy";

const REASONS: Record<string, [string, string]> = {
  checking: ["正在检查 Codex 配置", "Checking Codex configuration"],
  disabled: ["Codex 引擎未启用", "Codex is disabled"],
  tools_unavailable: ["共享工具尚未就绪", "Shared tools are not ready"],
  executable_unavailable: [
    "需要安装或配置 Codex",
    "Install or configure Codex",
  ],
  model_incompatible: [
    "选取后，在输入框选择订阅或 API 模型",
    "Select this engine, then choose a subscription or API model",
  ],
  account_required: [
    "需要在模型设置中连接 Codex 账号",
    "Connect a Codex account in model settings",
  ],
  account_unavailable: [
    "请检查 Codex 账号设置",
    "Check Codex account settings",
  ],
  workspace_required: ["需要先选择工作目录", "Select a workspace first"],
  configuration_unavailable: [
    "暂时无法读取 Codex 配置",
    "Codex configuration is unavailable",
  ],
};

/** Official OpenCode square mark.
 * Source: anomalyco/opencode packages/ui/src/assets/favicon/favicon.svg
 */
function OpenCodeIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 512 512"
      className={className}
      data-testid="opencode-logo"
      aria-hidden="true"
    >
      <rect width="512" height="512" fill="#131010" />
      <path d="M320 224V352H192V224H320Z" fill="#5A5858" />
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M384 416H128V96H384V416ZM320 160H192V352H320V160Z"
        fill="#FFFFFF"
      />
    </svg>
  );
}

/** Exact light/dark Blossom assets shipped with the official Codex desktop app. */
function CodexIcon({ className }: { className?: string }) {
  return (
    <span className={className} data-testid="codex-logo" aria-hidden="true">
      <img
        src="/brands/codex-blossom-on-light.png"
        alt=""
        className="size-full object-contain dark:hidden"
      />
      <img
        src="/brands/codex-blossom-on-dark.png"
        alt=""
        className="hidden size-full object-contain dark:block"
      />
    </span>
  );
}

export function ExecutionEnginePicker({
  value,
  resolvedEngine,
  onChange,
  codexAvailable,
  unavailableReason,
  opencodeAvailable = false,
  opencodeUnavailableReason,
  codexCapabilityChecks,
  opencodeCapabilityChecks,
  disabled,
}: {
  value: ExecutionEnginePreference;
  /** Engine selected by Auto for this turn. The picker remains on Auto, while
   * the trigger tells the user which native identity will actually run. */
  resolvedEngine?: Exclude<ExecutionEnginePreference, "auto">;
  onChange: (value: ExecutionEnginePreference) => void;
  codexAvailable: boolean;
  unavailableReason?: string | null;
  opencodeAvailable?: boolean;
  opencodeUnavailableReason?: string | null;
  codexCapabilityChecks?: EngineCapabilityChecks;
  opencodeCapabilityChecks?: EngineCapabilityChecks;
  disabled?: boolean;
}) {
  const { locale } = useI18n();
  const zh = locale.startsWith("zh");
  // Model readiness gates execution, not access to the engine's model picker.
  const codexSelectable =
    codexAvailable || unavailableReason === "model_incompatible";
  const title = zh ? "执行引擎" : "Execution engine";
  const labels = {
    auto: zh ? "自动" : "Auto",
    octopus: zh ? "原生兼容模式" : "Legacy native mode",
    codex: "Codex",
    opencode: "OpenCode",
  };
  const unavailable = !codexAvailable
    ? (REASONS[unavailableReason ?? "configuration_unavailable"] ??
        REASONS.configuration_unavailable)![zh ? 0 : 1]
    : null;
  const selectedUnavailable =
    value === "codex"
      ? unavailable
      : value === "opencode" && !opencodeAvailable
        ? opencodeUnavailableReason ||
          (zh
            ? "请检查 OpenCode 安装和模型配置"
            : "Check the OpenCode installation and model configuration")
        : null;
  const visibleEngine = value === "auto" ? resolvedEngine : value;
  const triggerTitle =
    selectedUnavailable ||
    `${title}: ${labels[value]}${value === "auto" && resolvedEngine ? ` · ${labels[resolvedEngine]}` : ""}`;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label={`${title}: ${labels[value]}`}
          title={triggerTitle}
          data-testid="execution-engine-trigger"
          className="relative flex size-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground outline-none transition hover:bg-muted/60 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/30 disabled:opacity-50"
        >
          {visibleEngine === "opencode" ? (
            <OpenCodeIcon className="size-3.5 shrink-0" />
          ) : visibleEngine === "codex" ? (
            <CodexIcon className="size-3.5 shrink-0" />
          ) : (
            <SparklesIcon className="size-3.5 shrink-0" />
          )}
          {selectedUnavailable ? (
            <span
              className="absolute right-1 top-1 size-1.5 rounded-full bg-destructive"
              aria-hidden="true"
            />
          ) : null}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <p className="px-2 py-2 text-ui font-medium">
          {zh ? "执行引擎" : "Execution engine"}
        </p>
        {value === "octopus" ? (
          <p className="px-2 pb-2 text-ui text-muted-foreground">
            {zh
              ? "此会话保留了旧版原生配置，可切换到下方执行引擎。"
              : "This session retains a legacy native setting. Choose an engine below to switch."}
          </p>
        ) : null}
        {(["auto", "opencode", "codex"] as const).map((engine) => (
          <DropdownMenuItem
            key={engine}
            disabled={
              (engine === "codex" && !codexSelectable) ||
              (engine === "opencode" && !opencodeAvailable)
            }
            onSelect={() => onChange(engine)}
            className={`items-start gap-2.5 py-2 ${value === engine ? "bg-accent" : ""}`}
          >
            {engine === "auto" ? (
              <SparklesIcon className="mt-0.5 size-4 shrink-0" />
            ) : engine === "opencode" ? (
              <OpenCodeIcon className="mt-0.5 size-4 shrink-0" />
            ) : (
              <CodexIcon className="mt-0.5 size-4 shrink-0" />
            )}
            <span className="min-w-0 flex-1">
              <span className="block font-medium">{labels[engine]}</span>
              <span className="mt-0.5 block text-ui leading-relaxed text-muted-foreground">
                {engine === "auto"
                  ? zh
                    ? `按任务自动选择${resolvedEngine ? ` · 当前 ${labels[resolvedEngine]}` : ""}`
                    : `Choose per task${resolvedEngine ? ` · currently ${labels[resolvedEngine]}` : ""}`
                  : engine === "opencode"
                    ? !opencodeAvailable
                      ? opencodeUnavailableReason ||
                        (zh
                          ? "请检查 OpenCode 安装和模型配置"
                          : "Check the OpenCode installation and model configuration")
                      : zh
                        ? "使用 OpenCode 身份，支持官方免费模型"
                        : "Use the OpenCode identity with official free or connected Zen models"
                    : (unavailable ??
                      (zh
                        ? "使用 Codex 身份执行当前任务"
                        : "Run this task with the Codex identity"))}
              </span>
              {(engine === "codex" && codexAvailable) || (engine === "opencode" && opencodeAvailable) ? (
                <span className="mt-0.5 block text-ui leading-relaxed text-muted-foreground">
                  {engineVerificationLabel(engine === "codex" ? codexCapabilityChecks : opencodeCapabilityChecks, zh)}
                </span>
              ) : null}
            </span>
            {value === engine ? (
              <CheckIcon className="mt-0.5 size-4 shrink-0 text-primary" />
            ) : null}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Historical evidence only. Never infer an engine from today's role or setting. */
export function ExecutionEngineBadge({ engine }: { engine: unknown }) {
  const { locale } = useI18n();
  if (engine !== "codex" && engine !== "octopus" && engine !== "opencode")
    return null;
  const name =
    engine === "opencode" ? "OpenCode" : engine === "codex" ? "Codex" : "Echo";
  return (
    <span
      className="mb-1 inline-block rounded border border-border/60 px-1.5 text-[10px] leading-4 text-muted-foreground"
      title={
        locale.startsWith("zh")
          ? `实际执行引擎：${name}`
          : `Executed by ${name}`
      }
      data-execution-engine={engine}
    >
      {name}
    </span>
  );
}
