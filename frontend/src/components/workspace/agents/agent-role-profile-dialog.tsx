import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  ChevronRight,
  CircuitBoard,
  ImagePlus,
  Loader2,
  Save,
  Shield,
  Sparkles,
  Wrench,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { AuthenticatedImage } from "@/components/ui/authenticated-image";
import { Button } from "@/components/ui/button";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useAgent, useGenerateAgentVisuals, useUpdateAgent } from "@/core/agents/hooks";
import { installAgent } from "@/core/agents/agent-world-api";
import {
  useAgentToolRegistry,
  useArms,
  useCapabilityPermissions,
  useSaveAgentToolRegistry,
} from "@/core/agents/tool-registry-hooks";
import type { AgentWorldAgent } from "@/core/agents/types";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { cn } from "@/lib/utils";

import { AgentArmsDialog } from "./agent-arms-dialog";

interface AgentRoleProfileDialogProps {
  agent: AgentWorldAgent | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onInstallChange?: () => void;
}

type EditableAgentConfig = {
  description: string;
  model: string;
  soul: string;
  arms: string[];
  extraAffinity: string;
  privateSkills: string;
};

function makeCodeName(agent: AgentWorldAgent): string {
  return agent.name
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => part.slice(0, 3).toUpperCase())
    .join("-");
}

function makeUid(agent: AgentWorldAgent): string {
  const seed = Array.from(agent.id || agent.name).reduce(
    (sum, char) => sum + char.charCodeAt(0),
    0,
  );
  return `${makeCodeName(agent).slice(0, 3) || "AGT"}-${String(seed % 90_000).padStart(5, "0")}`;
}

function parseList(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function serializeList(items: string[] | undefined): string {
  return (items ?? []).join(", ");
}

function sameList(left: string[], right: string[]): boolean {
  if (left.length !== right.length) return false;
  return left.every((item, index) => item === right[index]);
}

type AgentCharacterProfile = {
  epithet: string;
  quote: string;
  intro: string;
  background: string;
  age: string;
  personality: string;
  temperament: string;
  visualKeywords: string[];
  prompt: string;
};

function pickCategoryValue<T>(
  values: Record<string, T>,
  category: AgentWorldAgent["category"],
  fallback: T,
): T {
  return values[category] ?? fallback;
}

function buildCharacterProfile(
  agent: AgentWorldAgent,
  t: Translations,
): AgentCharacterProfile {
  const role = t.agentConfig.categoryRoles[agent.category] ?? agent.category;
  const type = t.agentConfig.categoryTypes[agent.category] ?? agent.category;
  const faction = agent.is_official
    ? t.agentConfig.officialFaction
    : t.agentConfig.authorFaction(agent.author);
  const fallbackAge = t.agentConfig.characterAgeArchetypes.assistant ?? "";
  const fallbackPersonality = t.agentConfig.characterPersonalities.assistant ?? "";
  const fallbackTemperament = t.agentConfig.characterTemperaments.assistant ?? "";
  const fallbackVisualKeywords =
    t.agentConfig.characterVisualKeywords.assistant ?? [];
  const fallbackEpithet = t.agentConfig.characterEpithets.assistant ?? role;
  const fallbackQuote = t.agentConfig.characterQuotes.assistant ?? "";
  const age = pickCategoryValue(
    t.agentConfig.characterAgeArchetypes,
    agent.category,
    fallbackAge,
  );
  const personality = pickCategoryValue(
    t.agentConfig.characterPersonalities,
    agent.category,
    fallbackPersonality,
  );
  const temperament = pickCategoryValue(
    t.agentConfig.characterTemperaments,
    agent.category,
    fallbackTemperament,
  );
  const visualKeywords = pickCategoryValue(
    t.agentConfig.characterVisualKeywords,
    agent.category,
    fallbackVisualKeywords,
  );
  const epithet = pickCategoryValue(
    t.agentConfig.characterEpithets,
    agent.category,
    fallbackEpithet,
  );
  const quote = pickCategoryValue(
    t.agentConfig.characterQuotes,
    agent.category,
    fallbackQuote,
  );
  const background = t.agentConfig.characterBackground(
    agent.display_name,
    role,
    type,
    faction,
    agent.description,
  );
  const intro = t.agentConfig.characterIntro(
    agent.display_name,
    role,
    type,
    faction,
    descriptionOrFallback(agent.description, t.agentConfig.characterDefaultOrigin),
    personality,
    temperament,
  );
  const prompt = [
    `character epithet: ${epithet}`,
    `signature line: ${quote}`,
    `readable character intro: ${intro}`,
    `character background: ${background}`,
    `apparent age: ${age}`,
    `personality: ${personality}`,
    `temperament: ${temperament}`,
    `visual keywords: ${visualKeywords.join(", ")}`,
  ].join("; ");

  return {
    epithet,
    quote,
    intro,
    background,
    age,
    personality,
    temperament,
    visualKeywords,
    prompt,
  };
}

function descriptionOrFallback(description: string, fallback: string): string {
  const trimmed = description.trim();
  if (!trimmed) return fallback;
  const fallbackUsesCjk = /[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/.test(fallback);
  const descriptionCjkCount = (
    trimmed.match(/[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/g) ?? []
  ).length;
  const descriptionLatinCount = (trimmed.match(/[A-Za-z]/g) ?? []).length;
  if (fallbackUsesCjk && descriptionLatinCount > descriptionCjkCount * 3) {
    return fallback;
  }
  return trimmed;
}

function FieldLabel({
  label,
  hint,
}: {
  label: string;
  hint?: string;
}) {
  return (
    <label className="block text-xs font-medium text-white">
      {label}
      {hint ? (
        <span className="ml-2 font-normal text-muted-foreground">{hint}</span>
      ) : null}
    </label>
  );
}

function AgentCoreVisual({
  agent,
  codeName,
  uid,
}: {
  agent: AgentWorldAgent;
  codeName: string;
  uid: string;
}) {
  const { t } = useI18n();
  const [view, setView] = useState<"front" | "side" | "back">("front");
  const generateVisuals = useGenerateAgentVisuals();
  const characterProfile = useMemo(
    () => buildCharacterProfile(agent, t),
    [agent, t],
  );
  const viewOptions = [
    ["front", t.agentConfig.viewFront],
    ["side", t.agentConfig.viewSide],
    ["back", t.agentConfig.viewBack],
  ] as const;
  const visualUrls = agent.visual_urls ?? {};
  const activeGeneratedVisual = visualUrls[view] ?? null;
  const activeAvatar = agent.avatar_url ? withAgentAvatarVersion(agent.avatar_url) : null;
  const activeVisual = activeGeneratedVisual ?? activeAvatar;
  const isAvatarOnly = Boolean(activeVisual && !activeGeneratedVisual);

  async function handleGenerateVisuals() {
    try {
      await generateVisuals.mutateAsync({
        name: agent.name,
        provider: "agnes",
        stylePrompt: characterProfile.prompt,
      });
      toast.success(t.agentConfig.visualGenerateSuccess);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(t.agentConfig.visualGenerateFailed(message));
    }
  }

  return (
    <section className="relative min-h-0 overflow-hidden">
      <div className="pointer-events-none absolute inset-0 opacity-[0.16] [background-image:radial-gradient(circle_at_48%_62%,hsl(var(--primary)/0.12),transparent_30%),linear-gradient(90deg,rgba(255,255,255,0.055)_1px,transparent_1px),linear-gradient(180deg,rgba(255,255,255,0.035)_1px,transparent_1px)] [background-size:100%_100%,34px_34px,34px_34px]" />
      <div className="pointer-events-none absolute left-[11%] top-[28%] text-7xl font-black uppercase tracking-normal text-white/[0.035] 2xl:text-8xl">
        {t.agentConfig.visualWatermark}
      </div>
      <div className="pointer-events-none absolute bottom-[44%] left-[15%] text-sm font-mono uppercase tracking-[0.55em] text-white/[0.045]">
        {t.agentConfig.visualLoadoutLabel}
      </div>
      <div className="absolute right-8 top-8 z-20 rounded-sm border border-white/10 bg-black/10 px-2 py-1 font-mono text-[9px] uppercase tracking-[0.32em] text-muted-foreground">
        REC
      </div>
      <div className="absolute right-5 top-1/2 z-20 flex -translate-y-1/2 flex-col gap-3">
        {viewOptions.map(([key, label]) => (
          <button
            key={key}
            className={cn(
              "group relative h-[74px] w-[62px] rounded-sm border bg-black/10 p-1 text-left transition xl:h-[92px] xl:w-[78px]",
              view === key
                ? "border-[#f4e86f] shadow-[0_0_18px_rgba(244,232,111,0.16)]"
                : "border-white/10 opacity-45 hover:opacity-85",
            )}
            type="button"
            onClick={() => setView(key)}
          >
            <span className="absolute left-2 top-2 z-10 font-mono text-[9px] uppercase tracking-[0.25em] text-muted-foreground">
              {key}
            </span>
            <span className="flex h-full items-end justify-center overflow-hidden rounded-sm bg-black/20 pb-1">
              {visualUrls[key] ? (
                <AuthenticatedImage
                  alt={`${agent.display_name} ${key}`}
                  className="h-[54px] w-full object-contain xl:h-[70px]"
                  src={visualUrls[key]}
                />
              ) : (
                <Bot className="mb-5 size-6 text-muted-foreground" />
              )}
            </span>
            <span className="absolute bottom-2 right-2 font-mono text-[9px] uppercase text-muted-foreground">
              {label}
            </span>
          </button>
        ))}
        <Button
          aria-label={t.agentConfig.visualGenerateAction}
          className="h-8 w-[62px] rounded-sm border-primary/35 bg-black/15 px-1 text-[10px] xl:w-[78px]"
          disabled={generateVisuals.isPending}
          title={t.agentConfig.visualGenerateAction}
          variant="outline"
          onClick={() => void handleGenerateVisuals()}
        >
          {generateVisuals.isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <ImagePlus className="size-3.5" />
          )}
        </Button>
      </div>
      <div className="absolute left-4 top-4 z-20 hidden items-center gap-2 rounded-sm border border-white/10 bg-black/15 px-3 py-2">
        <span className="h-1.5 w-1.5 rounded-full bg-primary shadow-[0_0_12px_hsl(var(--primary)/0.75)]" />
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
          {t.agentConfig.visualTitle}
        </span>
      </div>
      <div className="relative z-10 h-full min-h-[520px] px-4 pb-8 pt-8 xl:min-h-[620px] xl:px-6 xl:pb-10 xl:pt-10">
        <div className="relative flex h-full min-h-0 items-end justify-center overflow-hidden pr-20 xl:pr-24">
          <div className="absolute bottom-[78px] h-16 w-[62%] rounded-[50%] border border-[#f4e86f]/25 bg-[#f4e86f]/10 shadow-[0_0_34px_rgba(244,232,111,0.12)]" />
          <div className="absolute bottom-[118px] left-[10%] right-[18%] h-px bg-white/10" />
          <div className="relative z-10 flex h-[500px] w-full max-w-[460px] items-end justify-center xl:h-[640px] xl:max-w-[580px]">
            {activeVisual ? (
              <div
                className={cn(
                  "flex w-full items-end justify-center",
                  isAvatarOnly ? "pb-24 xl:pb-28" : "h-full",
                )}
              >
                <AuthenticatedImage
                  alt={`${agent.display_name} ${view}`}
                  className={cn(
                    "object-contain drop-shadow-2xl",
                    isAvatarOnly
                      ? "h-[300px] w-[300px] rounded-[32px] border border-white/10 bg-white/95 object-center p-0 mix-blend-normal xl:h-[360px] xl:w-[360px]"
                      : "max-h-full w-full object-bottom mix-blend-screen",
                  )}
                  fallback={
                    <div className="mb-24 flex size-32 items-center justify-center rounded-sm border border-primary/35 bg-background text-6xl shadow-lg">
                      {agent.icon || <Bot className="size-16 text-muted-foreground" />}
                    </div>
                  }
                  src={activeVisual}
                />
              </div>
            ) : (
              <div className="mb-28 flex flex-col items-center justify-center gap-3 text-muted-foreground">
                <div className="flex size-32 items-center justify-center rounded-sm border border-primary/35 bg-background text-6xl shadow-lg">
                  {agent.icon || <Bot className="size-16" />}
                </div>
                <span className="font-mono text-[10px] uppercase tracking-[0.16em]">
                  {t.agentConfig.visualMissing}
                </span>
              </div>
            )}
            <div className="absolute bottom-0 left-[6%] right-[6%] h-9 border-y border-[#111]/30 bg-[#f4e86f] text-center font-mono text-[10px] font-semibold uppercase tracking-[0.55em] text-[#232323] shadow-[0_0_24px_rgba(244,232,111,0.18)]">
              <div className="flex h-full items-center justify-center gap-4">
                <span className="h-px w-10 bg-[#232323]/50" />
                {t.agentConfig.visualSystemOnline}
                <span className="h-px w-10 bg-[#232323]/50" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

export function AgentRoleProfileDialog({
  agent,
  open,
  onOpenChange,
  onInstallChange,
}: AgentRoleProfileDialogProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [armsOpen, setArmsOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [savedFlash, setSavedFlash] = useState(false);
  const [installingPack, setInstallingPack] = useState(false);
  const [armsInitialTab, setArmsInitialTab] = useState<
    "arms" | "skills" | "permissions" | "routing"
  >("arms");
  const [form, setForm] = useState<EditableAgentConfig>({
    description: "",
    model: "",
    soul: "",
    arms: [],
    extraAffinity: "",
    privateSkills: "",
  });

  const localAgentName = open && agent?.is_installed ? agent.name : null;
  const agentQuery = useAgent(localAgentName);
  const armsQuery = useArms();
  const registryQuery = useAgentToolRegistry(localAgentName);
  const permissionsQuery = useCapabilityPermissions();
  const updateAgent = useUpdateAgent();
  const saveRegistry = useSaveAgentToolRegistry(agent?.name ?? "");

  const fullAgent = agentQuery.agent;
  const arms = armsQuery.data ?? [];
  const registry = registryQuery.data;
  const characterProfile = useMemo(
    () => (agent ? buildCharacterProfile(agent, t) : null),
    [agent, t],
  );

  const meta = useMemo(() => {
    if (!agent) return null;
    return {
      codeName: makeCodeName(agent),
      uid: makeUid(agent),
      role: t.agentConfig.categoryRoles[agent.category],
      type: t.agentConfig.categoryTypes[agent.category],
      faction: agent.is_official
        ? t.agentConfig.officialFaction
        : t.agentConfig.authorFaction(agent.author),
    };
  }, [agent, t]);

  const serverState = useMemo<EditableAgentConfig | null>(() => {
    if (!agent) return null;
    return {
      description: fullAgent?.description ?? agent.description ?? "",
      model: fullAgent?.model ?? "",
      soul: fullAgent?.soul ?? "",
      arms: registry?.arms ?? fullAgent?.tool_groups ?? agent.tags ?? [],
      extraAffinity: serializeList(registry?.extra_affinity),
      privateSkills: serializeList(registry?.private_skills ?? agent.key_skills),
    };
  }, [agent, fullAgent, registry]);

  useEffect(() => {
    if (open && serverState) {
      setForm(serverState);
    }
  }, [open, serverState]);

  if (!agent || !meta || !characterProfile) return null;

  const desiredExtraAffinity = parseList(form.extraAffinity);
  const desiredPrivateSkills = parseList(form.privateSkills);
  const agentDirty =
    !!serverState &&
    (form.description !== serverState.description ||
      form.model !== serverState.model ||
      form.soul !== serverState.soul);
  const registryDirty =
    !!serverState &&
    (!sameList(form.arms, serverState.arms) ||
      form.extraAffinity.trim() !== serverState.extraAffinity.trim() ||
      form.privateSkills.trim() !== serverState.privateSkills.trim());
  const isDirty = agentDirty || registryDirty;
  const canAssembleCapabilityPack =
    !agent.is_installed && desiredPrivateSkills.length > 0;
  const isLoading =
    agentQuery.isLoading || armsQuery.isLoading || registryQuery.isLoading;
  const isSaving = updateAgent.isPending || saveRegistry.isPending;
  const permissionEnabledCount =
    permissionsQuery.data?.filter((permission) => permission.enabled).length ?? 0;
  const permissionTotalCount = permissionsQuery.data?.length ?? 0;
  const permissionSummary = permissionTotalCount
    ? t.agentConfig.permissionCount(permissionEnabledCount, permissionTotalCount)
    : t.agentConfig.guarded;
  const enabledArmOptions = arms.filter((arm) => form.arms.includes(arm.arm_id));
  const effectiveSkillPool = new Set<string>(desiredPrivateSkills);
  for (const arm of enabledArmOptions) {
    for (const skill of arm.skills) {
      effectiveSkillPool.add(skill);
    }
  }
  const disabledPermissionSkills = new Set<string>();
  for (const permission of permissionsQuery.data ?? []) {
    if (!permission.enabled) {
      for (const skill of permission.skill_names) {
        disabledPermissionSkills.add(skill);
      }
    }
  }
  const blockedSkillCount = [...effectiveSkillPool].filter((skill) =>
    disabledPermissionSkills.has(skill),
  ).length;
  const executableSkillCount = Math.max(0, effectiveSkillPool.size - blockedSkillCount);
  const loadoutChecks: Array<{
    id: string;
    message: string;
    severity?: "danger";
    actionLabel?: string;
    onAction?: () => void;
    disabled?: boolean;
  }> = [
    ...(form.arms.length === 0
      ? [
          {
            id: "no-arms",
            message: t.agentConfig.checkNoArms,
            actionLabel: t.agentConfig.configureArmAction,
            onAction: () => openArmsConfig("arms"),
          },
        ]
      : []),
    ...(desiredPrivateSkills.length === 0
      ? [
          {
            id: "no-private-skills",
            message: t.agentConfig.checkNoPrivateSkills,
            actionLabel: t.agentConfig.configureSkillsAction,
            onAction: () => openArmsConfig("skills"),
          },
        ]
      : []),
    ...(blockedSkillCount > 0
      ? [
          {
            id: "blocked-skills",
            message: t.agentConfig.checkBlockedSkills(blockedSkillCount),
            actionLabel: t.agentConfig.configurePermissionsAction,
            onAction: () => openArmsConfig("permissions"),
          },
        ]
      : []),
    ...(executableSkillCount === 0
      ? [
          {
            id: "no-executable-skills",
            message: t.agentConfig.checkNoExecutableSkills,
            severity: "danger" as const,
            actionLabel: t.agentConfig.configureSkillsAction,
            onAction: () => openArmsConfig("skills"),
          },
        ]
      : []),
    ...(isDirty
      ? [
          {
            id: "unsaved-changes",
            message: t.agentConfig.checkUnsavedChanges,
            actionLabel: t.agentConfig.saveButton,
            onAction: () => void handleSave(),
            disabled: isLoading || isSaving,
          },
        ]
      : []),
  ];
  function openArmsConfig(tab: "arms" | "skills" | "permissions" | "routing") {
    setArmsInitialTab(tab);
    setArmsOpen(true);
  }

  function setField<K extends keyof EditableAgentConfig>(
    key: K,
    value: EditableAgentConfig[K],
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSave() {
    if (!agent) return;
    try {
      if (agentDirty) {
        await updateAgent.mutateAsync({
          name: agent.name,
          request: {
            description: form.description,
            model: form.model.trim() || null,
            soul: form.soul,
          },
        });
      }
      if (registryDirty) {
        await saveRegistry.mutateAsync({
          arms: form.arms,
          extra_affinity: desiredExtraAffinity,
          private_skills: desiredPrivateSkills,
        });
      }
      toast.success(t.agentConfig.saved);
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 1400);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(t.agentConfig.saveFailed(message));
    }
  }

  async function handleAssembleCapabilityPack() {
    if (!agent || installingPack) return;
    setInstallingPack(true);
    try {
      const result = await installAgent(agent.id);
      const assembledSkillCount =
        result.key_skills?.length ?? result.registered_skills ?? desiredPrivateSkills.length;
      toast.success(
        assembledSkillCount > 0
          ? t.agentWorld.toastCapabilityPackInstalled(
              agent.display_name,
              assembledSkillCount,
            )
          : t.agentWorld.toastInstalled(agent.display_name),
      );
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      onInstallChange?.();
      onOpenChange(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(message);
    } finally {
      setInstallingPack(false);
    }
  }

  function handleReset() {
    if (serverState) setForm(serverState);
  }

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent
          className={cn(
            "!h-[min(760px,86vh)] !w-[min(1180px,92vw)] !max-w-none overflow-hidden border-white/12 bg-[#2a2a2a] p-0 text-white shadow-2xl sm:rounded-lg",
            "data-[state=open]:duration-200",
          )}
          showCloseButton={false}
        >
          <DialogTitle className="sr-only">{t.agentConfig.dialogTitle}</DialogTitle>
          <DialogDescription className="sr-only">
            {t.agentConfig.subtitle}
          </DialogDescription>
          <div className="relative h-full overflow-hidden bg-[#2a2a2a]">
            <div className="pointer-events-none absolute inset-0 opacity-[0.18] [background-image:radial-gradient(circle_at_70%_38%,rgba(255,255,255,0.12),transparent_30%),linear-gradient(to_right,rgba(255,255,255,0.045)_1px,transparent_1px),linear-gradient(to_bottom,rgba(255,255,255,0.03)_1px,transparent_1px)] [background-size:100%_100%,40px_40px,40px_40px]" />
            <div className="relative grid h-full grid-cols-[minmax(300px,0.42fr)_minmax(0,0.58fr)]">
                <section className="relative flex min-h-0 flex-col overflow-hidden px-8 py-6 lg:px-10 lg:py-7">
                  <div className="pointer-events-none absolute left-0 top-0 h-5 w-5 border-l border-t border-primary/60" />
                  <div className="pointer-events-none absolute bottom-0 right-0 h-5 w-5 border-b border-r border-primary/45" />
                  <div className="mb-7 flex items-center justify-between">
                    <Button
                      aria-label={t.agentConfig.back}
                      className="h-8 w-8 shrink-0 rounded-sm"
                      size="icon"
                      variant="ghost"
                      onClick={() => onOpenChange(false)}
                    >
                      <ChevronRight className="size-5 rotate-180" />
                    </Button>
                    <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                      <span className={cn("h-1.5 w-1.5 rounded-full", isDirty ? "bg-amber-500" : "bg-emerald-500")} />
                      {isDirty ? t.agentConfig.unsaved : t.agentConfig.synced}
                    </div>
                    <Button
                      aria-label={t.common.close}
                      className="h-8 w-8 rounded-sm"
                      size="icon"
                      variant="ghost"
                      onClick={() => onOpenChange(false)}
                    >
                      <X className="size-4" />
                    </Button>
                  </div>
                  <div className="max-w-[360px]">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.24em] text-primary">
                        <span className="h-px w-6 bg-primary/70" />
                        {t.agentConfig.characterFileLabel}
                      </div>
                      <h1 className="mt-4 truncate text-4xl font-semibold leading-none text-white">
                        {agent.display_name}
                      </h1>
                      <p className="mt-3 text-xl font-medium leading-7 text-[#f4e86f]">
                        {characterProfile.epithet}
                      </p>
                      <div className="mt-3 flex flex-wrap gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                        <span className="rounded-sm border border-white/10 bg-black/15 px-2 py-1">
                          {meta.type}
                        </span>
                        <span className="rounded-sm border border-white/10 bg-black/15 px-2 py-1">
                          {meta.role}
                        </span>
                        <span className="rounded-sm border border-white/10 bg-black/15 px-2 py-1">
                          {meta.codeName}
                        </span>
                      </div>
                    </div>

                    <div className="mt-7 border-y border-white/10 py-4">
                      <p className="text-base font-medium leading-7 text-white/95">
                        &ldquo;{characterProfile.quote}&rdquo;
                      </p>
                    </div>

                    <div className="mt-5">
                      <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                        {t.agentConfig.characterBackgroundLabel}
                      </div>
                      <p className="line-clamp-7 text-sm leading-7 text-white/82">
                        {characterProfile.intro}
                      </p>
                    </div>

                    <div className="mt-5 space-y-4">
                      <div className="flex flex-wrap gap-1.5">
                        <span className="rounded-sm border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-xs text-white/85">
                          {t.agentConfig.characterAgeLabel} · {characterProfile.age}
                        </span>
                        <span className="rounded-sm border border-white/10 bg-white/[0.04] px-2.5 py-1.5 text-xs text-white/85">
                          {t.agentConfig.characterTemperamentLabel} · {characterProfile.temperament}
                        </span>
                      </div>

                      <div className="border-l border-primary/45 pl-3">
                        <div className="font-mono text-[9px] uppercase tracking-[0.16em] text-muted-foreground">
                          {t.agentConfig.characterPersonalityLabel}
                        </div>
                        <p className="mt-1 line-clamp-3 text-sm leading-6 text-white/88">
                          {characterProfile.personality}
                        </p>
                      </div>

                      <div>
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                            {t.agentConfig.characterVisualKeywordsLabel}
                          </span>
                          <span className="font-mono text-[10px] text-muted-foreground">
                            {t.agentConfig.characterPromptHint}
                          </span>
                        </div>
                        <div className="flex max-h-20 flex-wrap gap-1.5 overflow-hidden">
                          {characterProfile.visualKeywords.map((keyword) => (
                            <span
                              key={keyword}
                              className="rounded-sm border border-primary/20 bg-primary/10 px-2 py-1 text-xs text-primary"
                            >
                              {keyword}
                            </span>
                          ))}
                        </div>
                      </div>

                      <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                        <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                        {t.agentConfig.characterProfileReady}
                      </div>

                      {canAssembleCapabilityPack ? (
                        <div className="rounded-sm border border-primary/20 bg-primary/10 p-2.5">
                          <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-primary">
                            {t.agentConfig.capabilityPackLabel}
                          </div>
                          <button
                            className="inline-flex items-center gap-1 rounded-sm border border-primary/25 bg-black/15 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-primary transition hover:border-primary/45 hover:bg-primary/15"
                            disabled={installingPack}
                            type="button"
                            onClick={() => void handleAssembleCapabilityPack()}
                          >
                            {installingPack ? (
                              <Loader2 className="size-3 animate-spin" />
                            ) : (
                              <Sparkles className="size-3" />
                            )}
                            {t.agentWorld.assembleCapabilityPack}
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div className="mt-auto max-w-[360px] border-t border-white/10 pt-4">
                    <div className="flex items-center gap-2">
                      <button
                        className="flex h-9 w-9 items-center justify-center rounded-sm border border-white/10 bg-black/20 text-primary transition hover:border-primary/45"
                        aria-label={t.agentConfig.configureProfileAction}
                        type="button"
                        onClick={() => setProfileOpen(true)}
                      >
                        <CircuitBoard className="size-4" />
                      </button>
                      <button
                        className="flex h-9 w-9 items-center justify-center rounded-sm border border-white/10 bg-black/20 text-primary transition hover:border-primary/45"
                        aria-label={t.agentConfig.advancedArmConfig}
                        type="button"
                        onClick={() => openArmsConfig("arms")}
                      >
                        <Wrench className="size-4" />
                      </button>
                      <button
                        className="flex h-9 w-9 items-center justify-center rounded-sm border border-white/10 bg-black/20 text-primary transition hover:border-primary/45"
                        aria-label={t.agentConfig.browseSkillWhitelist}
                        type="button"
                        onClick={() => openArmsConfig("skills")}
                      >
                        <Sparkles className="size-4" />
                      </button>
                      <button
                        className="flex h-9 w-9 items-center justify-center rounded-sm border border-white/10 bg-black/20 text-primary transition hover:border-primary/45"
                        aria-label={t.agentConfig.configurePermissionsAction}
                        type="button"
                        onClick={() => openArmsConfig("permissions")}
                      >
                        <Shield className="size-4" />
                      </button>
                      <div className="ml-auto min-w-0 truncate font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                        {t.agentConfig.loadoutReady}
                      </div>
                    </div>
                  </div>
                </section>

                <AgentCoreVisual
                  agent={{
                    ...agent,
                    avatar_url: fullAgent?.avatar_url ?? agent.avatar_url,
                    visual_urls: fullAgent?.visual_urls ?? agent.visual_urls,
                  }}
                  codeName={meta.codeName}
                  uid={meta.uid}
                />
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={profileOpen} onOpenChange={setProfileOpen}>
        <DialogContent className="max-h-[88vh] overflow-hidden rounded-sm border-white/10 bg-[#191919] p-0 text-white shadow-2xl sm:max-w-3xl">
          <div className="relative overflow-hidden border-b border-white/10 bg-[#202020]/90 px-5 py-4">
            <div className="pointer-events-none absolute inset-0 opacity-30 [background-image:linear-gradient(90deg,rgba(255,255,255,0.06)_1px,transparent_1px),linear-gradient(180deg,rgba(255,255,255,0.045)_1px,transparent_1px)] [background-size:28px_28px]" />
            <DialogTitle className="relative">
              {t.agentConfig.configureProfileAction}
            </DialogTitle>
            <DialogDescription className="relative">
              {t.agentConfig.basicSubtitle} / {t.agentConfig.promptSubtitle}
            </DialogDescription>
          </div>
          <div className="grid gap-4 p-5">
            <div>
              <FieldLabel label={t.agentConfig.descriptionLabel} />
              <Textarea
                className="mt-1 min-h-[96px] border-white/10 bg-black/25 text-sm text-white"
                disabled={isLoading || isSaving}
                value={form.description}
                onChange={(event) => setField("description", event.target.value)}
              />
            </div>
            <div>
              <FieldLabel label={t.agentConfig.modelLabel} hint={t.agentConfig.modelHint} />
              <Input
                className="mt-1 h-9 border-white/10 bg-black/25 text-white"
                disabled={isLoading || isSaving}
                placeholder={t.agentConfig.modelPlaceholder}
                value={form.model}
                onChange={(event) => setField("model", event.target.value)}
              />
            </div>
            <div>
              <FieldLabel label={t.agentConfig.promptTitle} />
              <Textarea
                className="mt-1 min-h-[260px] border-white/10 bg-black/25 font-mono text-xs leading-5 text-white"
                disabled={isLoading || isSaving}
                placeholder={t.agentConfig.soulPlaceholder}
                value={form.soul}
                onChange={(event) => setField("soul", event.target.value)}
              />
            </div>
            <div className="flex justify-end gap-2 border-t border-white/10 pt-4">
              <Button
                className="rounded-sm"
                variant="ghost"
                onClick={() => setProfileOpen(false)}
              >
                {t.common.close}
              </Button>
              <Button
                className="rounded-sm"
                disabled={!isDirty || isLoading || isSaving}
                onClick={() => void handleSave()}
              >
                {isSaving ? <Loader2 className="mr-2 size-4 animate-spin" /> : <Save className="mr-2 size-4" />}
                {savedFlash ? t.agentConfig.savedButton : t.agentConfig.saveButton}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <AgentArmsDialog
        agentId={agent.name}
        agentDisplayName={agent.display_name}
        open={armsOpen}
        onOpenChange={setArmsOpen}
        initialTab={armsInitialTab}
      />
    </>
  );
}
