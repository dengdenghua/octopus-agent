import { useQueryClient } from "@tanstack/react-query";
import { ChevronDownIcon, PlusIcon, SparklesIcon } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/providers/AuthProvider";
import { toast } from "sonner";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { useMoliliLink } from "@/core/molili";
import type { ReasoningEffort } from "@/core/threads";
import { cn } from "@/lib/utils";

/**
 * Official LLM endpoint baked in here as a fallback for one-click enabling.
 * The visible official model catalog itself comes from the backend.
 */
const MOLILI_LLM_BASE_URL = "https://molili.8kbl.com/molili-agi/chatApi/v1";

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

interface OfficialCatalogModel {
  id: string;
  display_name?: string | null;
  multiplier?: string | null;
  recommended?: boolean;
}

function metaFromCatalog(m: OfficialCatalogModel): OfficialMeta {
  return {
    key: m.id,
    id: m.id,
    displayName: m.display_name || m.id,
    multiplier: m.multiplier || "1.0x",
    recommended: Boolean(m.recommended),
  };
}

/**
 * Very small helper — given a custom model, derive a short right-column
 * label (provider hint). Falls back to the backend `model` field, then
 * to nothing.
 */
function rightHint(m: PickerModel): string {
  const probe =
    `${m.name} ${m.model ?? ""} ${m.display_name ?? ""}`.toLowerCase();
  for (const [needle, label] of [
    ["claude", "Claude"],
    ["gpt", "OpenAI"],
    ["openai", "OpenAI"],
    ["gemini", "Gemini"],
    ["mistral", "Mistral"],
    ["llama", "Llama"],
  ] as const) {
    if (probe.includes(needle)) return label;
  }
  return m.model || "";
}

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
    <div className="mx-1 mt-1 border-t border-border/60 pt-1">
      <div className="mb-0.5 flex items-center justify-between px-1">
        <span className="text-[10px] font-medium text-muted-foreground/70">
          {title}
        </span>
        <span className="text-[10px] text-muted-foreground">
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
                "h-5 rounded-[5px] px-1 text-[10px] transition-colors",
                selected
                  ? "bg-background text-foreground shadow-sm"
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
        "group/row relative flex h-7 w-full items-center gap-1.5 rounded-md px-2 text-left text-[12px] opacity-75 transition-[opacity,background-color] duration-150",
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
        <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/70 group-hover/row:text-muted-foreground transition-colors">
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
  const navigate = useNavigate();
  // Guest mode keeps official models visible but disabled.
  // Custom models remain fully selectable before login. The custom tab
  // stays visible and fully functional so guests can BYOK against
  // OpenAI / Kimi / any OpenAI-compat endpoint.
  const { isGuest } = useAuth();
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

  const [moliliPack, setMoliliPack] = useState<OfficialCatalogModel[]>([]);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(
          `${getBackendBaseURL()}/api/molili/openai/v1/catalog`,
        );
        if (!r.ok) return;
        const j = (await r.json()) as { data?: OfficialCatalogModel[] };
        if (cancelled) return;
        const data = Array.isArray(j?.data) ? j.data : [];
        setMoliliPack(
          data.filter(
            (m): m is OfficialCatalogModel =>
              !!m.id && !/^(auto|molili)$/i.test(m.id),
          ),
        );
      } catch (err) {
        if (!cancelled) {
          console.warn(
            "[model-picker] official model catalog unavailable:",
            err,
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const officialMetas = useMemo(
    () => moliliPack.map(metaFromCatalog),
    [moliliPack],
  );

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

  const [officialEntries, customEntries] = useMemo(() => {
    const official: {
      meta: OfficialMeta;
      model: PickerModel;
      // True when the local /api/models has no matching entry — we'll
      // deep-link to the settings page instead of dispatching a run.
      unconfigured: boolean;
    }[] = [];
    const custom: PickerModel[] = [];
    const consumedMetaKeys = new Set<string>();
    for (const m of models) {
      const meta = officialMetas.find(
        (x) =>
          x.id === m.name ||
          x.id === m.model ||
          x.displayName === m.display_name,
      );
      if (meta && !consumedMetaKeys.has(meta.key)) {
        consumedMetaKeys.add(meta.key);
        official.push({ meta, model: m, unconfigured: false });
      } else {
        custom.push(m);
      }
    }
    for (const meta of officialMetas) {
      if (consumedMetaKeys.has(meta.key)) continue;
      consumedMetaKeys.add(meta.key);
      official.push({
        meta,
        model: { name: meta.id, display_name: meta.displayName },
        unconfigured: true,
      });
    }
    return [official, custom];
  }, [models, officialMetas]);

  const selectedForDisplay = useMemo(() => {
    if (!isGuest || isAutoMode || !selectedMeta) return selected;
    return customEntries[0];
  }, [customEntries, isAutoMode, isGuest, selected, selectedMeta]);

  const selectedMetaForDisplay =
    selectedForDisplay === selected ? selectedMeta : null;

  const handleSelect = (name: string) => {
    onChange(name);
    setOpen(false);
  };

  useEffect(() => {
    if (!isGuest || !selected || customEntries.length === 0) return;
    if (selectedMeta) {
      const fallback = customEntries[0];
      if (fallback) onChange(fallback.name);
    }
  }, [customEntries, isGuest, onChange, selected, selectedMeta]);

  const moliliLink = useMoliliLink();
  const queryClient = useQueryClient();
  const [enabling, setEnabling] = useState<string | null>(null);

  /* Implementation note. */
  const handleSelectUnconfigured = async (
    meta: OfficialMeta,
    upstreamId: string,
  ) => {
    const moliliUserId = moliliLink.data?.molili_user_id;
    if (!moliliUserId) {
      setOpen(false);
      toast.message(t.modelPicker.bindMoliliFirst, {
        description: t.modelPicker.bindMoliliDesc,
      });
      navigate("/login");
      return;
    }
    setEnabling(meta.key);
    try {
      const r = await fetch(`${getBackendBaseURL()}/api/models`, {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({
          name: upstreamId,
          model: upstreamId,
          display_name: meta.displayName,
          api_key: moliliUserId,
          base_url: MOLILI_LLM_BASE_URL,
          max_tokens: 8192,
          temperature: 0.7,
          supports_thinking: false,
          supports_vision: false,
        }),
      });
      if (r.status === 409) {
        // Already exists from a parallel click — that's fine.
      } else if (!r.ok) {
        const body = (await r.json().catch(() => null)) as {
          detail?: string;
        } | null;
        throw new Error(body?.detail ?? `POST /api/models → ${r.status}`);
      }
      // Refresh the local model list so the picker drops the disabled
      // chip on next render.
      await queryClient.invalidateQueries({ queryKey: ["models"] });
      toast.success(t.modelPicker.modelEnabled(meta.displayName));
      onChange(upstreamId);
      setOpen(false);
    } catch (err) {
      toast.error(
        err instanceof Error
          ? t.modelPicker.enableFailedWithMessage(err.message)
          : t.modelPicker.enableFailed,
      );
    } finally {
      setEnabling(null);
    }
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
        "inline-flex min-w-0 items-center gap-1 rounded-lg border border-transparent",
        "bg-transparent px-2 py-1 text-xs text-muted-foreground transition outline-none",
        "hover:border-border/60 hover:bg-muted/60 hover:text-foreground",
        "data-[state=open]:bg-muted data-[state=open]:text-foreground",
      )}
      aria-label={t.modelPicker.selectModel}
      title={t.modelPicker.selectModel}
    >
      {isAutoMode && <SparklesIcon className="size-3 shrink-0 text-blue-500" />}
      <span className="truncate max-w-[140px]">
        {isAutoMode
          ? t.modelPicker.autoModelLabel
          : cleanModelName(selectedMetaForDisplay?.displayName) ||
            cleanModelName(selectedForDisplay?.display_name) ||
            cleanModelName(selectedForDisplay?.name) ||
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

  // Guests can inspect official models, but only custom models are
  // selectable before login, so land them on Custom when possible.
  const defaultTab =
    isGuest && customEntries.length > 0
      ? "custom"
      : officialEntries.length > 0
        ? "official"
        : "custom";

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      {renderTrigger ? (
        <DropdownMenuTrigger asChild>
          {renderTrigger(selectedForDisplay)}
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
                <SparklesIcon className="size-3 shrink-0 text-blue-500" />
                {t.modelPicker.autoModelLabel}
              </span>
            }
            right={
              <span className="rounded border border-blue-500/40 px-1 py-0 text-[10px] text-blue-500">
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

        <Tabs defaultValue={defaultTab} className="gap-0">
          <TabsList className="mx-1 mt-1 h-6 w-auto bg-transparent p-0 flex gap-1">
            {/* Official tab. Guests can see it, but rows are
                disabled until they sign in. */}
            <TabsTrigger
              data-testid="model-picker-tab-official"
              value="official"
              disabled={officialEntries.length === 0}
              className={cn(
                // Match sidebar section labels: opacity-based emphasis,
                // monochrome. Active state is just the text going full
                // opacity + muted underline — no violet accent.
                "flex-1 rounded-md text-[10px] font-medium uppercase tracking-wider transition-[opacity,color] duration-150",
                "text-muted-foreground/60 hover:text-foreground",
                "data-[state=active]:text-foreground data-[state=active]:opacity-100",
              )}
            >
              <span>{t.modelPicker.tabOfficial}</span>
            </TabsTrigger>
            <TabsTrigger
              data-testid="model-picker-tab-custom"
              value="custom"
              disabled={
                customEntries.length === 0 &&
                !isGuest &&
                officialEntries.length > 0
              }
              className={cn(
                "flex-1 rounded-md text-[10px] font-medium uppercase tracking-wider transition-[opacity,color] duration-150",
                "text-muted-foreground/60 hover:text-foreground",
                "data-[state=active]:text-foreground data-[state=active]:opacity-100",
              )}
            >
              {t.modelPicker.tabCustom}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="official" className="p-1 pt-0.5">
            {officialEntries.length === 0 ? (
              <div className="px-2 py-4 text-center text-xs text-muted-foreground">
                {t.modelPicker.officialDisabled}
              </div>
            ) : (
              <div className="flex flex-col gap-0.5">
                {officialEntries.map(({ meta, model, unconfigured }) => {
                  const isEnabling = enabling === meta.key;
                  return (
                    <PickerRow
                      key={model.name}
                      label={
                        <span
                          className={cn(
                            unconfigured && "text-muted-foreground/70",
                          )}
                        >
                          {meta.displayName}
                        </span>
                      }
                      right={
                        isGuest ? (
                          <span className="text-[10px] text-muted-foreground/70">
                            {t.modelPicker.loginRequired}
                          </span>
                        ) : isEnabling ? (
                          <span className="text-[10px] text-muted-foreground">
                            {t.modelPicker.enabling}
                          </span>
                        ) : unconfigured ? (
                          <span className="text-[10px] text-muted-foreground/70">
                            {t.modelPicker.clickToEnable}
                          </span>
                        ) : (
                          meta.multiplier
                        )
                      }
                      badge={
                        !isGuest && meta.recommended ? (
                          <span
                            title={t.modelPicker.recommended}
                            className="inline-block size-1 shrink-0 rounded-full bg-primary/70"
                          />
                        ) : undefined
                      }
                      selected={
                        model.name === value && !unconfigured && !isGuest
                      }
                      disabled={isGuest}
                      onSelect={() =>
                        isGuest
                          ? undefined
                          : unconfigured
                            ? handleSelectUnconfigured(meta, model.name)
                            : handleSelect(model.name)
                      }
                    />
                  );
                })}
              </div>
            )}
          </TabsContent>

          <TabsContent value="custom" className="p-1 pt-0.5">
            <div className="flex flex-col gap-0.5">
              {customEntries.length === 0 ? (
                <div className="px-2 py-4 text-center text-xs text-muted-foreground">
                  {t.modelPicker.noCustomModels}
                </div>
              ) : (
                customEntries.map((m) => (
                  <PickerRow
                    key={m.name}
                    label={m.display_name || m.name}
                    right={rightHint(m)}
                    selected={m.name === value}
                    onSelect={() => handleSelect(m.name)}
                  />
                ))
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
          </TabsContent>
        </Tabs>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
