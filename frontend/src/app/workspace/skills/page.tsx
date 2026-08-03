import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { RegistrySkillsPanel } from "@/components/store/registry-skills-panel";
import {
  CheckCircle2Icon,
  PuzzleIcon,
  SearchIcon,
  SparklesIcon,
  ToggleLeftIcon,
  ToggleRightIcon,
  WrenchIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { CapabilityQualityStrip } from "@/components/workspace/capability-quality-strip";
import {
  WorkspaceBody,
  WorkspaceContainer,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import { enableSkill } from "@/core/skills/api";

type Skill = {
  name: string;
  description?: string;
  cost_profile?: string;
  affinity?: string[];
  trusted_source?: string;
  has_tests?: boolean;
  /* Implementation note. */
  category?: string;
  /* Implementation note. */
  enabled?: boolean;
  /* Implementation note. */
  group?: string | null;
  /* Implementation note. */
  kind?: "system" | "automation" | "domain";
  market_visibility?: string;
  market_reason?: string | null;
  canonical_skill?: string | null;
};

// Keep in sync with backend SKILL_CATEGORIES · if a new category is added
// on the backend, add an id here. Labels resolve against the active locale
// at render time so switching language immediately updates group headings.
const CATEGORY_IDS = [
  "sourcing",
  "research",
  "browse",
  "file",
  "comm",
  "content",
  "memory",
  "system",
  "other",
] as const;

function InstalledSkillsPanel() {
  const { t } = useI18n();
  const CATEGORY_ORDER = useMemo(
    () =>
      CATEGORY_IDS.map((id) => ({
        id,
        label: t.skillsPage.categories[id],
      })),
    [t],
  );
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [showInternalSkills, setShowInternalSkills] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        const response = await fetch(`${getBackendBaseURL()}/api/skills`);
        if (!response.ok) {
          throw new Error(`Failed to load skills: ${response.status}`);
        }
        const data = (await response.json()) as { skills: Skill[] };
        if (!cancelled) {
          // Filter to ``kind === "domain"`` only. System skills (built-ins /
          // atomic / memory / bb / git / shell / fs_write / web / code_intel)
          // and automation skills (browser_* / screen_* / mouse_* / ...)
          // belong to other panels; this page is the "installed domain
          // skills" view. Fall back to "domain" if kind is missing so we
          // never silently hide a skill due to stale metadata.
          const onlyDomain = (data.skills ?? []).filter(
            (s) => (s.kind ?? "domain") === "domain",
          );
          setSkills(onlyDomain);
          setError(null);
        }
      } catch (err) {
        swallow(err);
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Unknown error");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Implementation note.
  const handleToggle = useCallback(
    async (name: string, currentEnabled: boolean) => {
      try {
        await enableSkill(name, !currentEnabled);
        // Optimistic update
        setSkills((prev) =>
          prev.map((s) =>
            s.name === name ? { ...s, enabled: !currentEnabled } : s,
          ),
        );
      } catch (e) {
        swallow(e);
      }
    },
    [],
  );

  // Implementation note.
  const marketSkills = useMemo(() => {
    if (showInternalSkills) return skills;
    return skills.filter((s) => (s.market_visibility ?? "market") === "market");
  }, [showInternalSkills, skills]);

  const grouped = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? marketSkills.filter((s) => {
          const name = (s.name || "").toLowerCase();
          const desc = (s.description || "").toLowerCase();
          const aff = (s.affinity || []).join(" ").toLowerCase();
          return name.includes(q) || desc.includes(q) || aff.includes(q);
        })
      : marketSkills;

    const byCat: Record<string, Skill[]> = {};
    for (const s of filtered) {
      const cat = s.category || "other";
      (byCat[cat] ||= []).push(s);
    }
    for (const cat of Object.keys(byCat)) {
      byCat[cat]!.sort((a, b) => a.name.localeCompare(b.name));
    }
    return byCat;
  }, [marketSkills, query]);

  const totalFiltered = useMemo(
    () => Object.values(grouped).reduce((sum, arr) => sum + arr.length, 0),
    [grouped],
  );
  const hiddenSkillCount = Math.max(0, skills.length - marketSkills.length);

  if (loading) {
    return <LoadingState title={t.skillsPage.loadingSkills} />;
  }

  if (error) {
    return (
      <ErrorState
        title={t.skillsPage.loadingSkills}
        detail={error}
        className="min-h-[260px]"
      />
    );
  }

  if (skills.length === 0) {
    return (
      <Empty className="mx-auto min-h-[320px] max-w-xl border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <PuzzleIcon className="size-5" />
          </EmptyMedia>
          <EmptyTitle>{t.skillsPage.noInstalledTitle}</EmptyTitle>
          <EmptyDescription>{t.skillsPage.noInstalledHint}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="space-y-6">
      {/* Implementation note. */}
      <div className="flex items-center justify-between gap-3">
        <div className="relative flex-1 max-w-md">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            data-testid="skills-search-input"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t.skillsPage.searchPlaceholder}
            className={cn(
              "w-full rounded-lg border border-border-default bg-background/60 py-2 pl-9 pr-3",
              "text-sm placeholder:text-muted-foreground/60 outline-none",
              "focus:border-primary/50 focus:ring-2 focus:ring-primary/10",
            )}
          />
        </div>
        <div className="text-xs text-muted-foreground tabular-nums">
          {query
            ? t.skillsPage.matchCount(totalFiltered, marketSkills.length)
            : t.skillsPage.totalCount(marketSkills.length)}
        </div>
        {hiddenSkillCount > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-8 rounded-full px-3 text-xs"
            onClick={() => setShowInternalSkills((value) => !value)}
          >
            {showInternalSkills
              ? "隐藏内部技能"
              : `显示内部 ${hiddenSkillCount}`}
          </Button>
        )}
      </div>

      {/* Implementation note. */}
      <div data-testid="skills-category-list" className="space-y-8">
        {CATEGORY_ORDER.filter((c) => (grouped[c.id]?.length ?? 0) > 0).map(
          (cat) => (
            <CategorySection
              key={cat.id}
              title={cat.label}
              count={grouped[cat.id]!.length}
              skills={grouped[cat.id]!}
              onToggle={handleToggle}
            />
          ),
        )}
        {totalFiltered === 0 && (
          <Empty className="min-h-[260px]">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <SearchIcon />
              </EmptyMedia>
              <EmptyTitle>{t.skillsPage.noMatch(query)}</EmptyTitle>
            </EmptyHeader>
          </Empty>
        )}
      </div>
    </div>
  );
}

function CategorySection({
  title,
  count,
  skills,
  onToggle,
}: {
  title: string;
  count: number;
  skills: Skill[];
  onToggle?: (name: string, enabled: boolean) => void;
}) {
  return (
    <section>
      <div className="mb-3 flex items-baseline gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="text-xs text-muted-foreground tabular-nums">
          {count}
        </span>
      </div>
      <div
        data-testid="skills-card-grid"
        className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3"
      >
        {skills.map((s) => (
          <SkillCard key={s.name} skill={s} onToggle={onToggle} />
        ))}
      </div>
    </section>
  );
}

function SkillCard({
  skill,
  onToggle,
}: {
  skill: Skill;
  onToggle?: (name: string, enabled: boolean) => void;
}) {
  const { t } = useI18n();
  const tested = skill.has_tests;
  const isEnabled = skill.enabled !== false; // Implementation note.
  return (
    <div
      className={cn(
        "group relative grid grid-cols-[2rem_minmax(0,1fr)_auto] items-start gap-3 rounded-lg border border-border-default",
        "bg-background/60 px-3 py-2.5 transition-colors",
        "hover:border-border-strong hover:bg-background",
        !isEnabled && "opacity-60",
      )}
      title={[
        skill.trusted_source &&
          t.skillsPage.tooltipSource(skill.trusted_source),
        skill.cost_profile && t.skillsPage.tooltipCost(skill.cost_profile),
        (skill.affinity || []).length > 0 &&
          t.skillsPage.tooltipTags((skill.affinity || []).join(", ")),
        tested ? t.skillsPage.tooltipTested : t.skillsPage.tooltipUntested,
        skill.market_reason,
      ]
        .filter(Boolean)
        .join("\n")}
    >
      <div
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-md",
          isEnabled
            ? "bg-gradient-to-br from-purple-500/20 to-blue-500/20 text-purple-500"
            : "bg-muted/60 text-muted-foreground",
        )}
      >
        <WrenchIcon className="size-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <div className="truncate text-sm font-medium">{skill.name}</div>
          {tested && (
            <span title={t.skillsPage.testedDotTitle}>
              <CheckCircle2Icon className="size-3.5 shrink-0 text-emerald-500" />
            </span>
          )}
          {(skill.market_visibility ?? "market") !== "market" && (
            <span className="rounded border border-border-default bg-muted/35 px-1 py-0.5 text-xs leading-none text-muted-foreground">
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
        <div className="mt-0.5 line-clamp-1 text-xs leading-snug text-muted-foreground">
          {skill.description || t.skillsPage.noDescription}
        </div>
        {(skill.affinity || []).length > 0 && (
          <div className="mt-1 flex max-w-full gap-1 overflow-hidden">
            {(skill.affinity || []).slice(0, 3).map((tag) => (
              <span
                key={tag}
                className="max-w-28 truncate rounded border border-border-default bg-muted/35 px-1.5 py-0.5 text-xs leading-none text-muted-foreground"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>
      {/* Implementation note. */}
      {onToggle && (
        <button
          type="button"
          onClick={() => onToggle(skill.name, isEnabled)}
          className="shrink-0 p-1 rounded-md hover:bg-muted/80 transition-colors"
          title={isEnabled ? "点击禁用" : "点击启用"}
        >
          {isEnabled ? (
            <ToggleRightIcon className="size-5 text-emerald-500" />
          ) : (
            <ToggleLeftIcon className="size-5 text-muted-foreground" />
          )}
        </button>
      )}
    </div>
  );
}

export default function SkillsPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("installed");
  const createSkillPrompt = [
    "创建一个新的技能，请按下面结构和我确认后再生成：",
    "",
    "1. 技能名称：",
    "2. 使用场景：",
    "3. 输入参数：",
    "4. 输出结果：",
    "5. 安全边界：",
    "6. 验证用例：",
  ].join("\n");

  return (
    <WorkspaceContainer>
      <WorkspaceBody className="p-0">
        <div className="flex flex-col gap-4 p-4 w-full min-h-full">
          <CapabilityQualityStrip surface="skills" />
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <div className="flex size-6 items-center justify-center rounded bg-purple-500/10">
                  <PuzzleIcon className="size-4 text-purple-500" />
                </div>
                <h1 className="text-lg font-bold">{t.skillsPage.pageTitle}</h1>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {t.skillsPage.pageSubtitle}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground/80">
                {t.skillsPage.disclaimer}
              </p>
            </div>
            <Button
              size="sm"
              className="bg-gradient-to-r from-purple-500 to-blue-500 text-white h-7 text-xs"
              onClick={() =>
                navigate(
                  `/workspace/realtime/new?mode=skill&draft=${encodeURIComponent(createSkillPrompt)}`,
                )
              }
            >
              <SparklesIcon className="mr-1 size-3.5" />
              {t.skillsPage.createButton}
            </Button>
          </div>

          <Tabs
            value={activeTab}
            onValueChange={setActiveTab}
            className="w-full flex-1 flex flex-col"
          >
            <TabsList className="rounded-lg bg-white/55 p-1 dark:bg-white/[0.04] w-fit">
              <TabsTrigger value="installed">
                {t.skillsPage.tabInstalled}
              </TabsTrigger>
              <TabsTrigger value="registry">商城</TabsTrigger>
            </TabsList>

            <div className="mt-3 flex-1 w-full">
              <TabsContent
                value="installed"
                className="workspace-panel w-full rounded-lg p-4 shadow-[var(--shadow-xs)] border border-border-default min-h-[500px] outline-none"
              >
                <InstalledSkillsPanel />
              </TabsContent>
              <TabsContent
                value="registry"
                className="workspace-panel w-full rounded-lg shadow-[var(--shadow-xs)] border border-border-default min-h-[500px] outline-none"
              >
                <RegistrySkillsPanel />
              </TabsContent>
            </div>
          </Tabs>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
