import { type ReactNode, useMemo, useState } from "react";
import {
  BarChart3,
  Boxes,
  Bot,
  BriefcaseBusiness,
  CheckCircle2,
  Code2,
  Database,
  FileText,
  GraduationCap,
  Loader2,
  Mail,
  Palette,
  PenLine,
  Plus,
  Search,
  SearchCheck,
  ShieldCheck,
  Terminal,
  Video,
  WalletCards,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/core/i18n/hooks";
import { useEnableSkill, useSkills } from "@/core/skills/hooks";
import { cn } from "@/lib/utils";
import {
  type LocalSkill,
  LOCAL_SKILL_CATEGORIES,
  StoreErrorState,
  classifyLocalSkill,
  searchableSkillText,
  useLocalSkillCategoryLabel,
} from "./store-utils";

const CATEGORY_ICON_MAP: Record<string, LucideIcon> = {
  "browser-search": SearchCheck,
  "agent-tools": Bot,
  "webapp-frontend": Palette,
  "backend-api": Database,
  "code-quality": Code2,
  "devops-cloud": Terminal,
  "office-docs": FileText,
  "slides-report": FileText,
  "chart-viz": BarChart3,
  "writing-editing": PenLine,
  "marketing-copy": PenLine,
  "seo-growth": BarChart3,
  ecommerce: BriefcaseBusiness,
  "market-product": BriefcaseBusiness,
  "project-goal": CheckCircle2,
  "finance-stock": WalletCards,
  "finance-model": WalletCards,
  "data-stats": BarChart3,
  "data-insight": BarChart3,
  "academic-paper": GraduationCap,
  "deep-research": SearchCheck,
  "education-coach": GraduationCap,
  "hr-career": BriefcaseBusiness,
  "email-comms": Mail,
  "legal-compliance": ShieldCheck,
  "security-audit": ShieldCheck,
  "design-creative": Palette,
  "media-audio-video": Video,
  "personal-productivity": CheckCircle2,
};

function skillTone(category: string) {
  if (category.includes("browser") || category.includes("research")) {
    return "border-sky-500/20 bg-sky-500/10 text-sky-600 dark:text-sky-300";
  }
  if (category.includes("finance") || category.includes("market")) {
    return "border-amber-500/20 bg-amber-500/10 text-amber-600 dark:text-amber-300";
  }
  if (category.includes("data") || category.includes("chart")) {
    return "border-violet-500/20 bg-violet-500/10 text-violet-600 dark:text-violet-300";
  }
  if (category.includes("design") || category.includes("media")) {
    return "border-pink-500/20 bg-pink-500/10 text-pink-600 dark:text-pink-300";
  }
  if (category.includes("security") || category.includes("legal")) {
    return "border-rose-500/20 bg-rose-500/10 text-rose-600 dark:text-rose-300";
  }
  if (
    category.includes("code") ||
    category.includes("backend") ||
    category.includes("devops")
  ) {
    return "border-blue-500/20 bg-blue-500/10 text-blue-600 dark:text-blue-300";
  }
  return "border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-300";
}

type LocalSkillDirectoryPanelProps = {
  allButtonPosition?: "start" | "end";
  onDirectorySelect?: () => void;
  onSkillPacksSelect?: () => void;
  skillPacksContent?: ReactNode;
  skillPacksSelected?: boolean;
};

export function LocalSkillDirectoryPanel({
  allButtonPosition = "start",
  onDirectorySelect,
  onSkillPacksSelect,
  skillPacksContent,
  skillPacksSelected = false,
}: LocalSkillDirectoryPanelProps = {}) {
  const { t } = useI18n();
  const categoryLabel = useLocalSkillCategoryLabel();
  const { skills, isLoading, isFetching, error, refetch } = useSkills();
  const { mutate: setSkillEnabled, isPending } = useEnableSkill();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [showInternalSkills, setShowInternalSkills] = useState(false);

  const allDomainSkills = useMemo(() => {
    return (skills as LocalSkill[])
      .filter((skill) => (skill.kind ?? "domain") === "domain")
      .map((skill) => ({ ...skill, localCategory: classifyLocalSkill(skill) }))
      .sort((a, b) => {
        if (a.enabled !== b.enabled) return a.enabled ? -1 : 1;
        return a.name.localeCompare(b.name);
      });
  }, [skills]);

  const localSkills = useMemo(() => {
    if (showInternalSkills) return allDomainSkills;
    return allDomainSkills.filter(
      (skill) => (skill.market_visibility ?? "market") === "market",
    );
  }, [allDomainSkills, showInternalSkills]);

  const categoryCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const skill of localSkills) {
      counts.set(
        skill.localCategory,
        (counts.get(skill.localCategory) ?? 0) + 1,
      );
    }
    return counts;
  }, [localSkills]);

  const visibleSkills = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return localSkills.filter((skill) => {
      if (category !== "all" && skill.localCategory !== category) return false;
      if (!needle) return true;
      return searchableSkillText(skill).includes(needle);
    });
  }, [category, localSkills, query]);

  const activeLabel =
    category === "all" ? t.unifiedStore.skills.all : categoryLabel(category);
  const showSkillPacks = Boolean(skillPacksContent && skillPacksSelected);
  const enabledSkills = localSkills.filter((skill) => skill.enabled).length;
  const hiddenSkillCount = Math.max(
    0,
    allDomainSkills.length - localSkills.length,
  );

  const handleCategorySelect = (nextCategory: string) => {
    setCategory(nextCategory);
    onDirectorySelect?.();
  };

  const allButton = (
    <Button
      size="sm"
      variant={!showSkillPacks && category === "all" ? "secondary" : "ghost"}
      className="h-8 shrink-0 rounded-full px-3 text-xs"
      onClick={() => handleCategorySelect("all")}
    >
      {t.unifiedStore.skills.all}
      <span className="ml-1 text-muted-foreground">{localSkills.length}</span>
    </Button>
  );

  if (isLoading) {
    return (
      <div className="flex min-h-[360px] items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        {t.unifiedStore.skills.loading}
      </div>
    );
  }

  if (error) {
    return (
      <StoreErrorState
        title="技能目录暂时不可用"
        detail={error.message}
        retryLabel="重新加载"
        retrying={isFetching}
        onRetry={() => void refetch()}
      />
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5">
      {!showSkillPacks && (
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-center">
          <div className="relative w-full lg:max-w-[560px]">
            <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label={t.unifiedStore.skills.searchAria}
              className="h-11 rounded-2xl border-border/60 bg-background pl-10 text-base shadow-sm"
              placeholder={t.unifiedStore.skills.searchPlaceholder}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        {skillPacksContent && (
          <Button
            size="sm"
            variant={showSkillPacks ? "secondary" : "ghost"}
            className="h-8 shrink-0 rounded-full px-3 text-xs"
            onClick={onSkillPacksSelect}
          >
            <Boxes className="mr-1.5 size-3.5" />
            {t.metaSkills.title}
          </Button>
        )}
        {allButtonPosition === "start" && allButton}
        {LOCAL_SKILL_CATEGORIES.map((item) => {
          const count = categoryCounts.get(item.key) ?? 0;
          if (!count) return null;
          return (
            <Button
              key={item.key}
              size="sm"
              variant={
                !showSkillPacks && category === item.key ? "secondary" : "ghost"
              }
              className="h-8 shrink-0 rounded-full px-3 text-xs"
              onClick={() => handleCategorySelect(item.key)}
            >
              {categoryLabel(item.key)}
              <span className="ml-1 text-muted-foreground">{count}</span>
            </Button>
          );
        })}
        {(categoryCounts.get("other") ?? 0) > 0 && (
          <Button
            size="sm"
            variant={
              !showSkillPacks && category === "other" ? "secondary" : "ghost"
            }
            className="h-8 shrink-0 rounded-full px-3 text-xs"
            onClick={() => handleCategorySelect("other")}
          >
            {t.unifiedStore.skills.other}
            <span className="ml-1 text-muted-foreground">
              {categoryCounts.get("other")}
            </span>
          </Button>
        )}
        {allButtonPosition === "end" && allButton}
      </div>

      {showSkillPacks ? (
        <div>{skillPacksContent}</div>
      ) : (
        <>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {t.unifiedStore.skills.visibleCount(
                activeLabel,
                visibleSkills.length,
              )}
            </span>
            <div className="flex items-center gap-3">
              <span>{t.unifiedStore.skills.enabledCount(enabledSkills)}</span>
              {hiddenSkillCount > 0 && (
                <button
                  type="button"
                  className="rounded-full px-2 py-1 transition-colors hover:bg-muted hover:text-foreground"
                  onClick={() => setShowInternalSkills((value) => !value)}
                >
                  {showInternalSkills
                    ? "隐藏内部技能"
                    : `显示内部 ${hiddenSkillCount}`}
                </button>
              )}
            </div>
          </div>

          {visibleSkills.length ? (
            <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-4">
              {visibleSkills.map((skill) => {
                const SkillIcon =
                  CATEGORY_ICON_MAP[skill.localCategory] ?? Wrench;
                return (
                  <article
                    key={skill.name}
                    className={cn(
                      "group flex min-w-0 flex-col rounded-lg border border-border/60 bg-card/70 p-3.5 shadow-sm transition-colors hover:border-primary/25 hover:bg-card",
                      !skill.enabled && "bg-muted/15 text-muted-foreground",
                    )}
                  >
                    <div className="flex min-w-0 items-start gap-3">
                      <div
                        className={cn(
                          "flex size-12 shrink-0 items-center justify-center rounded-xl border shadow-sm",
                          skill.enabled
                            ? skillTone(skill.localCategory)
                            : "border-border/50 bg-muted/35 text-muted-foreground",
                        )}
                      >
                        <SkillIcon className="size-5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex min-w-0 items-center gap-2">
                          <h3 className="truncate text-[15px] font-semibold leading-5 text-foreground">
                            {skill.name}
                          </h3>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-1.5">
                          <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                            {categoryLabel(skill.localCategory)}
                          </span>
                          {skill.has_tests && (
                            <span className="inline-flex items-center gap-1 rounded-full bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium text-blue-600 dark:text-blue-300">
                              <ShieldCheck className="size-3" />
                              已验证
                            </span>
                          )}
                          {(skill.market_visibility ?? "market") !==
                            "market" && (
                            <span
                              title={
                                skill.canonical_skill
                                  ? `${skill.market_reason ?? "归并展示"}：${skill.canonical_skill}`
                                  : (skill.market_reason ?? "内部技能")
                              }
                              className="rounded-full bg-slate-500/10 px-2 py-0.5 text-[10px] font-medium text-slate-600 dark:text-slate-300"
                            >
                              {skill.market_visibility === "duplicate"
                                ? "重复"
                                : skill.market_visibility === "provider"
                                  ? "后端"
                                  : skill.market_visibility === "deprecated"
                                    ? "弃用"
                                    : "内部"}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    <p className="mt-3 line-clamp-2 flex-1 text-sm leading-5 text-muted-foreground">
                      {skill.description || t.unifiedStore.skills.noDescription}
                    </p>
                    <div className="mt-3 flex items-center justify-between gap-3 border-t border-border/40 pt-2.5">
                      <span
                        title={skill.trusted_source ?? undefined}
                        className="truncate text-[11px] text-muted-foreground"
                      >
                        {skill.has_tests ? "已验证" : "本地能力"}
                      </span>
                      <button
                        type="button"
                        aria-label={t.unifiedStore.skills.toggleSkillAria(
                          skill.enabled,
                          skill.name,
                        )}
                        disabled={isPending}
                        onClick={() =>
                          setSkillEnabled({
                            skillName: skill.name,
                            enabled: !skill.enabled,
                          })
                        }
                        className={cn(
                          "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-xs font-medium transition-colors disabled:opacity-60",
                          skill.enabled
                            ? "bg-emerald-500/10 text-emerald-700 hover:bg-emerald-500/15 dark:text-emerald-300"
                            : "bg-primary text-primary-foreground hover:bg-primary/90",
                        )}
                      >
                        {skill.enabled ? (
                          <>
                            <CheckCircle2 className="size-3.5" />
                            已启用
                          </>
                        ) : (
                          <>
                            <Plus className="size-3.5" />
                            启用
                          </>
                        )}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-border/70 bg-muted/10 p-8 text-center text-sm text-muted-foreground">
              {t.unifiedStore.skills.noMatch(query || activeLabel)}
            </div>
          )}
        </>
      )}
    </div>
  );
}
