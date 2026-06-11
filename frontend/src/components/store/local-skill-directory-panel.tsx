import { type ReactNode, useMemo, useState } from "react";
import {
  CheckCircle2,
  Loader2,
  Plus,
  Puzzle,
  Search,
  Wrench,
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

  const localSkills = useMemo(() => {
    return (skills as LocalSkill[])
      .filter((skill) => (skill.kind ?? "domain") === "domain")
      .map((skill) => ({ ...skill, localCategory: classifyLocalSkill(skill) }))
      .sort((a, b) => {
        if (a.enabled !== b.enabled) return a.enabled ? -1 : 1;
        return a.name.localeCompare(b.name);
      });
  }, [skills]);

  const categoryCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const skill of localSkills) {
      counts.set(skill.localCategory, (counts.get(skill.localCategory) ?? 0) + 1);
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

  const handleCategorySelect = (nextCategory: string) => {
    setCategory(nextCategory);
    onDirectorySelect?.();
  };

  const allButton = (
    <Button
      size="sm"
      variant={!showSkillPacks && category === "all" ? "secondary" : "ghost"}
      className="h-9 shrink-0 rounded-full px-3 text-xs"
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

      <div className="flex gap-1.5 overflow-x-auto pb-1">
        {skillPacksContent && (
          <Button
            size="sm"
            variant={showSkillPacks ? "secondary" : "ghost"}
            className="h-9 shrink-0 rounded-full px-3 text-xs"
            onClick={onSkillPacksSelect}
          >
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
              variant={!showSkillPacks && category === item.key ? "secondary" : "ghost"}
              className="h-9 shrink-0 rounded-full px-3 text-xs"
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
            variant={!showSkillPacks && category === "other" ? "secondary" : "ghost"}
            className="h-9 shrink-0 rounded-full px-3 text-xs"
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
              {t.unifiedStore.skills.visibleCount(activeLabel, visibleSkills.length)}
            </span>
            <span>
              {t.unifiedStore.skills.enabledCount(
                localSkills.filter((skill) => skill.enabled).length,
              )}
            </span>
          </div>

          {visibleSkills.length ? (
            <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-x-12 gap-y-5">
              {visibleSkills.map((skill) => (
                <div
                  key={skill.name}
                  className={cn(
                    "group flex min-w-0 items-center gap-4 rounded-xl px-3 py-3 transition-colors hover:bg-muted/35",
                    !skill.enabled && "text-muted-foreground",
                  )}
                >
                  <div
                    className={cn(
                      "flex size-12 shrink-0 items-center justify-center rounded-xl border border-border/50 bg-background shadow-sm",
                      !skill.enabled && "bg-muted/40",
                    )}
                  >
                    <Wrench
                      className={cn(
                        "size-5",
                        skill.enabled ? "text-primary" : "text-muted-foreground",
                      )}
                    />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-2">
                      <h3 className="truncate text-[15px] font-semibold leading-5 text-foreground">
                        {skill.name}
                      </h3>
                      {skill.has_tests && (
                        <CheckCircle2 className="size-3.5 shrink-0 text-emerald-500" />
                      )}
                    </div>
                    <p className="mt-1 line-clamp-1 text-sm leading-5 text-muted-foreground">
                      {skill.description || t.unifiedStore.skills.noDescription}
                    </p>
                  </div>
                  <button
                    type="button"
                    aria-label={t.unifiedStore.skills.toggleSkillAria(skill.enabled, skill.name)}
                    disabled={isPending}
                    onClick={() =>
                      setSkillEnabled({
                        skillName: skill.name,
                        enabled: !skill.enabled,
                      })
                    }
                    className={cn(
                      "flex size-9 shrink-0 items-center justify-center rounded-xl bg-muted/55 transition-colors hover:bg-muted",
                      skill.enabled
                        ? "bg-transparent text-muted-foreground/70"
                        : "text-foreground",
                    )}
                  >
                    {skill.enabled ? (
                      <CheckCircle2 className="size-5" />
                    ) : (
                      <Plus className="size-5" />
                    )}
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-border/70 bg-muted/10 p-8 text-center text-sm text-muted-foreground">
              {t.unifiedStore.skills.noMatch(query || activeLabel)}
            </div>
          )}
        </>
      )}
    </div>
  );
}
