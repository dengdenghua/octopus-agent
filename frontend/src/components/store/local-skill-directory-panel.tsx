import { type ReactNode, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  AtSign,
  Award,
  Banknote,
  BarChart3,
  Beaker,
  Binary,
  BookMarked,
  BookOpen,
  Bot,
  Boxes,
  Brain,
  BriefcaseBusiness,
  Brush,
  Bug,
  Building2,
  Calculator,
  Calendar,
  CalendarCheck,
  Camera,
  CheckCircle2,
  CheckSquare,
  ClipboardCheck,
  Clock,
  Cloud,
  CloudCog,
  Code2,
  Cog,
  Coins,
  Compass,
  Component,
  Container,
  Cpu,
  CreditCard,
  Database,
  DollarSign,
  Eraser,
  Eye,
  File,
  FileBadge,
  FileBarChart,
  FileCheck,
  FileCode,
  FileSpreadsheet,
  FileText,
  Film,
  Fingerprint,
  Flag,
  FlaskConical,
  FolderOpen,
  GitBranch,
  GitCommit,
  Globe,
  GraduationCap,
  Handshake,
  HardDrive,
  Hash,
  Headphones,
  Heart,
  Image,
  Inbox,
  Key,
  Landmark,
  Languages,
  Layers,
  LayoutDashboard,
  LayoutTemplate,
  Library,
  Lightbulb,
  LineChart,
  ListTodo,
  Loader2,
  Lock,
  Mail,
  Medal,
  Megaphone,
  MessagesSquare,
  Mic,
  Microscope,
  Milestone,
  Monitor,
  Music,
  Network,
  Package,
  Palette,
  PenLine,
  Pencil,
  PencilRuler,
  Phone,
  PieChart,
  PiggyBank,
  Plus,
  Presentation,
  Puzzle,
  Quote,
  Radar,
  Receipt,
  Rocket,
  Route,
  Scale,
  ScanLine,
  Scroll,
  ScrollText,
  Search,
  SearchCheck,
  Send,
  Server,
  Settings2,
  Share,
  Shield,
  ShieldAlert,
  ShieldCheck,
  ShoppingBag,
  ShoppingCart,
  Siren,
  Sparkles,
  Star,
  Store,
  Table,
  Tag,
  Target,
  Terminal,
  TestTube,
  ThumbsUp,
  Timer,
  TrendingUp,
  Type,
  UserCheck,
  Users,
  Video,
  Wallet,
  Workflow,
  Wrench,
  Zap,
  type LucideIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
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

const CATEGORY_ICON_POOL: Record<string, LucideIcon[]> = {
  "browser-search": [SearchCheck, Globe, Compass, Radar, ScanLine],
  "agent-tools": [Bot, Cpu, Puzzle, Workflow, Brain],
  "webapp-frontend": [Layers, LayoutDashboard, Component, Monitor, Globe],
  "backend-api": [Server, Database, Network, CloudCog, GitBranch],
  "code-quality": [Code2, GitCommit, Bug, ShieldCheck, FileCode],
  "devops-cloud": [Cloud, Server, Container, HardDrive, Terminal],
  "office-docs": [FileText, FileSpreadsheet, FileCheck, ClipboardCheck, ScrollText],
  "slides-report": [Presentation, Monitor, LayoutTemplate, Image, Star],
  "chart-viz": [BarChart3, FileBarChart, LineChart, PieChart, Activity],
  "writing-editing": [PenLine, Pencil, PencilRuler, Type, BookOpen],
  "marketing-copy": [Megaphone, Sparkles, Tag, Target, Send],
  "seo-growth": [TrendingUp, Search, ArrowUpRight, Hash, Eye],
  ecommerce: [ShoppingCart, ShoppingBag, Store, CreditCard, Package],
  "market-product": [BriefcaseBusiness, Handshake, TrendingUp, ShoppingCart, Target, Medal],
  "project-goal": [CheckCircle2, Flag, Target, Milestone, ListTodo],
  "finance-stock": [Wallet, Banknote, DollarSign, Coins, TrendingUp],
  "finance-model": [Calculator, FileSpreadsheet, Banknote, PiggyBank, Coins],
  "data-stats": [BarChart3, FileBarChart, Table, Binary, Activity],
  "data-insight": [LineChart, Activity, Eye, Lightbulb, Microscope],
  "academic-paper": [GraduationCap, BookOpen, BookMarked, Library, Scroll],
  "deep-research": [SearchCheck, Microscope, FlaskConical, Beaker, TestTube],
  "education-coach": [GraduationCap, BookOpen, Lightbulb, Star, Award],
  "hr-career": [Users, UserCheck, BriefcaseBusiness, Award, Medal],
  "email-comms": [Mail, Send, MessagesSquare, Inbox, AtSign],
  "legal-compliance": [Scale, Shield, ShieldCheck, ScrollText, FileBadge],
  "security-audit": [ShieldAlert, Lock, Fingerprint, Key, Bug],
  "design-creative": [Palette, Brush, PencilRuler, Image, Layers],
  "media-audio-video": [Video, Film, Music, Mic, Camera],
  "personal-productivity": [CheckSquare, Timer, Clock, ListTodo, CalendarCheck],
  other: [Wrench, Cog, Settings2, Puzzle, Sparkles],
};

const CATEGORY_TONE_MAP: Record<string, string> = {
  "browser-search":
    "border-sky-500/30 bg-gradient-to-br from-sky-500/20 to-blue-400/10 text-sky-600 dark:text-sky-300 shadow-sm shadow-sky-500/15",
  "agent-tools":
    "border-emerald-500/30 bg-gradient-to-br from-emerald-500/20 to-teal-400/10 text-emerald-600 dark:text-emerald-300 shadow-sm shadow-emerald-500/15",
  "webapp-frontend":
    "border-violet-500/30 bg-gradient-to-br from-violet-500/20 to-purple-400/10 text-violet-600 dark:text-violet-300 shadow-sm shadow-violet-500/15",
  "backend-api":
    "border-indigo-500/30 bg-gradient-to-br from-indigo-500/20 to-blue-500/10 text-indigo-600 dark:text-indigo-300 shadow-sm shadow-indigo-500/15",
  "code-quality":
    "border-blue-500/30 bg-gradient-to-br from-blue-500/20 to-cyan-400/10 text-blue-600 dark:text-blue-300 shadow-sm shadow-blue-500/15",
  "devops-cloud":
    "border-orange-500/30 bg-gradient-to-br from-orange-500/20 to-amber-400/10 text-orange-600 dark:text-orange-300 shadow-sm shadow-orange-500/15",
  "office-docs":
    "border-rose-500/30 bg-gradient-to-br from-rose-500/20 to-pink-400/10 text-rose-600 dark:text-rose-300 shadow-sm shadow-rose-500/15",
  "slides-report":
    "border-fuchsia-500/30 bg-gradient-to-br from-fuchsia-500/20 to-pink-400/10 text-fuchsia-600 dark:text-fuchsia-300 shadow-sm shadow-fuchsia-500/15",
  "chart-viz":
    "border-cyan-500/30 bg-gradient-to-br from-cyan-500/20 to-sky-400/10 text-cyan-600 dark:text-cyan-300 shadow-sm shadow-cyan-500/15",
  "writing-editing":
    "border-teal-500/30 bg-gradient-to-br from-teal-500/20 to-cyan-400/10 text-teal-600 dark:text-teal-300 shadow-sm shadow-teal-500/15",
  "marketing-copy":
    "border-pink-500/30 bg-gradient-to-br from-pink-500/20 to-rose-400/10 text-pink-600 dark:text-pink-300 shadow-sm shadow-pink-500/15",
  "seo-growth":
    "border-green-500/30 bg-gradient-to-br from-green-500/20 to-emerald-400/10 text-green-600 dark:text-green-300 shadow-sm shadow-green-500/15",
  ecommerce:
    "border-amber-500/30 bg-gradient-to-br from-amber-500/20 to-yellow-400/10 text-amber-600 dark:text-amber-300 shadow-sm shadow-amber-500/15",
  "market-product":
    "border-yellow-500/30 bg-gradient-to-br from-yellow-500/20 to-orange-300/10 text-yellow-600 dark:text-yellow-300 shadow-sm shadow-yellow-500/15",
  "project-goal":
    "border-green-500/30 bg-gradient-to-br from-green-500/20 to-teal-400/10 text-green-600 dark:text-green-300 shadow-sm shadow-green-500/15",
  "finance-stock":
    "border-emerald-500/30 bg-gradient-to-br from-emerald-500/20 to-green-400/10 text-emerald-600 dark:text-emerald-300 shadow-sm shadow-emerald-500/15",
  "finance-model":
    "border-lime-500/30 bg-gradient-to-br from-lime-500/20 to-green-400/10 text-lime-600 dark:text-lime-300 shadow-sm shadow-lime-500/15",
  "data-stats":
    "border-indigo-500/30 bg-gradient-to-br from-indigo-500/20 to-violet-400/10 text-indigo-600 dark:text-indigo-300 shadow-sm shadow-indigo-500/15",
  "data-insight":
    "border-purple-500/30 bg-gradient-to-br from-purple-500/20 to-violet-400/10 text-purple-600 dark:text-purple-300 shadow-sm shadow-purple-500/15",
  "academic-paper":
    "border-blue-500/30 bg-gradient-to-br from-blue-500/20 to-indigo-400/10 text-blue-600 dark:text-blue-300 shadow-sm shadow-blue-500/15",
  "deep-research":
    "border-cyan-500/30 bg-gradient-to-br from-cyan-500/20 to-blue-400/10 text-cyan-600 dark:text-cyan-300 shadow-sm shadow-cyan-500/15",
  "education-coach":
    "border-violet-500/30 bg-gradient-to-br from-violet-500/20 to-indigo-400/10 text-violet-600 dark:text-violet-300 shadow-sm shadow-violet-500/15",
  "hr-career":
    "border-orange-500/30 bg-gradient-to-br from-orange-500/20 to-red-300/10 text-orange-600 dark:text-orange-300 shadow-sm shadow-orange-500/15",
  "email-comms":
    "border-sky-500/30 bg-gradient-to-br from-sky-500/20 to-cyan-400/10 text-sky-600 dark:text-sky-300 shadow-sm shadow-sky-500/15",
  "legal-compliance":
    "border-border bg-gradient-to-br from-muted to-background text-muted-foreground shadow-sm",
  "security-audit":
    "border-red-500/30 bg-gradient-to-br from-red-500/20 to-rose-400/10 text-red-600 dark:text-red-300 shadow-sm shadow-red-500/15",
  "design-creative":
    "border-pink-500/30 bg-gradient-to-br from-pink-500/20 to-fuchsia-400/10 text-pink-600 dark:text-pink-300 shadow-sm shadow-pink-500/15",
  "media-audio-video":
    "border-purple-500/30 bg-gradient-to-br from-purple-500/20 to-fuchsia-400/10 text-purple-600 dark:text-purple-300 shadow-sm shadow-purple-500/15",
  "personal-productivity":
    "border-teal-500/30 bg-gradient-to-br from-teal-500/20 to-green-400/10 text-teal-600 dark:text-teal-300 shadow-sm shadow-teal-500/15",
  other:
    "border-border bg-gradient-to-br from-muted to-background text-foreground/80 shadow-sm",
};

function hashString(str: string): number {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = (h << 5) - h + str.charCodeAt(i);
    h |= 0;
  }
  return Math.abs(h);
}

function getSkillIcon(category: string, skillName: string): LucideIcon {
  const pool = CATEGORY_ICON_POOL[category] ?? CATEGORY_ICON_POOL.other ?? [Wrench];
  return pool[hashString(skillName) % pool.length] ?? pool[0] ?? Wrench;
}

function skillTone(category: string): string {
  return (
    CATEGORY_TONE_MAP[category] ??
    "border-border bg-gradient-to-br from-muted to-background text-foreground/80 shadow-sm"
  );
}

type LocalSkillDirectoryPanelProps = {
  searchQuery?: string;
  allButtonPosition?: "start" | "end";
  onDirectorySelect?: () => void;
  onSkillPacksSelect?: () => void;
  skillPacksContent?: ReactNode;
  skillPacksSelected?: boolean;
};

export function LocalSkillDirectoryPanel({
  searchQuery: externalSearchQuery = "",
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
  const [query, setQuery] = useState(externalSearchQuery);
  const [category, setCategory] = useState("all");
  const [showInternalSkills, setShowInternalSkills] = useState(false);

  useEffect(() => {
    if (externalSearchQuery !== query) {
      setQuery(externalSearchQuery);
    }
  }, [externalSearchQuery]);

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

  const allActive = !showSkillPacks && category === "all";
  const allButton = (
    <Button
      size="sm"
      variant="ghost"
      onClick={() => handleCategorySelect("all")}
      className={cn(
        "h-8 shrink-0 gap-1 rounded-full px-3 text-xs transition-colors",
        allActive
          ? "bg-primary/10 text-foreground hover:bg-primary/15"
          : "bg-muted/40 text-muted-foreground hover:bg-muted/60 hover:text-foreground",
      )}
    >
      {t.unifiedStore.skills.all}
      <span
        className={cn(
          "ml-0.5 text-[10px]",
          allActive ? "text-primary/70" : "text-muted-foreground/70",
        )}
      >
        {localSkills.length}
      </span>
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
        title={t.localSkillDirectory.errorTitle}
        detail={error.message}
        retryLabel={t.localSkillDirectory.retryLabel}
        retrying={isFetching}
        onRetry={() => void refetch()}
      />
    );
  }

  return (
    <div className="flex w-full flex-col gap-5">
      {/* Filter bar */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-wrap gap-1.5">
          {skillPacksContent && (
            <Button
              size="sm"
              variant="ghost"
              onClick={onSkillPacksSelect}
              className={cn(
                "h-8 shrink-0 gap-1.5 rounded-full px-3 text-xs transition-colors",
                showSkillPacks
                  ? "bg-primary/10 text-foreground hover:bg-primary/15"
                  : "bg-muted/40 text-muted-foreground hover:bg-muted/60 hover:text-foreground",
              )}
            >
              <Boxes className="h-3.5 w-3.5" />
              {t.metaSkills.title}
            </Button>
          )}
          {allButtonPosition === "start" && allButton}
          {LOCAL_SKILL_CATEGORIES.map((item) => {
            const count = categoryCounts.get(item.key) ?? 0;
            if (!count) return null;
            const active = !showSkillPacks && category === item.key;
            return (
              <Button
                key={item.key}
                size="sm"
                variant="ghost"
                onClick={() => handleCategorySelect(item.key)}
                className={cn(
                  "h-8 shrink-0 gap-1 rounded-full px-3 text-xs transition-colors",
                  active
                    ? "bg-primary/10 text-foreground hover:bg-primary/15"
                    : "bg-muted/40 text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                )}
              >
                {categoryLabel(item.key)}
                <span
                  className={cn(
                    "ml-0.5 text-[10px]",
                    active ? "text-primary/70" : "text-muted-foreground/70",
                  )}
                >
                  {count}
                </span>
              </Button>
            );
          })}
          {(categoryCounts.get("other") ?? 0) > 0 && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => handleCategorySelect("other")}
              className={cn(
                "h-8 shrink-0 gap-1 rounded-full px-3 text-xs transition-colors",
                !showSkillPacks && category === "other"
                  ? "bg-primary/10 text-foreground hover:bg-primary/15"
                  : "bg-muted/40 text-muted-foreground hover:bg-muted/60 hover:text-foreground",
              )}
            >
              {t.unifiedStore.skills.other}
              <span
                className={cn(
                  "ml-0.5 text-[10px]",
                  !showSkillPacks && category === "other"
                    ? "text-primary/70"
                    : "text-muted-foreground/70",
                )}
              >
                {categoryCounts.get("other")}
              </span>
            </Button>
          )}
          {allButtonPosition === "end" && allButton}
        </div>

        {!showSkillPacks && (
          <div className="flex items-center gap-3 rounded-full border border-border/50 bg-muted/30 px-3 py-1.5 text-xs">
            <span className="text-muted-foreground">
              {t.unifiedStore.skills.visibleCount(
                t.unifiedStore.skills.all,
                localSkills.length,
              )}
            </span>
            <span className="text-border/80">|</span>
            <span className="text-muted-foreground">
              {t.unifiedStore.skills.enabledCount(enabledSkills)}
            </span>
            {hiddenSkillCount > 0 && (
              <>
                <span className="text-border/80">|</span>
                <button
                  type="button"
                  className="text-muted-foreground transition-colors hover:text-foreground"
                  onClick={() => setShowInternalSkills((value) => !value)}
                >
                  {showInternalSkills
                    ? t.localSkillDirectory.hideInternalSkills
                    : t.localSkillDirectory.showInternalSkills(
                        hiddenSkillCount,
                      )}
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {showSkillPacks ? (
        <div>{skillPacksContent}</div>
      ) : (
        <>
          {visibleSkills.length ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {visibleSkills.map((skill) => {
                const SkillIcon = getSkillIcon(
                  skill.localCategory,
                  skill.name,
                );
                return (
                  <article
                      key={skill.name}
                      className={cn(
                        "group flex min-w-0 flex-col rounded-xl border border-border/60 bg-card/70 p-3.5 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/25 hover:bg-card hover:shadow-md",
                        !skill.enabled && "bg-muted/15 text-muted-foreground",
                      )}
                    >
                    <div className="flex min-w-0 items-start gap-3">
                      <div
                        className={cn(
                          "flex size-11 shrink-0 items-center justify-center rounded-lg border shadow-sm",
                          skill.enabled
                            ? skillTone(skill.localCategory)
                            : "border-border/50 bg-muted/35 text-muted-foreground",
                        )}
                      >
                        <SkillIcon className="size-5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex min-w-0 items-center gap-2">
                          <h3 className="truncate text-sm font-semibold leading-5 text-foreground">
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
                              {t.localSkillDirectory.verified}
                            </span>
                          )}
                          {(skill.market_visibility ?? "market") !==
                            "market" && (
                            <span
                              title={
                                skill.canonical_skill
                                  ? `${skill.market_reason ?? t.localSkillDirectory.marketReasonMerged}：${skill.canonical_skill}`
                                  : (skill.market_reason ??
                                    t.localSkillDirectory.internalSkill)
                              }
                              className="rounded-full bg-muted-foreground/10 px-2 py-0.5 text-[10px] font-medium text-muted-foreground"
                            >
                              {skill.market_visibility === "duplicate"
                                ? t.localSkillDirectory.visibilityDuplicate
                                : skill.market_visibility === "provider"
                                  ? t.localSkillDirectory.visibilityProvider
                                  : skill.market_visibility === "specialized"
                                    ? t.localSkillDirectory.visibilitySpecialized
                                    : skill.market_visibility === "deprecated"
                                      ? t.localSkillDirectory.visibilityDeprecated
                                      : t.localSkillDirectory.visibilityInternal}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    <p className="mt-3 line-clamp-2 flex-1 text-xs leading-4 text-muted-foreground">
                      {skill.description || t.unifiedStore.skills.noDescription}
                    </p>
                    <div className="mt-3 flex items-center justify-between gap-3 border-t border-border/40 pt-2.5">
                      <span
                        title={skill.trusted_source ?? undefined}
                        className="truncate text-[11px] text-muted-foreground"
                      >
                        {skill.has_tests
                          ? t.localSkillDirectory.verified
                          : t.localSkillDirectory.localCapability}
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
                            {t.localSkillDirectory.enabled}
                          </>
                        ) : (
                          <>
                            <Plus className="size-3.5" />
                            {t.localSkillDirectory.enable}
                          </>
                        )}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="flex flex-col items-center rounded-xl border border-dashed border-border/60 bg-muted/10 py-16 text-center text-sm text-muted-foreground">
              {t.unifiedStore.skills.noMatch(query || activeLabel)}
            </div>
          )}
        </>
      )}
    </div>
  );
}
