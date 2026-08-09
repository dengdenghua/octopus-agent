import { ChevronDownIcon, PlusIcon, SparklesIcon } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import type { ReasoningEffort } from "@/core/threads";
import { cn } from "@/lib/utils";

/** Minimal slice of the backend model shape used by the picker. */
export interface PickerModel {
  name: string;
  display_name?: string | null;
  description?: string | null;
  model?: string | null;
  supports_thinking?: boolean;
  supports_vision?: boolean;
  [key: string]: unknown;
}

interface OfficialMeta {
  key: string;
  displayName: string;
  id: string;
  multiplier: string;
  recommended: boolean;
}

/**
 * Octopus Mix — the built-in mixture-of-agents virtual model. Surfaces in the
 * Official tab when the backend advertises ``octopus-mix`` via /api/llm-models.
 */
const MIX_META: OfficialMeta = {
  key: "octopus-mix",
  id: "octopus-mix",
  displayName: "Octopus Mix",
  multiplier: "Mix",
  recommended: true,
};

const REASONING_EFFORT_OPTIONS: ReasoningEffort[] = [
  "low",
  "medium",
  "high",
  "xhigh",
];

function reasoningEffortLabel(
  effort: ReasoningEffort,
  t: Translations,
): string {
  switch (effort) {
    case "minimal":
      return t.inputBox.reasoningEffortMinimal;
    case "low":
      return t.inputBox.reasoningEffortLow;
    case "medium":
      return t.inputBox.reasoningEffortMedium;
    case "high":
      return t.inputBox.reasoningEffortHigh;
    case "xhigh":
      return t.inputBox.reasoningEffortXHigh;
    case "max":
      return t.inputBox.reasoningEffortMax;
  }
}

function ReasoningEffortSetting({
  value,
  disabled,
  onChange,
}: {
  value?: ReasoningEffort;
  disabled?: boolean;
  onChange: (effort: ReasoningEffort) => void;
}) {
  const { t } = useI18n();
  const current = value === "max" ? "xhigh" : (value ?? "medium");
  const title = t.inputBox.reasoningEffort;

  return (
    <div className="mx-1 mt-1 border-t border-border-default pt-1">
      <div className="mb-0.5 flex items-center justify-between px-1">
        <span className="text-xs font-medium text-muted-foreground/70">
          {title}
        </span>
        <span className="text-xs text-muted-foreground">
          {t.inputBox.reasoningEffortCurrent(reasoningEffortLabel(current, t))}
        </span>
      </div>
      <div
        role="radiogroup"
        aria-label={title}
        className="grid grid-cols-4 gap-0.5 rounded-md bg-muted/35 p-0.5"
      >
        {REASONING_EFFORT_OPTIONS.map((effort) => {
          const selected = effort === current;
          return (
            <button
              key={effort}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              onClick={(event) => {
                event.preventDefault();
                onChange(effort);
              }}
              className={cn(
                "h-5 rounded-md px-1 text-xs transition-colors",
                selected
                  ? "bg-background text-foreground shadow-[var(--shadow-xs)]"
                  : "text-muted-foreground hover:text-foreground",
                "disabled:cursor-not-allowed disabled:opacity-45",
              )}
            >
              {reasoningEffortLabel(effort, t)}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Single row in the list. `right` is the trailing muted text. */
function PickerRow({
  label,
  right,
  badge,
  selected,
  disabled,
  onSelect,
}: {
  label: ReactNode;
  right?: ReactNode;
  badge?: ReactNode;
  selected?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onSelect}
      className={cn(
        // Match sidebar NavRow language: h-8, opacity-based emphasis,
        // monochrome. No color accent — selection reads via opacity and
        // a 2px leading bar the way active nav items do.
        "group/row relative flex h-7 w-full items-center gap-1.5 rounded-md px-2 text-left text-xs opacity-75 transition-[opacity,background-color]",
        "hover:opacity-100 hover:bg-muted/40",
        disabled &&
          "cursor-not-allowed opacity-35 hover:opacity-35 hover:bg-transparent",
        selected &&
          !disabled &&
          "opacity-100 bg-[color:color-mix(in_oklch,var(--sidebar-accent)_55%,transparent)] before:absolute before:left-0 before:top-1 before:bottom-1 before:w-[2px] before:rounded-r before:bg-primary/70",
      )}
    >
      <span className="flex min-w-0 flex-1 items-center gap-1.5 truncate">
        <span className="truncate">{label}</span>
        {badge}
      </span>
      {right !== undefined && (
        <span className="shrink-0 text-xs tabular-nums text-muted-foreground/70 group-hover/row:text-muted-foreground transition-colors">
          {right}
        </span>
      )}
    </button>
  );
}

export interface ModelPickerProps {
  models: PickerModel[];
  value?: string | null;
  onChange: (name: string) => void;
  reasoningEffort?: ReasoningEffort;
  reasoningEffortDisabled?: boolean;
  onReasoningEffortChange?: (effort: ReasoningEffort) => void;
  /** Render prop for a custom trigger. */
  renderTrigger?: (selected: PickerModel | undefined) => ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function ModelPicker({
  models,
  value,
  onChange,
  reasoningEffort,
  reasoningEffortDisabled,
  onReasoningEffortChange,
  renderTrigger,
  open: controlledOpen,
  onOpenChange,
}: ModelPickerProps) {
  const { t } = useI18n();
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  const open = controlledOpen ?? uncontrolledOpen;
  const setOpen = onOpenChange ?? setUncontrolledOpen;

  // "auto" is a UI-only sentinel — the backend reads it as "let the
  // ModelRouter middleware pick per-task". We resolve it to a synthetic
  // PickerModel so the trigger + highlighted row can render a label.
  const isAutoMode = (value ?? "").trim().toLowerCase() === "auto";
  const selected = useMemo(
    () =>
      isAutoMode
        ? {
            name: "auto",
            display_name: t.modelPicker.autoModelLabel,
            description: t.modelPicker.autoModelDescription,
          }
        : (models.find((m) => m.name === value) ?? models[0]),
    [
      isAutoMode,
      value,
      models,
      t.modelPicker.autoModelLabel,
      t.modelPicker.autoModelDescription,
    ],
  );

  const officialMetas = useMemo(() => {
    // Surface the built-in Mix model in the Official tab only when the
    // backend actually advertises it (via /api/llm-models).
    const hasMix = models.some(
      (m) => m.name === MIX_META.id || m.model === MIX_META.id,
    );
    return hasMix ? [MIX_META] : [];
  }, [models]);

  const selectedMeta = useMemo(() => {
    if (!selected) return null;
    return (
      officialMetas.find(
        (meta) =>
          meta.id === selected.name ||
          meta.id === selected.model ||
          meta.displayName === selected.display_name,
      ) ?? null
    );
  }, [officialMetas, selected]);


  /**
   * One flat list, in the order the backend returned.
   *
   * The dropdown used to split Official / Custom across tabs. With a handful
   * of configured endpoints that cost two clicks to reach a neighbouring
   * model and hid the selected row behind whichever tab opened by default.
   * Unconfigured official rows are dropped here rather than rendered grey —
   * they are a settings concern, and a column of unclickable placeholders is
   * the bulk of what made this panel feel heavy.
   *
   * ``::1m`` variants are folded into their base row (see longContextFor) so
   * one model occupies one line.
   */
  const flatEntries = useMemo(
    () => models.filter((m) => m.context_profile !== "1m"),
    [models],
  );

  /**
   * Map base model name → its ``::1m`` sibling, so a row can offer the
   * long-context variant inline instead of as a second, near-identical entry.
   */
  const longContextFor = useMemo(() => {
    const map = new Map<string, PickerModel>();
    for (const m of models) {
      if (m.context_profile !== "1m") continue;
      map.set(m.name.replace(/::1m$/, ""), m);
    }
    return map;
  }, [models]);

  const handleSelect = (name: string) => {
    onChange(name);
    setOpen(false);
  };

  // Clean up model name: remove trailing question marks and whitespace
  const cleanModelName = (name: string | undefined | null): string => {
    if (!name) return "";
    return name.replace(/\?+$/, "").trim();
  };

  // The trigger keeps the Auto sparkles + label + chevron (the
  // model-name + multiplier header and the in-list Auto row were the
  // red-box duplicates that got removed). The Auto toggle now lives
  // exclusively on the Auto row at the top of the dropdown panel
  // — one control, one backing state, two visible surfaces.
  const triggerButton = (
    <button
      type="button"
      data-testid="model-picker-trigger"
      className={cn(
        "inline-flex h-8 min-w-0 items-center gap-1 rounded-lg border border-transparent",
        "bg-transparent px-2 py-1 text-xs text-muted-foreground transition outline-none",
        "hover:border-border-default hover:bg-muted/60 hover:text-foreground",
        "data-[state=open]:bg-muted data-[state=open]:text-foreground",
      )}
      aria-label={t.modelPicker.selectModel}
      title={t.modelPicker.selectModel}
    >
      {isAutoMode && <SparklesIcon className="size-3 shrink-0 text-info" />}
      <span className="truncate max-w-[var(--text-truncate-md)]">
        {isAutoMode
          ? t.modelPicker.autoModelLabel
          : cleanModelName(selectedMeta?.displayName) ||
            cleanModelName(selected?.display_name) ||
            cleanModelName(selected?.name) ||
            t.modelPicker.selectModel}
      </span>
      <ChevronDownIcon className="size-3 opacity-60" />
    </button>
  );

  // Default trigger composition: the trigger button alone is
  // wrapped by DropdownMenuTrigger asChild. The Auto switch used
  // to sit to the left of the trigger, but it duplicates the Auto
  // row at the top of the dropdown panel — same backing state, same
  // "auto" sentinel — so the inline switch is redundant and removed.
  const defaultTriggerContainer = (
    <DropdownMenuTrigger asChild>{triggerButton}</DropdownMenuTrigger>
  );

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      {renderTrigger ? (
        <DropdownMenuTrigger asChild>
          {renderTrigger(selected)}
        </DropdownMenuTrigger>
      ) : (
        defaultTriggerContainer
      )}
      <DropdownMenuContent
        data-testid="model-picker-menu"
        align="end"
        side="top"
        sideOffset={6}
        className="w-56 p-0"
      >
        {/* Auto row lives above the tabs so the user can flip into
            smart-routing mode without scrolling through the model
            list. The trigger button is the canonical model label;
            this row only restates the Auto state with a sparkles
            icon + 智能 badge so the option stays discoverable. */}
        <div className="p-1 pb-0">
          <PickerRow
            label={
              <span className="inline-flex items-center gap-1.5">
                <SparklesIcon className="size-3 shrink-0 text-info" />
                {t.modelPicker.autoModelLabel}
              </span>
            }
            right={
              <span className="rounded border border-info/40 px-1 py-0 text-xs text-info">
                {t.modelPicker.autoModelBadge}
              </span>
            }
            selected={isAutoMode}
            onSelect={() => handleSelect("auto")}
          />
        </div>

        {onReasoningEffortChange && (
          <ReasoningEffortSetting
            value={reasoningEffort}
            disabled={reasoningEffortDisabled}
            onChange={onReasoningEffortChange}
          />
        )}

        <div className="p-1 pt-0.5">
          <div className="flex flex-col gap-0.5">
            {flatEntries.length === 0 ? (
              <div className="px-2 py-4 text-center text-xs text-muted-foreground">
                {t.modelPicker.noCustomModels}
              </div>
            ) : (
              flatEntries.map((m) => {
                const long = longContextFor.get(m.name);
                return (
                  <PickerRow
                    key={m.name}
                    label={m.display_name || m.name}
                    right={
                      long ? (
                        <button
                          type="button"
                          data-testid={`model-picker-1m-${m.name}`}
                          title={t.modelPicker.longContextHint}
                          onClick={(e) => {
                            // The row itself selects the default context
                            // window; this affordance is the only way to
                            // reach the 1M variant now that it no longer
                            // occupies its own row.
                            e.stopPropagation();
                            handleSelect(long.name);
                          }}
                          className={cn(
                            "rounded border px-1 text-xs transition",
                            long.name === value
                              ? "border-primary/60 text-foreground"
                              : "border-border-default/60 text-muted-foreground hover:text-foreground",
                          )}
                        >
                          1M
                        </button>
                      ) : undefined
                    }
                    selected={m.name === value}
                    onSelect={() => handleSelect(m.name)}
                  />
                );
              })
            )}
          </div>
          <div className="mt-1.5 border-t pt-1.5">
            <button
              type="button"
              onClick={() => {
                setOpen(false);
                // Settings dialog hosts the "models" page where the
                // user manages api_base / api_key entries.
                window.dispatchEvent(
                  new CustomEvent("octopus:open-settings", {
                    detail: { tab: "models" },
                  }),
                );
              }}
              className={cn(
                "flex w-full items-center justify-center gap-1.5 rounded-md",
                "px-2 py-1.5 text-xs text-muted-foreground transition",
                "hover:bg-accent hover:text-foreground",
              )}
            >
              <PlusIcon className="size-3.5" />
              {t.modelPicker.addModel}
            </button>
          </div>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
