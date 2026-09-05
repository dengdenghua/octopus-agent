import { ChevronDownIcon } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
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
    "需要在模型设置中选择兼容的模型",
    "Choose a compatible model in model settings",
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
  orchestration_required: [
    "团队由 Octopus 编排，成员任务可使用 Codex",
    "Octopus coordinates teams; member tasks can use Codex",
  ],
  configuration_unavailable: [
    "暂时无法读取 Codex 配置",
    "Codex configuration is unavailable",
  ],
};

export function ExecutionEnginePicker({
  value,
  onChange,
  codexAvailable,
  unavailableReason,
  disabled,
}: {
  value: ExecutionEnginePreference;
  onChange: (value: ExecutionEnginePreference) => void;
  codexAvailable: boolean;
  unavailableReason?: string | null;
  disabled?: boolean;
}) {
  const { locale } = useI18n();
  const zh = locale.startsWith("zh");
  const title = zh ? "执行引擎" : "Execution engine";
  const labels = {
    auto: zh ? "自动" : "Auto",
    octopus: "Octopus",
    codex: "Codex",
  };
  const unavailable = !codexAvailable
    ? (REASONS[unavailableReason ?? "configuration_unavailable"] ??
        REASONS.configuration_unavailable)![zh ? 0 : 1]
    : null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label={`${title}: ${labels[value]}`}
          title={value === "codex" && unavailable ? unavailable : title}
          className="flex h-7 shrink-0 items-center gap-1 rounded-md px-2 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
        >
          {zh ? "引擎：" : "Engine: "}{labels[value]}
          {value === "codex" && unavailable ? (
            <span aria-hidden="true">· !</span>
          ) : null}
          <ChevronDownIcon className="size-3" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        {(["auto", "octopus", "codex"] as const).map((engine) => (
          <DropdownMenuItem
            key={engine}
            disabled={engine === "codex" && !codexAvailable}
            onSelect={() => onChange(engine)}
            className="flex flex-col items-start gap-1"
          >
            <span>
              {labels[engine]}
              {value === engine ? " ✓" : ""}
            </span>{" "}
            <span className="text-xs text-muted-foreground">
              {engine === "auto"
                ? zh
                  ? "代码优先 Codex，办公与流程优先 Octopus"
                  : "Codex for code; Octopus for tools and workflows"
                : engine === "octopus"
                  ? zh
                    ? "使用原生工具与任务流程"
                    : "Use native tools and task workflows"
                  : (unavailable ??
                    (zh
                      ? "使用 Codex 执行当前角色的任务"
                      : "Run this role's task with Codex"))}
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Historical evidence only. Never infer an engine from today's role or setting. */
export function ExecutionEngineBadge({ engine }: { engine: unknown }) {
  const { locale } = useI18n();
  if (engine !== "codex" && engine !== "octopus") return null;
  const name = engine === "codex" ? "Codex" : "Octopus";
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
