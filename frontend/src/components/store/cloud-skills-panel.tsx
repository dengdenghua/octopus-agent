import { skillDescription } from "@/core/utils/display-value";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  CheckIcon,
  CloudIcon,
  InfoIcon,
  Loader2Icon,
  SearchIcon,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { serializeComposerDraft } from "@/core/threads/composer-capability-refs";
import { SkillIcon } from "./skill-icon";
import { AgentAvatar } from "@/components/workspace/agent-avatar";
import { SKILL_CATEGORIES, skillCategories } from "./skill-categories";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  fetchCloudInstalled,
  fetchCloudSkills,
  fetchUnifiedAssets,
  streamInstallCloudSkill,
  manageCloudSkill,
  type CloudInstalledStatus,
  type CloudSkillInstallProgress,
  type CloudSkillItem,
  type CloudSkillsResponse,
  type UnifiedAsset,
} from "@/core/agents/agent-world-api";

const PAGE_SIZE = 40;
const SKILL_NAMES: Record<string, string> = {
  "academic-paper-expert": "学术论文助手",
  "ad-copywriter": "广告文案",
  "ad-creative": "广告创意",
  "agent-generator": "智能体生成器",
  "skill-creator": "技能创建器",
  "plugin-creator": "插件创建器",
  "agent-visual-kit": "智能体视觉设计",
  "agnes-image-generate": "AI 图像生成",
  "agnes-video-generate": "AI 视频生成",
  "agnes-video-poll": "视频生成进度查询",
  "api-and-interface-design": "API 与接口设计",
  "api-doc-gen": "API 文档生成",
  "api-shape-explorer": "API 方案探索",
  "auto-hypothesis-test": "统计假设检验",
  "auto-stat-test": "自动统计检验",
  "backend-building": "后端开发",
};

function normalizeSkillName(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-");
}

function localSkillAliases(asset: UnifiedAsset) {
  return [asset.id, asset.name, asset.name_zh]
    .filter((value): value is string => Boolean(value?.trim()))
    .map(normalizeSkillName);
}

interface SkillEntry {
  key: string;
  name: string;
  description: string;
  version?: string;
  author?: string;
  source?: string;
  cloud: CloudSkillItem | null;
  local: UnifiedAsset | null;
}

function entryCategories(entry: SkillEntry): string[] {
  const name = entry.cloud?.original_name || entry.name;
  return ["skill-creator", "plugin-creator", "agent-generator"].includes(name)
    ? ["开发工具"]
    : skillCategories(entry.cloud?.tags);
}

function sourceLabel(source?: string) {
  const labels: Record<string, string> = {
    builtin: "系统内置",
    local: "本地技能",
    imported: "本地导入",
    octopus: "echo",
    "octopus-repository": "echo",
    echo: "echo",
    openai: "OpenAI 官方",
    anthropic: "Anthropic 官方",
    vercel: "Vercel 官方",
    "minimax-design": "MiniMax Design",
    "skills.sh": "Skills.sh 社区",
  };
  return source?.trim() ? labels[source] || source : "未提供";
}

function authorLabel(author?: string, source?: string) {
  if (
    ["octopus", "octopus-repository", "echo"].includes(source ?? "") ||
    /^(octopus-agent|octopus|echo)$/i.test(author?.trim() ?? "")
  )
    return "echo";
  return author?.trim() || "未提供";
}

export function CloudSkillsPanel({
  searchQuery = "",
  onClearSearch,
}: {
  searchQuery?: string;
  onClearSearch?: () => void;
}) {
  const navigate = useNavigate();
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [infoOpen, setInfoOpen] = useState(false);
  const [installedOnly, setInstalledOnly] = useState(false);
  const [tagFilter, setTagFilter] = useState("");
  const [cloudSkills, setCloudSkills] = useState<CloudSkillItem[]>([]);
  const [externalSkills, setExternalSkills] = useState<CloudSkillItem[]>([]);
  const [sourceFilter, setSourceFilter] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [skillUsers, setSkillUsers] =
    useState<CloudInstalledStatus["skill_users"]>(undefined);
  const [externalLoading, setExternalLoading] = useState(true);
  const [sourceStates, setSourceStates] = useState<
    NonNullable<CloudSkillsResponse["meta"]>["sources"]
  >([]);
  const [localSkills, setLocalSkills] = useState<UnifiedAsset[]>([]);
  const [installedNames, setInstalledNames] = useState<Set<string>>(new Set());
  const [skillStates, setSkillStates] = useState<
    NonNullable<CloudInstalledStatus["skill_states"]>
  >({});
  const [managing, setManaging] = useState(false);
  const [confirmRemoval, setConfirmRemoval] = useState<string | null>(null);
  const [progress, setProgress] = useState<
    Record<string, CloudSkillInstallProgress>
  >({});
  const [loading, setLoading] = useState(true);
  const [cloudError, setCloudError] = useState<string | null>(null);
  const [detail, setDetail] = useState<SkillEntry | null>(null);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [searchQuery, sourceFilter, installedOnly, tagFilter, roleFilter]);

  const load = useCallback(async () => {
    setLoading(true);
    setCloudError(null);
    const [cloudResult, installedResult, localResult] =
      await Promise.allSettled([
        fetchCloudSkills({ limit: 500 }),
        fetchCloudInstalled(),
        fetchUnifiedAssets({ kind: "skill", limit: 500, offset: 0 }),
      ]);

    if (cloudResult.status === "fulfilled") {
      setCloudSkills(cloudResult.value.items);
    } else {
      setCloudSkills([]);
      setCloudError(
        cloudResult.reason instanceof Error
          ? cloudResult.reason.message
          : String(cloudResult.reason),
      );
    }
    setInstalledNames(
      new Set(
        installedResult.status === "fulfilled"
          ? installedResult.value.skills.map(normalizeSkillName)
          : [],
      ),
    );
    setSkillStates(
      installedResult.status === "fulfilled"
        ? (installedResult.value.skill_states ?? {})
        : {},
    );
    setSkillUsers(
      installedResult.status === "fulfilled"
        ? installedResult.value.skill_users
        : undefined,
    );
    setLocalSkills(
      installedResult.status === "fulfilled" &&
        installedResult.value.local_skills
        ? installedResult.value.local_skills
        : localResult.status === "fulfilled"
          ? localResult.value.items
          : [],
    );
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const controller = new AbortController();
    setExternalLoading(true);
    const timer = setTimeout(
      () => {
        void fetchCloudSkills({
          source: "external",
          search: searchQuery.trim(),
          limit: 500,
          signal: controller.signal,
        })
          .then((result) => {
            if (controller.signal.aborted) return;
            setExternalSkills(result.items);
            setSourceStates(result.meta?.sources ?? []);
          })
          .catch(() => {
            if (controller.signal.aborted) return;
            setExternalSkills([]);
            setSourceStates([
              { source: "external", state: "unavailable", count: 0 },
            ]);
          })
          .finally(() => {
            if (!controller.signal.aborted) setExternalLoading(false);
          });
      },
      searchQuery.trim() ? 350 : 0,
    );
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [searchQuery]);

  const entries = useMemo(() => {
    const localByAlias = new Map<string, UnifiedAsset>();
    for (const skill of localSkills) {
      for (const alias of localSkillAliases(skill))
        localByAlias.set(alias, skill);
    }

    const usedLocal = new Set<UnifiedAsset>();
    const remote = Array.from(
      new Map(
        [...cloudSkills, ...externalSkills].map((skill) => [skill.name, skill]),
      ).values(),
    );
    const merged: SkillEntry[] = remote.map((skill) => {
      const local =
        [skill.name, ...(skill.aliases ?? [])]
          .map((name) => localByAlias.get(normalizeSkillName(name)))
          .find(Boolean) ?? null;
      if (local) usedLocal.add(local);
      return {
        key: `cloud:${skill.name}`,
        name: skill.name,
        description: skillDescription(skill.description),
        version: skill.version,
        author: skill.author?.trim() || local?.author,
        source: skill.source?.trim() || local?.source,
        cloud: skill,
        local,
      };
    });
    for (const skill of localSkills) {
      if (usedLocal.has(skill)) continue;
      merged.push({
        key: `local:${skill.source}:${skill.id}`,
        name: skill.name_zh || skill.name || skill.id,
        description: skillDescription(skill.description),
        version: skill.version,
        author: skill.author,
        source: skill.source,
        cloud: null,
        local: skill,
      });
    }
    return merged;
  }, [cloudSkills, externalSkills, localSkills]);

  const runtimeId = (entry: SkillEntry) =>
    entry.local?.name ||
    [entry.name, ...(entry.cloud?.aliases ?? [])].find((name) =>
      installedNames.has(normalizeSkillName(name)),
    ) ||
    entry.name;
  const usersFor = (entry: SkillEntry) => skillUsers?.[runtimeId(entry)] ?? [];
  const isInstalled = (entry: SkillEntry) =>
    Boolean(entry.local) ||
    [entry.name, ...(entry.cloud?.aliases ?? [])].some((name) =>
      installedNames.has(normalizeSkillName(name)),
    );
  const displayName = (entry: SkillEntry) =>
    entry.local?.name_zh ||
    SKILL_NAMES[entry.cloud?.display_name?.replace(/[_ ]+/g, "-") ?? ""] ||
    SKILL_NAMES[entry.name] ||
    entry.cloud?.aliases?.map((alias) => SKILL_NAMES[alias]).find(Boolean) ||
    entry.cloud?.display_name ||
    entry.name.replace(/[-_]+/g, " ");
  // Group discovery entries by the original skill name, never by translated
  // titles or broad capabilities. Keep each install identity and provenance.
  const groups = useMemo(() => {
    const byName = new Map<string, SkillEntry[]>();
    for (const entry of entries) {
      const name = entry.cloud?.external
        ? entry.cloud.original_name || entry.cloud.display_name || entry.name
        : entry.local?.name || entry.name;
      const key = name.trim().toLowerCase().replace(/[ _]+/g, "-");
      const variants = byName.get(key) ?? [];
      variants.push(entry);
      byName.set(key, variants);
    }
    return [...byName].map(([key, variants]) => ({ key, variants }));
  }, [entries]);
  const detailVariants = detail
    ? (groups.find((group) =>
        group.variants.some((entry) => entry.key === detail.key),
      )?.variants ?? [detail])
    : [];
  const availableCategories = new Set(entries.flatMap(entryCategories));
  const tags = SKILL_CATEGORIES.filter((category) =>
    availableCategories.has(category),
  );
  const query = searchQuery.trim().toLowerCase();
  const matchesFilters = (entry: SkillEntry) =>
    (!sourceFilter ||
      (sourceFilter === "echo"
        ? !entry.cloud?.external && Boolean(entry.cloud)
        : sourceFilter === "local"
          ? isInstalled(entry)
          : sourceFilter === "skills.sh"
            ? Boolean(
                entry.cloud?.search_match === searchQuery.trim() && query,
              ) || entry.source === "skills.sh"
            : entry.source === sourceFilter)) &&
    (!installedOnly || isInstalled(entry)) &&
    (!roleFilter ||
      (skillUsers !== undefined &&
        isInstalled(entry) &&
        (roleFilter === "linked"
          ? usersFor(entry).length > 0
          : usersFor(entry).length === 0))) &&
    (!tagFilter || entryCategories(entry).includes(tagFilter)) &&
    (!query ||
      entry.cloud?.search_match === searchQuery.trim() ||
      [
        entry.name,
        displayName(entry),
        entry.description,
        entry.author,
        entry.source,
        authorLabel(entry.author, entry.source),
        sourceLabel(entry.source),
        ...usersFor(entry).map((user) => user.name),
        ...(entry.cloud?.tags ?? []),
        ...entryCategories(entry),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(query));
  const filteredEntries = groups.flatMap((group) => {
    const matches = group.variants.filter(matchesFilters);
    if (!matches.length) return [];
    return [{ ...group, entry: matches.find(isInstalled) ?? matches[0]! }];
  });

  const useSkill = (entry: SkillEntry) => {
    const id =
      entry.local?.name ||
      [entry.name, ...(entry.cloud?.aliases ?? [])].find((name) =>
        installedNames.has(normalizeSkillName(name)),
      ) ||
      entry.name;
    const prompt = /^[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(id)
      ? serializeComposerDraft({ refs: [{ type: "skill", id }], body: "" })
      : `请使用「${displayName(entry)}」技能，`;
    navigate(`/workspace/realtime/new?${new URLSearchParams({ prompt })}`);
  };

  const stateFor = (entry: SkillEntry) => skillStates[runtimeId(entry)];
  const manage = async (
    entry: SkillEntry,
    action: "enable" | "disable" | "uninstall",
  ) => {
    setManaging(true);
    try {
      await manageCloudSkill(runtimeId(entry), action);
      setConfirmRemoval(null);
      if (action === "uninstall") {
        setProgress((current) => {
          const next = { ...current };
          delete next[normalizeSkillName(entry.name)];
          return next;
        });
        setDetail(null);
      }
      await load();
      toast.success(
        `技能「${displayName(entry)}」已${action === "uninstall" ? "卸载" : action === "disable" ? "停用" : "启用"}`,
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : String(error));
    } finally {
      setManaging(false);
    }
  };

  const clearFilters = () => {
    setInstalledOnly(false);
    setTagFilter("");
    setSourceFilter("");
    setRoleFilter("");
    onClearSearch?.();
  };

  const install = async (skill: CloudSkillItem) => {
    const key = normalizeSkillName(skill.name);
    setProgress((current) => ({
      ...current,
      [key]: { phase: "resolving", progress: 2, message: "正在启动安装" },
    }));
    try {
      await streamInstallCloudSkill(skill.name, (event) => {
        setProgress((current) => ({ ...current, [key]: event }));
      });
      setInstalledNames((current) => new Set(current).add(key));
      const status = await fetchCloudInstalled().catch(() => null);
      if (status?.skill_states) setSkillStates(status.skill_states);
      if (status?.skill_users) setSkillUsers(status.skill_users);
      toast.success(`技能「${skill.name}」已安装`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setProgress((current) => ({
        ...current,
        [key]: { phase: "failed", progress: 100, message },
      }));
      toast.error(message);
    }
  };

  return (
    <div className="space-y-3">
      <div className="sticky top-0 z-10 space-y-3 border-b border-border/60 bg-background py-3">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="mr-auto text-sm font-medium">技能目录</h3>
          <span className="text-xs text-muted-foreground">
            已安装{" "}
            {groups.filter((group) => group.variants.some(isInstalled)).length}{" "}
            · 当前目录 {groups.length}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            aria-label="目录说明"
            onClick={() => setInfoOpen(true)}
          >
            <InfoIcon className="size-4" />
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1" role="group" aria-label="技能安装状态">
            {[false, true].map((only) => (
              <Button
                key={String(only)}
                size="sm"
                variant={installedOnly === only ? "secondary" : "ghost"}
                aria-pressed={installedOnly === only}
                onClick={() => setInstalledOnly(only)}
                className="h-8 text-xs"
              >
                {only ? "已安装" : "全部"}
              </Button>
            ))}
          </div>
          <select
            aria-label="技能源"
            value={sourceFilter}
            onChange={(event) => {
              setSourceFilter(event.target.value);
              setTagFilter("");
            }}
            className="ml-auto h-8 max-w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {[
              ["", "全部来源"],
              ["echo", "echo"],
              ["openai", "OpenAI"],
              ["anthropic", "Anthropic"],
              ["vercel", "Vercel"],
              ["minimax-design", "MiniMax Design · 官方精选"],
              ["skills.sh", "Skills.sh"],
              ["local", "本地"],
            ].map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
          <select
            aria-label="角色关联"
            value={roleFilter}
            disabled={skillUsers === undefined}
            onChange={(event) => setRoleFilter(event.target.value)}
            className="h-8 max-w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="">全部关联状态</option>
            <option value="linked">已关联角色</option>
            <option value="unlinked">未关联角色</option>
          </select>
          <span className="text-xs text-muted-foreground" role="status">
            {filteredEntries.length} 个结果
          </span>
          {externalLoading && (
            <Loader2Icon
              className="size-3.5 animate-spin text-muted-foreground"
              aria-label="正在加载远程技能源"
            />
          )}
        </div>
        {tags.length > 0 && (
          <div
            className="flex flex-wrap items-center gap-1"
            role="group"
            aria-label="技能分类"
          >
            {["", ...tags].map((tag) => (
              <Button
                key={tag || "all-categories"}
                size="sm"
                variant={tagFilter === tag ? "secondary" : "ghost"}
                aria-pressed={tagFilter === tag}
                onClick={() => setTagFilter(tag)}
                className="h-8 px-2.5 text-xs shadow-none"
              >
                {tag || "全部分类"}
              </Button>
            ))}
          </div>
        )}
      </div>
      {sourceFilter === "skills.sh" && query.length < 2 && (
        <p className="text-xs text-muted-foreground" role="status">
          在上方输入至少 2 个字，搜索 Skills.sh 社区技能。
        </p>
      )}
      {sourceStates?.some((item) =>
        ["unavailable", "stale"].includes(item.state),
      ) && (
        <p className="text-xs text-muted-foreground" role="status">
          {sourceStates
            .filter((item) => ["unavailable", "stale"].includes(item.state))
            .map(
              (item) =>
                `${sourceLabel(item.source)}：${item.state === "stale" ? "使用缓存" : "暂不可用"}`,
            )
            .join("；")}
        </p>
      )}

      {cloudError ? (
        <div className="rounded-lg border border-warning/25 bg-warning/5 px-3 py-2 text-xs text-muted-foreground">
          云端目录同步失败，仍可查看本地与其他来源的技能：{cloudError}
        </div>
      ) : null}

      {loading && entries.length === 0 ? (
        <div className="grid gap-x-6 sm:grid-cols-2">
          {Array.from({ length: 10 }).map((_, index) => (
            <Skeleton key={index} className="my-2 h-16 rounded-md" />
          ))}
        </div>
      ) : filteredEntries.length === 0 ? (
        <div className="py-12 text-center text-sm text-muted-foreground">
          <SearchIcon className="mx-auto mb-3 size-6" aria-hidden="true" />
          <p>
            {externalLoading
              ? "正在查找技能…"
              : installedOnly && !query && !tagFilter && !sourceFilter
                ? "还没有已安装的技能。"
                : "没有匹配的技能。"}
          </p>
          <p className="mt-2 text-xs">
            可调整关键词或清除筛选；输入至少 2 个字会同时搜索远程市场。
          </p>
          <Button
            variant="ghost"
            size="sm"
            className="mt-3"
            onClick={clearFilters}
          >
            查看全部技能
          </Button>
        </div>
      ) : (
        <>
          <div
            className="grid gap-x-6 sm:grid-cols-2"
            role="list"
            aria-label="技能列表"
          >
            {filteredEntries
              .slice(0, visibleCount)
              .map(({ key, variants, entry }) => {
                const installed = isInstalled(entry);
                const state = progress[normalizeSkillName(entry.name)];
                const installing =
                  state && !["completed", "failed"].includes(state.phase);
                return (
                  <div
                    key={key}
                    role="listitem"
                    className="min-w-0 border-b border-border/50 px-1 py-3 transition-colors hover:bg-muted/30"
                  >
                    <div className="flex items-center gap-2.5">
                      <SkillIcon
                        name={entry.cloud?.display_name || entry.name}
                        tags={entry.cloud?.tags}
                      />
                      <button
                        type="button"
                        onClick={() => setDetail(entry)}
                        aria-label={`查看 ${entry.name} 详情`}
                        className="min-w-0 flex-1 cursor-pointer rounded-md text-left outline-none hover:text-primary focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <span className="flex items-center gap-1.5">
                          <span className="truncate text-sm font-medium">
                            {displayName(entry)}
                          </span>
                          {installed && (
                            <CheckIcon
                              className="size-3.5 shrink-0 text-success"
                              aria-label="已安装"
                            />
                          )}
                        </span>
                        <span className="mt-0.5 block truncate text-xs leading-5 text-muted-foreground">
                          {entry.description}
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {sourceLabel(entry.source)}
                          {variants.length > 1
                            ? ` · ${variants.length} 个来源版本`
                            : ""}
                        </span>
                      </button>
                      {entry.cloud?.catalog_only ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-8 shrink-0 px-2 text-xs"
                          asChild
                        >
                          <a
                            href={entry.cloud.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            查看原平台
                          </a>
                        </Button>
                      ) : installed ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-8 shrink-0 px-2.5 text-xs"
                          disabled={managing}
                          onClick={() =>
                            stateFor(entry)?.enabled === false
                              ? void manage(entry, "enable")
                              : useSkill(entry)
                          }
                          aria-label={`${stateFor(entry)?.enabled === false ? "启用" : "使用"} ${displayName(entry)}`}
                        >
                          {stateFor(entry)?.enabled === false
                            ? "已停用 · 启用"
                            : "使用"}
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-8 shrink-0 gap-1 px-2.5 text-xs"
                          disabled={Boolean(installing)}
                          onClick={() =>
                            variants.length > 1
                              ? setDetail(entry)
                              : entry.cloud && void install(entry.cloud)
                          }
                        >
                          {installing ? (
                            <Loader2Icon className="size-3.5 animate-spin" />
                          ) : (
                            <CloudIcon className="size-3.5" />
                          )}
                          {installing
                            ? `${state.progress}%`
                            : state?.phase === "failed"
                              ? "重试"
                              : variants.length > 1
                                ? "选择来源"
                                : "安装"}
                        </Button>
                      )}
                      {installed &&
                        (stateFor(entry)?.can_toggle ||
                          stateFor(entry)?.can_uninstall) && (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-8 shrink-0 px-2 text-xs text-muted-foreground"
                            aria-label={`管理 ${displayName(entry)}`}
                            onClick={() => {
                              setConfirmRemoval(null);
                              setDetail(entry);
                            }}
                          >
                            管理
                          </Button>
                        )}
                    </div>
                    {installed && (
                      <div className="mt-1 flex min-w-0 justify-end pl-[50px]">
                        {skillUsers === undefined ? (
                          <span className="text-xs text-muted-foreground">
                            角色关联未加载
                          </span>
                        ) : usersFor(entry).length ? (
                          <button
                            type="button"
                            className="flex max-w-full items-center rounded-md p-0.5 text-xs text-muted-foreground outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
                            aria-label={`查看 ${displayName(entry)} 的使用角色`}
                            title={usersFor(entry)
                              .map((user) => user.name)
                              .join("、")}
                            onClick={() => {
                              setConfirmRemoval(null);
                              setDetail(entry);
                            }}
                          >
                            <span className="flex -space-x-1.5">
                              {usersFor(entry)
                                .slice(0, 4)
                                .map((user) => (
                                  <span
                                    key={user.id}
                                    title={user.name}
                                    className="relative rounded-md ring-2 ring-background hover:z-10"
                                  >
                                    <AgentAvatar
                                      agent={{
                                        name: user.id,
                                        display_name: user.name,
                                        avatar_url: user.avatar_url,
                                        icon: user.icon,
                                      }}
                                      className="size-6"
                                    />
                                  </span>
                                ))}
                            </span>
                            {usersFor(entry).length > 4 && (
                              <span className="ml-1.5 tabular-nums">
                                +{usersFor(entry).length - 4}
                              </span>
                            )}
                          </button>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            未关联角色
                          </span>
                        )}
                      </div>
                    )}
                    {state && !installed && (
                      <div className="mt-2 pl-[50px]" role="status">
                        {state.phase !== "failed" && (
                          <div className="h-1 overflow-hidden rounded-full bg-muted">
                            <div
                              className="h-full bg-primary transition-[width]"
                              style={{ width: `${state.progress}%` }}
                            />
                          </div>
                        )}
                        <p className="mt-1 break-words text-xs text-muted-foreground">
                          {state.message}
                        </p>
                      </div>
                    )}
                  </div>
                );
              })}
          </div>
          <div className="flex items-center justify-center gap-3 py-4">
            <span className="text-xs text-muted-foreground" role="status">
              已显示 {Math.min(visibleCount, filteredEntries.length)} /{" "}
              {filteredEntries.length}
            </span>
            {visibleCount < filteredEntries.length && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setVisibleCount((count) => count + PAGE_SIZE)}
              >
                加载更多
              </Button>
            )}
          </div>
        </>
      )}
      <Dialog open={infoOpen} onOpenChange={setInfoOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>目录说明</DialogTitle>
            <DialogDescription>
              聚合当前目录与远程搜索结果，数量不代表全网技能总量。
            </DialogDescription>
          </DialogHeader>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <dt className="text-muted-foreground">echo 目录</dt>
            <dd>{cloudSkills.length}</dd>
            <dt className="text-muted-foreground">远程已载入</dt>
            <dd>{externalSkills.length}</dd>
            <dt className="text-muted-foreground">本地技能</dt>
            <dd>{localSkills.length}</dd>
          </dl>
          <p className="text-sm leading-6 text-muted-foreground">
            同名技能合并为一个入口，各来源的内容、安装状态独立保留，可在详情切换。搜索会同时查询已接入的远程来源；Skills.sh
            需要至少 2 个字，每次最多返回 30 条。MiniMax Design
            支持安装官网精选技能包；图像、视频和音频生成需配置对应工具。来源暂不可用时，仍可浏览其他目录。
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setInfoOpen(false)}>
              知道了
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={Boolean(detail)}
        onOpenChange={(open) => !open && setDetail(null)}
      >
        <DialogContent className="flex flex-col overflow-y-clip">
          <DialogHeader className="shrink-0 pr-8 text-left">
            <DialogTitle className="flex items-center gap-3 break-words">
              {detail && (
                <>
                  <SkillIcon name={detail.name} tags={detail.cloud?.tags} />
                  <span>{displayName(detail)}</span>
                </>
              )}
            </DialogTitle>
            <DialogDescription>查看用途、来源与安装状态</DialogDescription>
          </DialogHeader>
          {detail && (
            <div className="min-h-0 overflow-y-auto overscroll-contain space-y-4 text-sm">
              {detailVariants.length > 1 && (
                <div className="space-y-2">
                  <label
                    htmlFor="skill-source-version"
                    className="block text-xs text-muted-foreground"
                  >
                    来源版本
                  </label>
                  <select
                    id="skill-source-version"
                    value={detail.key}
                    onChange={(event) =>
                      setDetail(
                        detailVariants.find(
                          (entry) => entry.key === event.target.value,
                        ) ?? detail,
                      )
                    }
                    className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {detailVariants.map((entry) => (
                      <option key={entry.key} value={entry.key}>
                        {sourceLabel(entry.source)}
                        {entry.cloud?.repository
                          ? ` · ${entry.cloud.repository}`
                          : ""}{" "}
                        · {entry.version || "版本未提供"} ·{" "}
                        {isInstalled(entry) ? "已安装" : "未安装"}
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-muted-foreground">
                    同名技能的内容与依赖可能不同，安装和使用针对当前选中的来源。
                  </p>
                </div>
              )}
              <p className="whitespace-pre-wrap break-words leading-6">
                {detail.description}
              </p>
              {isInstalled(detail) && (
                <section className="space-y-2" aria-label="角色使用者">
                  <h4 className="text-sm font-medium">
                    角色使用者
                    {skillUsers !== undefined
                      ? ` · ${usersFor(detail).length}`
                      : ""}
                  </h4>
                  <p className="text-xs text-muted-foreground">
                    按角色配置中的技能登记统计，不代表实际调用次数。
                  </p>
                  {skillUsers === undefined ? (
                    <p className="text-sm text-muted-foreground">
                      角色关联未加载
                    </p>
                  ) : usersFor(detail).length ? (
                    <div className="flex flex-wrap gap-1.5">
                      {usersFor(detail).map((user) => (
                        <Badge
                          key={user.id}
                          variant="secondary"
                          title={user.id}
                        >
                          <AgentAvatar
                            agent={{
                              name: user.id,
                              display_name: user.name,
                              avatar_url: user.avatar_url,
                              icon: user.icon,
                            }}
                            className="mr-1 size-5"
                          />
                          {user.name}
                        </Badge>
                      ))}
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">未关联角色</p>
                  )}
                </section>
              )}
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 rounded-lg bg-muted/50 p-4">
                <dt className="text-muted-foreground">标识</dt>
                <dd className="break-words">{detail.name}</dd>
                <dt className="text-muted-foreground">来源</dt>
                <dd className="break-words">{sourceLabel(detail.source)}</dd>
                <dt className="text-muted-foreground">作者</dt>
                <dd className="break-words">
                  {authorLabel(detail.author, detail.source)}
                </dd>
                <dt className="text-muted-foreground">版本</dt>
                <dd>{detail.version || "未提供"}</dd>
                {detail.cloud?.source_url && (
                  <>
                    <dt className="text-muted-foreground">
                      {detail.cloud.source === "minimax-design" ||
                      detail.cloud.catalog_only
                        ? "原平台"
                        : "原仓库"}
                    </dt>
                    <dd className="break-all">
                      <a
                        href={detail.cloud.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="underline"
                      >
                        {detail.cloud.repository || "查看来源"}
                      </a>
                    </dd>
                  </>
                )}
                {detail.cloud?.license && (
                  <>
                    <dt className="text-muted-foreground">许可</dt>
                    <dd>{detail.cloud.license}</dd>
                  </>
                )}
                {detail.cloud?.compatibility && (
                  <>
                    <dt className="text-muted-foreground">兼容与依赖</dt>
                    <dd>{detail.cloud.compatibility}</dd>
                  </>
                )}
                <dt className="text-muted-foreground">状态</dt>
                <dd>
                  {detail.cloud?.catalog_only
                    ? "在原平台使用"
                    : isInstalled(detail)
                      ? "已安装"
                      : "未安装"}
                </dd>
              </dl>
              {!!detail.cloud?.tags?.length && (
                <div className="flex flex-wrap gap-2">
                  {detail.cloud.tags.map((tag) => (
                    <Badge key={tag} variant="secondary">
                      {tag}
                    </Badge>
                  ))}
                </div>
              )}
              <p className="text-xs leading-5 text-muted-foreground">
                {stateFor(detail)?.enabled === false
                  ? "该技能已停用，恢复启用后可调用。"
                  : "当前目录未提供技能正文、完整权限及依赖清单。"}
              </p>
              {confirmRemoval === runtimeId(detail) && (
                <p className="text-sm text-destructive">
                  卸载会删除该下载版本的技能文件及本地修改。之后可从目录重新安装。
                </p>
              )}
            </div>
          )}
          {detail && (
            <DialogFooter className="shrink-0 border-t pt-3">
              <Button variant="outline" onClick={() => setDetail(null)}>
                关闭
              </Button>
              {detail.cloud?.catalog_only && (
                <Button asChild>
                  <a
                    href={detail.cloud.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    查看原平台
                  </a>
                </Button>
              )}
              {isInstalled(detail) && stateFor(detail)?.can_toggle && (
                <Button
                  variant="outline"
                  disabled={managing}
                  onClick={() =>
                    void manage(
                      detail,
                      stateFor(detail)?.enabled === false
                        ? "enable"
                        : "disable",
                    )
                  }
                >
                  {stateFor(detail)?.enabled === false
                    ? "恢复启用"
                    : "停用技能"}
                </Button>
              )}
              {isInstalled(detail) && stateFor(detail)?.can_uninstall && (
                <Button
                  variant="destructive"
                  disabled={managing}
                  onClick={() =>
                    confirmRemoval === runtimeId(detail)
                      ? void manage(detail, "uninstall")
                      : setConfirmRemoval(runtimeId(detail))
                  }
                >
                  {confirmRemoval === runtimeId(detail)
                    ? "确认卸载"
                    : "卸载技能"}
                </Button>
              )}
              {!detail.cloud?.catalog_only &&
                isInstalled(detail) &&
                stateFor(detail)?.enabled !== false && (
                  <Button onClick={() => useSkill(detail)}>使用技能</Button>
                )}
              {!isInstalled(detail) &&
                detail.cloud &&
                !detail.cloud.catalog_only && (
                  <Button
                    disabled={Boolean(
                      progress[normalizeSkillName(detail.name)] &&
                      !["completed", "failed"].includes(
                        progress[normalizeSkillName(detail.name)]!.phase,
                      ),
                    )}
                    onClick={() => detail.cloud && void install(detail.cloud)}
                  >
                    安装技能
                  </Button>
                )}
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
