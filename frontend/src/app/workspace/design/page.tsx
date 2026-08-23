"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArchiveIcon,
  ArrowLeftIcon,
  ArrowRightIcon,
  BookOpenIcon,
  BotIcon,
  CheckIcon,
  ChevronDownIcon,
  CircleHelpIcon,
  CirclePlayIcon,
  FolderIcon,
  Grid2X2Icon,
  HandIcon,
  ImageIcon,
  LayoutPanelLeftIcon,
  ListIcon,
  Loader2Icon,
  Maximize2Icon,
  MessageSquareIcon,
  MinusIcon,
  MousePointer2Icon,
  PanelLeftCloseIcon,
  PanelRightIcon,
  PlusIcon,
  PuzzleIcon,
  Redo2Icon,
  SearchIcon,
  SendIcon,
  Settings2Icon,
  SparklesIcon,
  Trash2Icon,
  WandSparklesIcon,
  WorkflowIcon,
  XIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useAgents } from "@/core/agents/hooks";
import type { Agent } from "@/core/agents/types";
import { authHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useHubPlugins, usePlugins } from "@/core/plugins/hooks";
import {
  useEnableMarketSkill,
  useEnableSkill,
  useSkills,
} from "@/core/skills/hooks";
import type { SkillInfo } from "@/core/skills/types";
import { cn } from "@/lib/utils";
import { useAuth } from "@/providers/AuthProvider";

import {
  appendDesignNode,
  DESIGN_CANVAS_STORAGE_KEY,
  designCanvasRunPrompt,
  mergeDesignCanvases,
  parseDesignCanvas,
  tidyDesignCanvas,
  type DesignCanvasDocument,
  type DesignCanvasNode,
  type DesignNodeKind,
} from "./canvas-model";
import {
  COMFY_WORKFLOWS,
  CREATIVE_SKILL_COLLECTION,
  NATIVE_NODE_TEMPLATES,
  type DesignSection,
  type WorkspaceLayout,
} from "./design-catalog";
import { DirectorStage } from "./director-stage";
import { ComfyWorkflowEditor } from "./comfy-workflow-editor";
import { PluginNodeFrame } from "./plugin-node-frame";

type ToolMode = "select" | "hand";
type AddTab = "nodes" | "agents" | "skills" | "plugins";
type EmbeddedSurface = "director" | "editor" | "comfyui" | null;

const CREATIVE_SKILL_COVERS = [
  "/community/game-guide(1).jpg",
  "/community/weekly-highlights.jpg",
  "/community/memory-video(1).jpg",
  "/community/daily-album.jpg",
  "/community/study-paper(1).jpg",
  "/community/travel-plan(1).jpg",
  "/community/food-delivery(1).jpg",
  "/community/web-summary.jpg",
  "/community/mock-interview.jpg",
  "/community/gacha.jpg",
  "/community/smart-home.jpg",
  "/community/language-coach.jpg",
  "/community/voice-reply.jpg",
  "/community/weekend.jpg",
  "/community/meeting-notes.jpg",
  "/community/price-watch(1).jpg",
] as const;

const COMFY_WORKFLOW_COVERS = [
  "/images/browser-wallpapers/aurora-lab.png",
  "/images/browser-wallpapers/sky-studio.png",
  "/images/browser-wallpapers/forest-calm.png",
  "/images/browser-wallpapers/ember-dusk.png",
  "/images/browser-wallpapers/mist-glass.png",
  "/images/browser-wallpapers/focus-nocturne.png",
  "/images/browser-wallpapers/clear-productivity.png",
] as const;
type CanvasSyncState =
  | "local"
  | "loading"
  | "saving"
  | "saved"
  | "conflict"
  | "error";
type CanvasServerPayload = {
  revision?: number;
  document?: Record<string, unknown> | null;
  updated_at?: string | null;
};
type PendingCanvasConflict = {
  revision: number;
  remote: DesignCanvasDocument;
  merged: DesignCanvasDocument;
  conflicts: string[];
};
type CanvasPresenceMember = {
  id: string;
  client_id: string;
  display_name: string;
  x: number | null;
  y: number | null;
  section: DesignSection;
  color: string;
  updated_at: string;
};
type ProjectArtifact = {
  id: string;
  name: string;
  category?: string;
  kind?: string;
  path?: string;
  url?: string;
  summary?: string;
  task_id?: string;
  milestone_id?: string;
};
type DesignLibraryAsset = ProjectArtifact & {
  category: "角色" | "场景" | "风格包" | "道具" | "自定义";
  description?: string;
  tags?: string[];
  filename?: string;
  size?: number;
  created_at?: string;
};

const NODE_WIDTH = 236;
const NODE_HEIGHT = 122;
const MIN_ZOOM = 0.35;
const MAX_ZOOM = 1.8;

const KIND_STYLE: Record<
  DesignNodeKind,
  { label: string; tint: string; accent: string }
> = {
  brief: { label: "需求", tint: "bg-amber-50", accent: "bg-amber-400" },
  agent: { label: "角色", tint: "bg-violet-50", accent: "bg-violet-500" },
  skill: { label: "Skill", tint: "bg-blue-50", accent: "bg-blue-500" },
  plugin: { label: "插件", tint: "bg-emerald-50", accent: "bg-emerald-500" },
  text: { label: "文本", tint: "bg-zinc-50", accent: "bg-zinc-500" },
  table: { label: "表格", tint: "bg-cyan-50", accent: "bg-cyan-500" },
  image: { label: "图片", tint: "bg-pink-50", accent: "bg-pink-500" },
  video: { label: "视频", tint: "bg-indigo-50", accent: "bg-indigo-500" },
  audio: { label: "音频", tint: "bg-orange-50", accent: "bg-orange-500" },
  director: { label: "3D", tint: "bg-lime-50", accent: "bg-lime-500" },
  editor: { label: "剪辑", tint: "bg-rose-50", accent: "bg-rose-500" },
  comfyui: { label: "ComfyUI", tint: "bg-sky-50", accent: "bg-sky-500" },
  output: { label: "交付", tint: "bg-purple-50", accent: "bg-purple-500" },
};

function nextNodeId(kind: DesignNodeKind): string {
  return `${kind}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}

function artifactNodeKind(artifact: ProjectArtifact): DesignNodeKind {
  const marker =
    `${artifact.kind ?? ""} ${artifact.path ?? ""} ${artifact.url ?? ""}`.toLowerCase();
  if (/\.(mp4|mov|webm|mkv)\b|\bvideo\b/.test(marker)) return "video";
  if (/\.(mp3|wav|m4a|aac|flac)\b|\baudio\b/.test(marker)) return "audio";
  if (/\.(png|jpe?g|webp|gif|svg)\b|\bimage\b/.test(marker)) return "image";
  if (/\.(csv|xlsx?|ods)\b|\btable\b/.test(marker)) return "table";
  return "output";
}

function EdgeLayer({ document }: { document: DesignCanvasDocument }) {
  if (document.mode !== "workflow") return null;
  return (
    <svg className="pointer-events-none absolute inset-0 size-full overflow-visible">
      {document.edges.map((edge) => {
        const source = document.nodes.find((node) => node.id === edge.source);
        const target = document.nodes.find((node) => node.id === edge.target);
        if (!source || !target) return null;
        const sx = source.x + (source.width ?? NODE_WIDTH);
        const sy = source.y + (source.height ?? NODE_HEIGHT) / 2;
        const tx = target.x;
        const ty = target.y + (target.height ?? NODE_HEIGHT) / 2;
        const bend = Math.max(64, Math.abs(tx - sx) * 0.45);
        return (
          <path
            key={edge.id}
            d={`M ${sx} ${sy} C ${sx + bend} ${sy}, ${tx - bend} ${ty}, ${tx} ${ty}`}
            fill="none"
            className="stroke-[#c4c4c4] dark:stroke-[#525252]"
            strokeWidth="1.5"
          />
        );
      })}
    </svg>
  );
}

function CanvasNode({
  node,
  selected,
  zoom,
  mode,
  onSelect,
  onMove,
}: {
  node: DesignCanvasNode;
  selected: boolean;
  zoom: number;
  mode: ToolMode;
  onSelect: () => void;
  onMove: (x: number, y: number) => void;
}) {
  const style = KIND_STYLE[node.kind] ?? KIND_STYLE.text;
  const assetPreviewUrl = node.asset?.url
    ? node.asset.url.startsWith("/")
      ? `${getBackendBaseURL()}${node.asset.url}`
      : node.asset.url
    : null;
  const startDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (mode !== "select") return;
    event.stopPropagation();
    onSelect();
    const startX = event.clientX;
    const startY = event.clientY;
    const originX = node.x;
    const originY = node.y;
    const move = (next: PointerEvent) =>
      onMove(
        originX + (next.clientX - startX) / zoom,
        originY + (next.clientY - startY) / zoom,
      );
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end, { once: true });
  };

  return (
    <div
      data-testid={`design-node-${node.id}`}
      onPointerDown={startDrag}
      className={cn(
        "pointer-events-auto absolute overflow-hidden rounded-[16px] border border-[#e3e3e3] bg-white shadow-[0_2px_5px_rgba(0,0,0,.08)] transition dark:border-[#4a4a4a] dark:bg-[#1a1a1a] dark:shadow-[0_2px_5px_rgba(0,0,0,.15)]",
        mode === "select" && "cursor-grab active:cursor-grabbing",
        selected
          ? "border-foreground/45 ring-[3px] ring-foreground/8"
          : "hover:border-foreground/25",
      )}
      style={{
        width: node.width ?? NODE_WIDTH,
        minHeight: NODE_HEIGHT,
        height: node.height,
        transform: `translate(${node.x}px, ${node.y}px)`,
      }}
    >
      <div className={cn("h-1", style.accent)} />
      <div className="p-3.5">
        <div className="flex items-center gap-2.5">
          <span
            className={cn(
              "grid size-8 place-items-center rounded-lg",
              style.tint,
            )}
          >
            <span className="text-xs font-semibold text-zinc-700">
              {style.label.slice(0, 2)}
            </span>
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13px] font-semibold">
              {node.title}
            </div>
            <div className="mt-0.5 text-[10px] text-muted-foreground">
              {style.label}
            </div>
          </div>
          <span className="size-1.5 rounded-full bg-emerald-500" />
        </div>
        {node.kind === "image" && assetPreviewUrl ? (
          <img
            src={assetPreviewUrl}
            alt=""
            className="mt-2.5 h-24 w-full rounded-[10px] border border-black/[0.06] object-cover"
          />
        ) : null}
        <p className="mt-2.5 line-clamp-2 text-[11px] leading-[17px] text-muted-foreground">
          {node.description}
        </p>
      </div>
      <span
        className="absolute -left-1 size-2 rounded-full bg-foreground/25"
        style={{ top: (node.height ?? NODE_HEIGHT) / 2 - 4 }}
      />
      <span
        className="absolute -right-1 size-2 rounded-full bg-foreground/50"
        style={{ top: (node.height ?? NODE_HEIGHT) / 2 - 4 }}
      />
    </div>
  );
}

function ChatPanel({
  chatUrl,
  onRun,
  onNew,
  onClose,
}: {
  chatUrl: string | null;
  onRun: (prompt?: string) => void;
  onNew: () => void;
  onClose: () => void;
}) {
  const [prompt, setPrompt] = useState("");
  if (chatUrl) {
    return (
      <aside className="h-full w-[320px] min-w-[292px] shrink-0 border-l border-border-subtle bg-background">
        <iframe
          title="创作协作对话"
          src={chatUrl}
          className="size-full border-0 bg-background"
          allow="clipboard-read; clipboard-write"
        />
      </aside>
    );
  }
  return (
    <aside className="flex h-full w-[304px] min-w-[280px] shrink-0 flex-col bg-background">
      <div className="flex h-12 items-center gap-2 border-b border-border-subtle px-3.5">
        <div className="min-w-0 flex-1 truncate text-[13px] font-semibold">
          创作协作
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label="新建对话"
          onClick={onNew}
        >
          <PlusIcon className="size-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          aria-label="收起对话"
          onClick={onClose}
        >
          <PanelRightIcon className="size-4" />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 text-[13px] leading-6">
        <div className="flex gap-2.5">
          <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-violet-100 text-violet-600">
            <SparklesIcon className="size-3.5" />
          </span>
          <div>
            <p className="font-medium">把想法说给我，产物会直接落在画布上。</p>
            <p className="mt-2 text-muted-foreground">
              我会先拆解任务，再调用画布里绑定的角色、Skill
              和插件。工作流模式按连线执行，自由画布模式由我自主编排。
            </p>
          </div>
        </div>
      </div>
      <div className="p-3">
        <div className="rounded-[16px] border border-border-default bg-background p-2 shadow-[0_12px_32px_-24px_rgba(0,0,0,.45)]">
          <Textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="描述你想创作的内容…"
            className="min-h-20 resize-none border-0 bg-transparent px-2 py-1 text-xs shadow-none focus-visible:ring-0"
          />
          <div className="flex items-center gap-1 pt-1">
            <Button variant="ghost" size="icon" className="size-8 rounded-full">
              <PlusIcon className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 gap-1.5 rounded-lg text-[11px]"
            >
              <PuzzleIcon className="size-3.5" /> Skill
            </Button>
            <span className="flex-1" />
            <Button
              size="icon"
              className="size-8 rounded-full"
              onClick={() => onRun(prompt)}
            >
              <SendIcon className="size-3.5" />
            </Button>
          </div>
        </div>
        <p className="pt-1.5 text-center text-[9px] text-muted-foreground">
          内容会自动保存到当前项目
        </p>
      </div>
    </aside>
  );
}

function AddNodePopover({
  tab,
  query,
  agents,
  skills,
  plugins,
  loading,
  onTab,
  onQuery,
  onAdd,
  onClose,
}: {
  tab: AddTab;
  query: string;
  agents: Array<{
    name: string;
    display_name?: string | null;
    description?: string | null;
  }>;
  skills: Array<{ name: string; description: string; enabled: boolean }>;
  plugins: Array<{
    id: string;
    name: string;
    description: string;
    enabled: boolean;
  }>;
  loading: boolean;
  onTab: (tab: AddTab) => void;
  onQuery: (value: string) => void;
  onAdd: (
    kind: DesignNodeKind,
    title: string,
    description: string,
    binding?: DesignCanvasNode["binding"],
  ) => void;
  onClose: () => void;
}) {
  const normalized = query.trim().toLowerCase();
  const items = useMemo(() => {
    if (tab === "nodes")
      return NATIVE_NODE_TEMPLATES.map((item) => ({ ...item }));
    if (tab === "agents")
      return agents
        .filter((item) =>
          `${item.display_name ?? item.name} ${item.description ?? ""}`
            .toLowerCase()
            .includes(normalized),
        )
        .slice(0, 16)
        .map((item) => ({
          kind: "agent" as const,
          title: item.display_name ?? item.name,
          description: item.description || "Octopus AI 角色",
          icon: BotIcon,
          binding: { type: "agent" as const, id: item.name },
        }));
    if (tab === "skills")
      return skills
        .filter(
          (item) =>
            item.enabled &&
            `${item.name} ${item.description}`
              .toLowerCase()
              .includes(normalized),
        )
        .slice(0, 16)
        .map((item) => ({
          kind: "skill" as const,
          title: item.name,
          description: item.description || "Octopus Skill",
          icon: SparklesIcon,
          binding: { type: "skill" as const, id: item.name },
        }));
    return plugins
      .filter(
        (item) =>
          item.enabled &&
          `${item.name} ${item.description}`.toLowerCase().includes(normalized),
      )
      .slice(0, 16)
      .map((item) => ({
        kind: "plugin" as const,
        title: item.name,
        description: item.description || "Octopus 插件",
        icon: PuzzleIcon,
        binding: { type: "plugin" as const, id: item.id },
      }));
  }, [agents, normalized, plugins, skills, tab]);

  return (
    <div className="absolute bottom-[72px] left-1/2 z-40 w-[330px] -translate-x-1/2 overflow-hidden rounded-[16px] border border-[#e6e6e6] bg-white shadow-[0_8px_32px_rgba(0,0,0,.08),0_2px_8px_rgba(0,0,0,.04)] dark:border-[#454545] dark:bg-[#1a1a1a] dark:shadow-[0_8px_32px_rgba(0,0,0,.15),0_2px_8px_rgba(0,0,0,.1)]">
      <div className="flex items-center gap-2 px-3 pb-2 pt-3">
        <div className="flex-1 text-[13px] font-semibold">添加节点</div>
        <button
          type="button"
          onClick={onClose}
          className="grid size-7 place-items-center rounded-lg hover:bg-muted"
        >
          <XIcon className="size-3.5" />
        </button>
      </div>
      <div className="mx-3 flex rounded-lg bg-muted/70 p-1 text-[10px]">
        {(["nodes", "agents", "skills", "plugins"] as const).map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => onTab(id)}
            className={cn(
              "h-7 flex-1 rounded-md",
              tab === id
                ? "bg-background font-medium shadow-sm"
                : "text-muted-foreground",
            )}
          >
            {
              {
                nodes: "节点",
                agents: "角色",
                skills: "Skill",
                plugins: "插件",
              }[id]
            }
          </button>
        ))}
      </div>
      {tab !== "nodes" ? (
        <div className="relative mx-3 mt-2">
          <SearchIcon className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            placeholder="搜索…"
            className="h-8 pl-8 text-xs"
          />
        </div>
      ) : null}
      <div className="max-h-[440px] overflow-y-auto p-2.5">
        {loading ? (
          <div className="grid h-28 place-items-center">
            <Loader2Icon className="size-4 animate-spin" />
          </div>
        ) : items.length === 0 ? (
          <div className="p-8 text-center text-xs text-muted-foreground">
            没有匹配的能力
          </div>
        ) : (
          <div className="space-y-0.5">
            {items.map((item, index) => {
              const Icon = item.icon;
              return (
                <button
                  key={`${item.title}-${index}`}
                  type="button"
                  onClick={() =>
                    onAdd(
                      item.kind,
                      item.title,
                      item.description,
                      "binding" in item ? item.binding : undefined,
                    )
                  }
                  className="group flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left hover:bg-muted/65"
                >
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-muted">
                    <Icon className="size-4" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5 text-[12px] font-medium">
                      {item.title}
                      {"badge" in item && item.badge ? (
                        <span className="rounded bg-foreground px-1 py-px text-[8px] text-background">
                          {item.badge}
                        </span>
                      ) : null}
                    </span>
                    <span className="block truncate text-[10px] text-muted-foreground">
                      {item.description}
                    </span>
                  </span>
                  <PlusIcon className="size-3.5 opacity-0 group-hover:opacity-100" />
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function DesignHomeView({
  onStart,
  onOpenSkills,
  onOpenComfy,
  onOpenCanvas,
}: {
  onStart: (prompt: string) => void;
  onOpenSkills: () => void;
  onOpenComfy: () => void;
  onOpenCanvas: () => void;
}) {
  const [prompt, setPrompt] = useState("");
  const [category, setCategory] = useState("精选");
  const showcases = [
    {
      category: "官方 Skill",
      title: "产品发布视觉套件",
      description: "从卖点、主视觉到横竖版短片，完成一套统一的发布内容。",
      duration: "0:18",
      tone: "from-slate-900 via-violet-700 to-fuchsia-300",
      prompt:
        "为一款新产品制作完整发布视觉套件，包括主视觉、分镜、短片和发布清单。",
    },
    {
      category: "特效包装",
      title: "手绘实拍融合短片",
      description: "让实拍空间与手绘线条发生接触、变形和节奏化响应。",
      duration: "0:16",
      tone: "from-cyan-900 via-sky-500 to-amber-200",
      prompt:
        "制作一条实拍与手绘线条融合的16秒创意短片，先给出视觉锚点和镜头方案。",
    },
    {
      category: "MV",
      title: "复古拼贴音乐 MV",
      description: "用纸张纹理、海报墙与卡点剪辑建立完整的音乐视觉系统。",
      duration: "0:24",
      tone: "from-rose-950 via-red-600 to-orange-200",
      prompt:
        "根据音乐结构制作复古拼贴MV，保持角色一致，并输出镜头、字幕和剪辑节奏。",
    },
    {
      category: "UI动效",
      title: "数字产品电影感演示",
      description: "把真实界面、交互路径和动效参考组织成可审片的产品宣传片。",
      duration: "0:20",
      tone: "from-zinc-950 via-emerald-700 to-teal-200",
      prompt:
        "把数字产品界面制作成电影感宣传片，准确展示交互、运镜、节奏和声音。",
    },
  ];
  const categories = [
    "精选",
    "官方 Skill",
    "特效包装",
    "影视片头",
    "MV",
    "二次元PV",
    "品牌广告",
    "UI动效",
  ];
  const visible =
    category === "精选"
      ? showcases
      : showcases.filter((item) => item.category === category);

  const submit = () => {
    const value = prompt.trim();
    if (value) onStart(value);
  };

  return (
    <div className="relative h-full overflow-y-auto bg-[#fafafa] dark:bg-[#0a0a0a]">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-45"
        style={{
          backgroundImage:
            "radial-gradient(circle, color-mix(in oklch, var(--foreground) 14%, transparent) 1px, transparent 1px)",
          backgroundSize: "24px 24px",
        }}
      />
      <div className="relative mx-auto w-full max-w-[920px] px-8 pb-14 pt-16">
        <div className="text-center">
          <div className="inline-flex items-center gap-2.5">
            <span className="grid size-11 place-items-center rounded-[13px] bg-[#111] text-white shadow-sm dark:bg-white dark:text-black">
              <WandSparklesIcon className="size-5" />
            </span>
            <h1 className="text-[34px] font-semibold tracking-[-0.045em]">
              Octopus Design
            </h1>
          </div>
          <p className="mt-2 text-[15px] text-muted-foreground">
            属于你的多模态 Agent 团队
          </p>
        </div>

        <div className="mx-auto mt-10 max-w-[760px] overflow-hidden rounded-[24px] border border-black/[0.08] bg-background shadow-[0_12px_34px_rgba(0,0,0,.08)] dark:border-white/10">
          <Textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                submit();
              }
            }}
            className="min-h-[94px] resize-none border-0 bg-transparent px-5 pt-5 text-[14px] shadow-none focus-visible:ring-0"
            placeholder="描述你要生成的内容，或直接说出完整目标…"
          />
          <div className="flex h-[52px] items-center gap-1.5 px-3 pb-3">
            <Button variant="ghost" size="icon" className="size-8 rounded-full">
              <PlusIcon className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 gap-1.5 rounded-lg text-[11px]"
            >
              <BotIcon className="size-3.5" /> 模型
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 gap-1.5 rounded-lg text-[11px]"
              onClick={onOpenSkills}
            >
              <PuzzleIcon className="size-3.5" /> Skill
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 gap-1.5 rounded-lg text-[11px]"
              onClick={onOpenComfy}
            >
              <WorkflowIcon className="size-3.5" /> 工作流
            </Button>
            <span className="flex-1" />
            <Button
              size="icon"
              className="size-9 rounded-full"
              disabled={!prompt.trim()}
              onClick={submit}
              aria-label="开始创作"
            >
              <SendIcon className="size-4" />
            </Button>
          </div>
        </div>

        <button
          type="button"
          onClick={onOpenCanvas}
          className="mx-auto mt-2 flex h-10 w-full max-w-[730px] items-center gap-2 rounded-b-[15px] bg-black/[0.035] px-5 text-[11px] text-muted-foreground hover:bg-black/[0.055] dark:bg-white/[0.05]"
        >
          <FolderIcon className="size-3.5" />
          进入当前创作画布
          <span className="flex-1" />
          <ArrowRightIcon className="size-3.5" />
        </button>

        <div className="mt-7 flex flex-wrap items-center justify-center gap-2">
          {categories.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setCategory(item)}
              className={cn(
                "h-8 rounded-full border border-black/[0.07] bg-background px-4 text-[11px] text-muted-foreground transition",
                category === item &&
                  "border-foreground bg-foreground font-medium text-background",
              )}
            >
              {item}
            </button>
          ))}
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {visible.map((item) => (
            <button
              key={item.title}
              type="button"
              onClick={() => setPrompt(item.prompt)}
              className="group overflow-hidden rounded-[14px] border border-black/[0.07] bg-background text-left shadow-[0_2px_5px_rgba(0,0,0,.04)] transition hover:-translate-y-0.5 hover:shadow-[0_8px_24px_rgba(0,0,0,.10)] dark:border-white/10"
            >
              <div
                className={cn(
                  "relative h-[118px] bg-gradient-to-br",
                  item.tone,
                )}
              >
                <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_25%,rgba(255,255,255,.45),transparent_28%)]" />
                <span className="absolute bottom-2 left-2 rounded bg-black/65 px-1.5 py-0.5 text-[9px] text-white">
                  {item.duration}
                </span>
              </div>
              <div className="p-3.5">
                <div className="truncate text-[12px] font-semibold">
                  {item.title}
                </div>
                <p className="mt-1.5 line-clamp-2 text-[10px] leading-[16px] text-muted-foreground">
                  {item.description}
                </p>
                <div className="mt-3 text-[9px] text-muted-foreground">
                  Octopus Design
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

const ASSET_DISPLAY_BATCH_SIZE = 24;

function AssetsView({
  agents,
  onUseAgent,
  projectId,
  onUseArtifact,
}: {
  agents: Agent[];
  onUseAgent: (agent: Agent) => void;
  projectId: string | null;
  onUseArtifact: (artifact: ProjectArtifact) => void;
}) {
  const [grid, setGrid] = useState(true);
  const [category, setCategory] = useState("所有类型");
  const [query, setQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(ASSET_DISPLAY_BATCH_SIZE);
  const [artifacts, setArtifacts] = useState<ProjectArtifact[]>([]);
  const [libraryAssets, setLibraryAssets] = useState<DesignLibraryAsset[]>([]);
  const [artifactsLoading, setArtifactsLoading] = useState(false);
  const [assetDialogOpen, setAssetDialogOpen] = useState(false);
  const [assetSaving, setAssetSaving] = useState(false);
  const [assetFile, setAssetFile] = useState<File | null>(null);
  const [assetName, setAssetName] = useState("");
  const [assetCategory, setAssetCategory] =
    useState<DesignLibraryAsset["category"]>("角色");
  const [assetDescription, setAssetDescription] = useState("");
  const [assetTags, setAssetTags] = useState("");
  const assetInputRef = useRef<HTMLInputElement>(null);
  const categories = [
    "所有类型",
    "项目产物",
    "角色",
    "场景",
    "风格包",
    "道具",
    "自定义",
  ];
  useEffect(() => {
    const controller = new AbortController();
    void fetch(`${getBackendBaseURL()}/api/design/assets`, {
      headers: authHeaders(),
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok)
          throw new Error(`design asset library failed: ${response.status}`);
        return (await response.json()) as { items?: DesignLibraryAsset[] };
      })
      .then((payload) => setLibraryAssets(payload.items ?? []))
      .catch((error: unknown) => {
        if ((error as { name?: string }).name !== "AbortError")
          setLibraryAssets([]);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!projectId) {
      setArtifacts([]);
      return;
    }
    const controller = new AbortController();
    setArtifactsLoading(true);
    void fetch(
      `${getBackendBaseURL()}/api/projects/${encodeURIComponent(projectId)}`,
      { headers: authHeaders(), signal: controller.signal },
    )
      .then(async (response) => {
        if (!response.ok)
          throw new Error(`project assets failed: ${response.status}`);
        return (await response.json()) as { artifacts?: ProjectArtifact[] };
      })
      .then((payload) => setArtifacts(payload.artifacts ?? []))
      .catch((error: unknown) => {
        if ((error as { name?: string }).name !== "AbortError")
          setArtifacts([]);
      })
      .finally(() => {
        if (!controller.signal.aborted) setArtifactsLoading(false);
      });
    return () => controller.abort();
  }, [projectId]);
  const needle = query.trim().toLowerCase();
  const visibleAgents =
    category === "所有类型" || category === "角色"
      ? agents.filter((agent) =>
          `${agent.display_name ?? agent.name} ${agent.description ?? ""}`
            .toLowerCase()
            .includes(needle),
        )
      : [];
  const visibleProjectArtifacts =
    category === "所有类型" || category === "项目产物"
      ? artifacts.filter((artifact) =>
          `${artifact.name} ${artifact.kind ?? ""} ${artifact.summary ?? ""}`
            .toLowerCase()
            .includes(needle),
        )
      : [];
  const visibleLibraryAssets = libraryAssets.filter(
    (asset) =>
      (category === "所有类型" || category === asset.category) &&
      `${asset.name} ${asset.category} ${asset.description ?? ""} ${(asset.tags ?? []).join(" ")}`
        .toLowerCase()
        .includes(needle),
  );
  const visibleArtifacts: ProjectArtifact[] = [
    ...visibleProjectArtifacts,
    ...visibleLibraryAssets.map((asset) => ({
      ...asset,
      summary: asset.description || asset.tags?.join(" · ") || asset.filename,
    })),
  ];
  const displayedAgents = visibleAgents.slice(0, visibleCount);
  const displayedArtifacts = visibleArtifacts.slice(0, visibleCount);
  const hasMoreAssets =
    displayedAgents.length < visibleAgents.length ||
    displayedArtifacts.length < visibleArtifacts.length;

  useEffect(() => {
    setVisibleCount(ASSET_DISPLAY_BATCH_SIZE);
  }, [category, query]);
  const createLibraryAsset = async () => {
    if (!assetFile || !assetName.trim()) return;
    const body = new FormData();
    body.append("file", assetFile);
    body.append("name", assetName.trim());
    body.append("category", assetCategory);
    body.append("description", assetDescription.trim());
    body.append("tags", assetTags.trim());
    setAssetSaving(true);
    try {
      const response = await fetch(`${getBackendBaseURL()}/api/design/assets`, {
        method: "POST",
        headers: authHeaders(),
        body,
      });
      const payload = (await response.json()) as { item?: DesignLibraryAsset };
      if (!response.ok || !payload.item)
        throw new Error(`design asset create failed: ${response.status}`);
      setLibraryAssets((current) => [
        payload.item!,
        ...current.filter((item) => item.id !== payload.item!.id),
      ]);
      setAssetDialogOpen(false);
      setAssetFile(null);
      setAssetName("");
      setAssetDescription("");
      setAssetTags("");
      toast.success("资产已保存，可在其他项目复用");
    } catch {
      toast.error("资产保存失败，请检查文件大小或登录状态");
    } finally {
      setAssetSaving(false);
    }
  };
  return (
    <>
      <div className="h-full overflow-y-auto bg-background px-11 py-9">
        <div className="mx-auto max-w-5xl">
          <h1 className="text-2xl font-semibold tracking-tight">资产中心</h1>
          <p className="mt-1.5 text-xs text-muted-foreground">
            沉淀可复用的角色、场景、风格包、道具等素材，在新的创作空间中快速调用
          </p>
          <div className="mt-7 flex flex-wrap gap-2">
            <Button
              className="rounded-xl"
              onClick={() => setAssetDialogOpen(true)}
            >
              <PlusIcon className="mr-1.5 size-4" />
              添加资产
            </Button>
            <Button
              variant="outline"
              className="rounded-xl"
              onClick={() => toast.info("资产包导入将保留来源、版本和依赖信息")}
            >
              <ArchiveIcon className="mr-1.5 size-4" />
              导入资产包
            </Button>
          </div>
          <div className="mt-8 flex items-center border-t border-border-subtle pt-4">
            <div className="flex gap-1 text-xs">
              {categories.map((item) => (
                <button
                  key={item}
                  onClick={() => setCategory(item)}
                  className={cn(
                    "rounded-lg px-3 py-2",
                    category === item
                      ? "bg-muted font-medium"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {item}
                </button>
              ))}
            </div>
            <span className="flex-1" />
            <div className="relative w-60">
              <SearchIcon className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                className="h-9 rounded-xl pl-9 text-xs"
                placeholder="搜索资产"
              />
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setGrid(true)}
              className={cn("ml-2 size-8", grid && "bg-muted")}
            >
              <Grid2X2Icon className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setGrid(false)}
              className={cn("size-8", !grid && "bg-muted")}
            >
              <ListIcon className="size-4" />
            </Button>
          </div>
          {artifactsLoading ? (
            <div className="mt-6 flex items-center gap-2 text-[11px] text-muted-foreground">
              <Loader2Icon className="size-3.5 animate-spin" />
              正在读取项目产物
            </div>
          ) : null}
          {visibleArtifacts.length > 0 ? (
            <>
              <div className="mt-6 flex items-center gap-2">
                <h2 className="text-[13px] font-semibold">资产</h2>
                <span className="text-[10px] text-muted-foreground">
                  {visibleArtifacts.length}
                </span>
              </div>
              <div
                className={cn(
                  "mt-3",
                  grid
                    ? "grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4"
                    : "flex flex-col gap-2",
                )}
              >
                {displayedArtifacts.map((artifact) => {
                  const kind = artifactNodeKind(artifact);
                  const previewUrl = artifact.url
                    ? artifact.url.startsWith("/")
                      ? `${getBackendBaseURL()}${artifact.url}`
                      : artifact.url
                    : null;
                  return (
                    <article
                      key={artifact.id}
                      className={cn(
                        "group overflow-hidden rounded-[12px] border border-border-default bg-background transition hover:border-sky-300 hover:shadow-[0_14px_35px_-20px_rgba(0,0,0,.3)]",
                        !grid && "flex items-center p-2.5",
                      )}
                    >
                      <div
                        className={cn(
                          "relative grid shrink-0 place-items-center overflow-hidden bg-gradient-to-br from-sky-100 via-cyan-50 to-background",
                          grid ? "h-32 w-full" : "size-12 rounded-lg",
                        )}
                      >
                        {kind === "image" && previewUrl ? (
                          <img
                            src={previewUrl}
                            alt=""
                            className="size-full object-cover"
                          />
                        ) : kind === "video" ? (
                          <CirclePlayIcon
                            className={cn(grid ? "size-10" : "size-5")}
                          />
                        ) : kind === "image" ? (
                          <ImageIcon
                            className={cn(grid ? "size-10" : "size-5")}
                          />
                        ) : (
                          <ArchiveIcon
                            className={cn(grid ? "size-10" : "size-5")}
                          />
                        )}
                        {grid ? (
                          <span className="absolute left-2.5 top-2.5 rounded-md bg-black/65 px-1.5 py-0.5 text-[8px] font-medium text-white">
                            {artifact.category || KIND_STYLE[kind].label}
                          </span>
                        ) : null}
                      </div>
                      <div
                        className={cn("min-w-0 flex-1", grid ? "p-3" : "ml-3")}
                      >
                        <div className="truncate text-[12px] font-semibold">
                          {artifact.name}
                        </div>
                        <p className="mt-1 line-clamp-2 min-h-8 text-[10px] leading-4 text-muted-foreground">
                          {artifact.summary ||
                            artifact.path ||
                            artifact.kind ||
                            "项目交付产物"}
                        </p>
                        <div className="mt-2 flex items-center text-[9px] text-muted-foreground">
                          <span>
                            {artifact.category ||
                              (artifact.milestone_id
                                ? "里程碑产物"
                                : "项目产物")}
                          </span>
                          <button
                            onClick={() => onUseArtifact(artifact)}
                            className="ml-auto rounded-md bg-foreground px-2 py-1 text-background opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
                          >
                            加入画布
                          </button>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </>
          ) : null}
          {visibleAgents.length > 0 ? (
            <>
              <div className="mt-6 flex items-center gap-2">
                <h2 className="text-[13px] font-semibold">角色资产</h2>
                <span className="text-[10px] text-muted-foreground">
                  {visibleAgents.length}
                </span>
              </div>
              <div
                className={cn(
                  "mt-3",
                  grid
                    ? "grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4"
                    : "flex flex-col gap-2",
                )}
              >
                {displayedAgents.map((agent) => {
                  const title = agent.display_name || agent.name;
                  const imageUrl =
                    agent.avatar_url || agent.visual_urls?.portrait;
                  return (
                    <article
                      key={agent.name}
                      className={cn(
                        "group overflow-hidden rounded-[12px] border border-border-default bg-background transition hover:border-violet-300 hover:shadow-[0_14px_35px_-20px_rgba(0,0,0,.3)]",
                        !grid && "flex items-center p-2.5",
                      )}
                    >
                      <div
                        className={cn(
                          "relative grid shrink-0 place-items-center overflow-hidden bg-gradient-to-br from-violet-100 via-indigo-50 to-background",
                          grid ? "h-32 w-full" : "size-12 rounded-lg",
                        )}
                      >
                        {imageUrl ? (
                          <img
                            src={imageUrl}
                            alt=""
                            className="size-full object-cover"
                          />
                        ) : (
                          <span className={cn(grid ? "text-4xl" : "text-xl")}>
                            {agent.icon || "✦"}
                          </span>
                        )}
                        {grid ? (
                          <span className="absolute left-2.5 top-2.5 rounded-md bg-black/65 px-1.5 py-0.5 text-[8px] font-medium text-white">
                            角色
                          </span>
                        ) : null}
                      </div>
                      <div
                        className={cn("min-w-0 flex-1", grid ? "p-3" : "ml-3")}
                      >
                        <div className="truncate text-[12px] font-semibold">
                          {title}
                        </div>
                        <p className="mt-1 line-clamp-2 min-h-8 text-[10px] leading-4 text-muted-foreground">
                          {agent.description || "Octopus AI 创作角色"}
                        </p>
                        <div className="mt-2 flex items-center text-[9px] text-muted-foreground">
                          <span>{agent.model || "跟随当前模型"}</span>
                          <button
                            onClick={() => onUseAgent(agent)}
                            className="ml-auto rounded-md bg-foreground px-2 py-1 text-background opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
                          >
                            加入画布
                          </button>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            </>
          ) : visibleArtifacts.length === 0 && !artifactsLoading ? (
            <div className="grid min-h-[420px] place-items-center text-center">
              <div>
                <ArchiveIcon className="mx-auto size-7 text-muted-foreground/50" />
                <p className="mt-4 text-sm font-semibold">
                  {query ? "没有匹配的资产" : `还没有${category}资产`}
                </p>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  点击上方添加资产，或从画布节点保存为可复用资产
                </p>
              </div>
            </div>
          ) : null}
          {hasMoreAssets ? (
            <div className="mt-6 flex justify-center">
              <Button
                type="button"
                variant="outline"
                className="rounded-xl"
                onClick={() =>
                  setVisibleCount((count) => count + ASSET_DISPLAY_BATCH_SIZE)
                }
              >
                加载更多
                <span className="ml-1.5 text-xs text-muted-foreground">
                  {Math.min(
                    visibleCount,
                    Math.max(visibleAgents.length, visibleArtifacts.length),
                  )}
                  /{Math.max(visibleAgents.length, visibleArtifacts.length)}
                </span>
              </Button>
            </div>
          ) : null}
        </div>
      </div>
      <Dialog open={assetDialogOpen} onOpenChange={setAssetDialogOpen}>
        <DialogContent className="gap-0 overflow-hidden p-0 sm:max-w-[500px]">
          <DialogHeader className="border-b border-border-subtle px-5 py-4 pr-12">
            <DialogTitle className="text-[15px]">添加资产</DialogTitle>
            <DialogDescription className="text-[11px] leading-5">
              填写清晰的名称、描述和标签，让 Agent 能搜索并在不同项目中复用。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 px-5 py-4">
            <div className="grid grid-cols-[1fr_120px] gap-2">
              <Input
                value={assetName}
                onChange={(event) => setAssetName(event.target.value)}
                placeholder="资产名称"
                className="h-9 rounded-lg text-xs"
                maxLength={120}
              />
              <select
                value={assetCategory}
                onChange={(event) =>
                  setAssetCategory(
                    event.target.value as DesignLibraryAsset["category"],
                  )
                }
                className="h-9 rounded-lg border border-border-default bg-background px-3 text-xs outline-none focus:ring-2 focus:ring-ring"
              >
                {["角色", "场景", "风格包", "道具", "自定义"].map((item) => (
                  <option key={item}>{item}</option>
                ))}
              </select>
            </div>
            <Textarea
              value={assetDescription}
              onChange={(event) => setAssetDescription(event.target.value)}
              placeholder="输入清晰的描述，帮助 Agent 更好地搜索和复用…"
              className="min-h-20 resize-none rounded-lg text-xs leading-5"
              maxLength={1200}
            />
            <input
              ref={assetInputRef}
              type="file"
              hidden
              accept="image/*,video/*,audio/*,.pdf,.txt,.md,.csv,.xls,.xlsx,.ppt,.pptx,.doc,.docx"
              onChange={(event) => {
                const selected = event.target.files?.[0] ?? null;
                setAssetFile(selected);
                if (selected && !assetName.trim())
                  setAssetName(selected.name.replace(/\.[^.]+$/, ""));
                event.target.value = "";
              }}
            />
            <button
              type="button"
              onClick={() => assetInputRef.current?.click()}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                const selected = event.dataTransfer.files?.[0] ?? null;
                setAssetFile(selected);
                if (selected && !assetName.trim())
                  setAssetName(selected.name.replace(/\.[^.]+$/, ""));
              }}
              className="grid min-h-36 w-full place-items-center rounded-xl border border-dashed border-border-default bg-muted/20 text-center transition hover:border-foreground/40 hover:bg-muted/35"
            >
              <span>
                <ArchiveIcon className="mx-auto size-5 text-muted-foreground" />
                <span className="mt-2 block text-[11px] font-medium">
                  {assetFile ? assetFile.name : "将素材文件拖入 / 点击上传"}
                </span>
                <span className="mt-1 block text-[9px] text-muted-foreground">
                  单个文件最大 64 MB
                </span>
              </span>
            </button>
            <Input
              value={assetTags}
              onChange={(event) => setAssetTags(event.target.value)}
              placeholder="添加标签（可选），用逗号分隔"
              className="h-9 rounded-lg text-xs"
              maxLength={600}
            />
          </div>
          <DialogFooter className="border-t border-border-subtle px-5 py-3">
            <Button
              size="sm"
              disabled={!assetFile || !assetName.trim() || assetSaving}
              onClick={() => void createLibraryAsset()}
              className="rounded-lg px-4"
            >
              {assetSaving ? (
                <Loader2Icon className="mr-1.5 size-3.5 animate-spin" />
              ) : null}
              创建资产
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function CanvasAssetsPanel({
  projectId,
  document,
  onClose,
  onPick,
}: {
  projectId: string | null;
  document: DesignCanvasDocument;
  onClose: () => void;
  onPick: (artifact: ProjectArtifact) => void;
}) {
  const [tab, setTab] = useState<"canvas" | "assets">("canvas");
  const [grid, setGrid] = useState(false);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [projectArtifacts, setProjectArtifacts] = useState<ProjectArtifact[]>(
    [],
  );
  const [libraryAssets, setLibraryAssets] = useState<DesignLibraryAsset[]>([]);
  const [loading, setLoading] = useState(false);
  const uploadRef = useRef<HTMLInputElement>(null);
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [libraryResponse, projectResponse] = await Promise.all([
        fetch(`${getBackendBaseURL()}/api/design/assets`, {
          headers: authHeaders(),
        }),
        projectId
          ? fetch(
              `${getBackendBaseURL()}/api/projects/${encodeURIComponent(projectId)}`,
              {
                headers: authHeaders(),
              },
            )
          : Promise.resolve(null),
      ]);
      if (libraryResponse.ok) {
        const payload = (await libraryResponse.json()) as {
          items?: DesignLibraryAsset[];
        };
        setLibraryAssets(payload.items ?? []);
      }
      if (projectResponse?.ok) {
        const payload = (await projectResponse.json()) as {
          artifacts?: ProjectArtifact[];
        };
        setProjectArtifacts(payload.artifacts ?? []);
      } else if (!projectId) {
        setProjectArtifacts([]);
      }
    } finally {
      setLoading(false);
    }
  }, [projectId]);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  const canvasAssets = useMemo(() => {
    const byId = new Map<string, ProjectArtifact>();
    for (const artifact of projectArtifacts) byId.set(artifact.id, artifact);
    for (const node of document.nodes) {
      if (!node.asset) continue;
      byId.set(node.asset.id, {
        id: node.asset.id,
        name: node.title,
        kind: node.asset.kind,
        path: node.asset.path,
        url: node.asset.url,
        summary: node.description,
      });
    }
    return [...byId.values()];
  }, [document.nodes, projectArtifacts]);
  const source: ProjectArtifact[] =
    tab === "canvas" ? canvasAssets : libraryAssets;
  const needle = query.trim().toLowerCase();
  const items = source.filter((item) => {
    const kind = artifactNodeKind(item);
    return (
      (typeFilter === "all" || kind === typeFilter) &&
      `${item.name} ${item.summary ?? ""} ${item.path ?? ""} ${item.category ?? ""}`
        .toLowerCase()
        .includes(needle)
    );
  });
  const uploadProjectFiles = async (files: FileList) => {
    if (!projectId) {
      toast.info("当前画布尚未绑定项目");
      return;
    }
    const body = new FormData();
    Array.from(files)
      .slice(0, 12)
      .forEach((file) => body.append("files", file));
    setLoading(true);
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/design/projects/${encodeURIComponent(projectId)}/assets`,
        { method: "POST", headers: authHeaders(), body },
      );
      if (!response.ok) throw new Error("project upload failed");
      const payload = (await response.json()) as { items?: ProjectArtifact[] };
      setProjectArtifacts((current) => [
        ...(payload.items ?? []),
        ...current.filter(
          (item) =>
            !(payload.items ?? []).some((added) => added.id === item.id),
        ),
      ]);
      toast.success(`已上传 ${(payload.items ?? []).length} 个项目文件`);
    } catch {
      toast.error("项目文件上传失败");
    } finally {
      setLoading(false);
    }
  };
  return (
    <aside className="flex w-[280px] shrink-0 flex-col border-l border-border-subtle bg-background">
      <div className="flex h-11 items-center border-b border-border-subtle px-2">
        <div className="grid flex-1 grid-cols-2 rounded-lg bg-muted/60 p-0.5 text-[11px]">
          {(["canvas", "assets"] as const).map((item) => (
            <button
              key={item}
              onClick={() => setTab(item)}
              className={cn(
                "rounded-md px-2 py-1.5",
                tab === item && "bg-background font-semibold shadow-sm",
              )}
            >
              {item === "canvas" ? "画布" : "资产"}
            </button>
          ))}
        </div>
        <button
          onClick={onClose}
          className="ml-2 grid size-7 place-items-center rounded-lg hover:bg-muted"
          aria-label="关闭项目资产"
        >
          <XIcon className="size-3.5" />
        </button>
      </div>
      <div className="flex items-center gap-1 border-b border-border-subtle px-2 py-2">
        <button
          onClick={() => setGrid(false)}
          className={cn(
            "grid size-7 place-items-center rounded-md",
            !grid && "bg-muted",
          )}
          title="树形视图"
        >
          <ListIcon className="size-3.5" />
        </button>
        <button
          onClick={() => setGrid(true)}
          className={cn(
            "grid size-7 place-items-center rounded-md",
            grid && "bg-muted",
          )}
          title="网格视图"
        >
          <Grid2X2Icon className="size-3.5" />
        </button>
        <span className="flex-1" />
        <button
          onClick={() => void refresh()}
          className="grid size-7 place-items-center rounded-md hover:bg-muted"
          title="刷新文件列表"
        >
          <Redo2Icon className={cn("size-3.5", loading && "animate-spin")} />
        </button>
      </div>
      <div className="space-y-2 px-2 py-2">
        <div className="relative">
          <SearchIcon className="absolute left-2.5 top-1/2 size-3 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索文件"
            className="h-8 rounded-lg pl-8 text-[10px]"
          />
        </div>
        <div className="grid grid-cols-3 gap-1">
          <select
            value={typeFilter}
            onChange={(event) => setTypeFilter(event.target.value)}
            className="h-7 rounded-md border border-border-default bg-background px-1.5 text-[9px]"
          >
            <option value="all">类型</option>
            <option value="image">图片</option>
            <option value="video">视频</option>
            <option value="audio">音频</option>
            <option value="file">文件</option>
          </select>
          <button className="h-7 rounded-md border border-border-default text-[9px] text-muted-foreground">
            标签
          </button>
          <button className="h-7 rounded-md border border-border-default text-[9px] text-muted-foreground">
            时间
          </button>
        </div>
      </div>
      <div
        className={cn(
          "min-h-0 flex-1 overflow-y-auto px-2 pb-2",
          grid ? "grid auto-rows-max grid-cols-2 gap-2" : "space-y-0.5",
        )}
      >
        {items.map((item) => {
          const kind = artifactNodeKind(item);
          return (
            <button
              key={item.id}
              onClick={() => onPick(item)}
              className={cn(
                "group text-left hover:bg-muted",
                grid
                  ? "overflow-hidden rounded-lg border border-border-subtle"
                  : "flex w-full items-center gap-2 rounded-md px-2 py-1.5",
              )}
              title="在画布中定位"
            >
              <div
                className={cn(
                  "grid shrink-0 place-items-center bg-muted",
                  grid ? "h-16 w-full" : "size-6 rounded",
                )}
              >
                {kind === "image" ? (
                  <ImageIcon className="size-3.5" />
                ) : kind === "video" ? (
                  <CirclePlayIcon className="size-3.5" />
                ) : (
                  <ArchiveIcon className="size-3.5" />
                )}
              </div>
              <span className={cn("min-w-0", grid && "block p-2")}>
                <span className="block truncate text-[10px] font-medium">
                  {item.name}
                </span>
                <span className="block truncate text-[8px] text-muted-foreground">
                  {item.category || item.kind || "文件"}
                </span>
              </span>
            </button>
          );
        })}
        {!loading && items.length === 0 ? (
          <div className="col-span-2 px-3 py-12 text-center text-[10px] text-muted-foreground">
            {query
              ? "没有匹配文件"
              : tab === "canvas"
                ? "画布还没有项目文件"
                : "资产库为空"}
          </div>
        ) : null}
      </div>
      {tab === "canvas" ? (
        <div className="border-t border-border-subtle p-2">
          <input
            ref={uploadRef}
            type="file"
            multiple
            hidden
            onChange={(event) => {
              if (event.target.files?.length)
                void uploadProjectFiles(event.target.files);
              event.target.value = "";
            }}
          />
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-full justify-center text-[10px]"
            onClick={() => uploadRef.current?.click()}
            disabled={!projectId}
          >
            <PlusIcon className="mr-1 size-3.5" />
            上传文件
          </Button>
        </div>
      ) : null}
    </aside>
  );
}

function SkillsView({
  onUse,
  installedSkills,
  loading,
}: {
  onUse: (id: string) => void;
  installedSkills: SkillInfo[];
  loading: boolean;
}) {
  const navigate = useNavigate();
  const enableSkill = useEnableSkill();
  const enableMarketSkill = useEnableMarketSkill();
  const [category, setCategory] = useState("全部");
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<"market" | "mine">("market");
  const [onlyUninstalled, setOnlyUninstalled] = useState(false);
  const [skillSort, setSkillSort] = useState<"recent" | "popular">("recent");
  const [detailSkillId, setDetailSkillId] = useState<string | null>(null);
  const [detailFiles, setDetailFiles] = useState<
    Array<{ path: string; content: string }>
  >([]);
  const [detailFilePath, setDetailFilePath] = useState("SKILL.md");
  const [detailLoading, setDetailLoading] = useState(false);
  const categories = [
    "全部",
    "精选",
    "短剧漫剧",
    "专业影视",
    "动画",
    "商业广告",
    "电商",
    "教育",
    "创意实验",
    "音频音乐",
    "平台工具",
  ];
  const needle = query.trim().toLowerCase();
  const installedByName = new Map(
    installedSkills.map((skill) => [skill.name, skill]),
  );
  const featuredSkillIds = new Set(
    CREATIVE_SKILL_COLLECTION.slice(0, 30).map((item) => item.id),
  );
  const downloadScore = (value: string) => {
    if (value === "内置") return Number.MAX_SAFE_INTEGER;
    const score = Number.parseFloat(value);
    return Number.isFinite(score) ? score : 0;
  };
  const items = CREATIVE_SKILL_COLLECTION.filter((item) => {
    const installed = installedByName.get(item.id);
    return (
      (tab === "market" || Boolean(installed)) &&
      (!onlyUninstalled || !installed) &&
      (category === "全部" ||
        (category === "精选" && featuredSkillIds.has(item.id)) ||
        item.category === category) &&
      (!needle ||
        `${item.title} ${item.description} ${item.category}`
          .toLowerCase()
          .includes(needle))
    );
  }).sort((left, right) =>
    skillSort === "popular"
      ? downloadScore(right.downloads) - downloadScore(left.downloads)
      : 0,
  );
  const detailSkill = detailSkillId
    ? (CREATIVE_SKILL_COLLECTION.find((item) => item.id === detailSkillId) ??
      null)
    : null;
  useEffect(() => {
    if (!detailSkillId) {
      setDetailFiles([]);
      return;
    }
    const controller = new AbortController();
    setDetailLoading(true);
    void fetch(
      `${getBackendBaseURL()}/api/design/skills/${encodeURIComponent(detailSkillId)}/files`,
      { headers: authHeaders(), signal: controller.signal },
    )
      .then(async (response) => {
        if (!response.ok)
          throw new Error(`skill preview failed: ${response.status}`);
        return (await response.json()) as {
          items?: Array<{ path: string; content: string }>;
        };
      })
      .then((payload) => {
        const files = payload.items ?? [];
        setDetailFiles(files);
        setDetailFilePath(
          files.some((item) => item.path === "SKILL.md")
            ? "SKILL.md"
            : files[0]?.path || "",
        );
      })
      .catch((error: unknown) => {
        if ((error as { name?: string }).name !== "AbortError") {
          setDetailFiles([]);
          toast.error("Skill 文件读取失败");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [detailSkillId]);
  const handleUseSkill = async (id: string) => {
    const installed = installedByName.get(id);
    if (!installed) {
      try {
        await enableMarketSkill.mutateAsync(id);
        toast.success("Skill 已安装并启用");
      } catch {
        toast.error("Skill 安装失败");
        return;
      }
    }
    if (installed && !installed.enabled) {
      try {
        await enableSkill.mutateAsync({ skillName: id, enabled: true });
        toast.success("Skill 已启用");
      } catch {
        toast.error("Skill 启用失败");
        return;
      }
    }
    onUse(id);
  };

  return (
    <>
      <div className="h-full overflow-y-auto bg-background px-10 py-8">
        <div className="mx-auto max-w-[1120px]">
          <h1 className="text-[24px] font-semibold tracking-tight">Skill</h1>
          <p className="mt-1 text-[12px] text-muted-foreground">
            发现、安装并管理 Skill，扩展 Octopus Design 的创作能力
          </p>
          <div className="mt-7 flex gap-2">
            <Button
              className="h-9 rounded-[10px] bg-foreground px-4 text-[11px] text-background"
              onClick={() =>
                toast.info("可在对话中让 Agent 为当前流程创建 Skill")
              }
            >
              <WandSparklesIcon className="mr-1.5 size-3.5" />
              通过 Octopus 创建
            </Button>
            <Button
              variant="outline"
              className="h-9 rounded-[10px] px-4 text-[11px]"
              onClick={() => navigate("/workspace/skills")}
            >
              <PlusIcon className="mr-1.5 size-3.5" />
              管理与安装
            </Button>
          </div>

          <div className="mt-7 border-t border-border-subtle pt-3">
            <div className="flex items-center gap-5">
              <button
                onClick={() => setTab("market")}
                className={cn(
                  "relative h-9 text-[12px] font-medium",
                  tab === "market"
                    ? "text-foreground after:absolute after:bottom-0 after:left-0 after:right-0 after:h-0.5 after:bg-foreground"
                    : "text-muted-foreground",
                )}
              >
                Skill
              </button>
              <button
                onClick={() => setTab("mine")}
                className={cn(
                  "relative h-9 text-[12px] font-medium",
                  tab === "mine"
                    ? "text-foreground after:absolute after:bottom-0 after:left-0 after:right-0 after:h-0.5 after:bg-foreground"
                    : "text-muted-foreground",
                )}
              >
                我的 Skill
              </button>
              <span className="flex-1" />
              <div className="relative w-60 shrink-0">
                <SearchIcon className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  className="h-9 rounded-[10px] pl-9 text-[11px]"
                  placeholder="搜索 Skill..."
                />
              </div>
            </div>
            <div className="mt-2 flex min-w-0 gap-1 overflow-x-auto text-[11px]">
              {categories.map((item) => (
                <button
                  key={item}
                  onClick={() => setCategory(item)}
                  className={cn(
                    "shrink-0 rounded-md px-3 py-2",
                    category === item
                      ? "bg-muted font-medium text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>

          <div className="mt-6 flex items-center">
            <h2 className="text-[15px] font-semibold">
              {tab === "market"
                ? category === "精选"
                  ? "官方精选"
                  : "创作 Skill"
                : "已安装 Skill"}
            </h2>
            <span className="ml-2 text-[10px] text-muted-foreground">
              {loading ? "…" : items.length}
            </span>
            {tab === "market" ? (
              <>
                <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-[10px] text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={onlyUninstalled}
                    onChange={(event) =>
                      setOnlyUninstalled(event.target.checked)
                    }
                    className="size-3 rounded border-border-default"
                  />
                  仅显示未安装
                </label>
                <select
                  value={skillSort}
                  onChange={(event) =>
                    setSkillSort(event.target.value as "recent" | "popular")
                  }
                  className="ml-3 h-7 rounded-lg border border-border-default bg-background px-2 text-[10px] text-muted-foreground outline-none"
                  aria-label="Skill 排序"
                >
                  <option value="recent">最近</option>
                  <option value="popular">最热门</option>
                </select>
              </>
            ) : null}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
            {items.map((item) => {
              const Icon = item.icon;
              const installed = installedByName.get(item.id);
              const catalogIndex = CREATIVE_SKILL_COLLECTION.findIndex(
                (skill) => skill.id === item.id,
              );
              const cover =
                CREATIVE_SKILL_COVERS[
                  Math.max(0, catalogIndex) % CREATIVE_SKILL_COVERS.length
                ];
              return (
                <article
                  key={item.id}
                  className="group overflow-hidden rounded-[12px] border border-border-default bg-background transition hover:-translate-y-0.5 hover:shadow-[0_14px_35px_-18px_rgba(0,0,0,.35)]"
                >
                  <div
                    className={cn(
                      "relative h-28 overflow-hidden bg-gradient-to-br",
                      item.tone,
                    )}
                  >
                    <img
                      src={cover}
                      alt=""
                      className="absolute inset-0 size-full object-cover transition duration-300 group-hover:scale-[1.03]"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/20 via-transparent to-white/5" />
                    <div className="absolute inset-0 bg-[radial-gradient(circle_at_25%_15%,rgba(255,255,255,.65),transparent_34%)]" />
                    <Icon className="absolute bottom-3 right-4 size-8 text-white/75 drop-shadow" />
                    <span className="absolute left-2.5 top-2.5 rounded-md bg-violet-600 px-1.5 py-0.5 text-[8px] font-medium text-white">
                      {installed
                        ? installed.enabled
                          ? "已启用"
                          : "已安装"
                        : "官方"}
                    </span>
                    <div className="absolute inset-0 flex items-center justify-center gap-1.5 bg-black/40 opacity-0 backdrop-blur-[1px] transition-opacity group-hover:opacity-100">
                      <button
                        onClick={() => setDetailSkillId(item.id)}
                        className="rounded-lg bg-white/92 px-2.5 py-1.5 text-[9px] font-medium text-zinc-900"
                      >
                        查看详情
                      </button>
                      <button
                        onClick={() => void handleUseSkill(item.id)}
                        disabled={
                          enableSkill.isPending || enableMarketSkill.isPending
                        }
                        className="rounded-lg bg-zinc-950/90 px-2.5 py-1.5 text-[9px] font-medium text-white"
                      >
                        {installed?.enabled
                          ? "加入画布"
                          : installed
                            ? "启用并加入"
                            : "安装并加入"}
                      </button>
                    </div>
                  </div>
                  <button
                    onClick={() => void handleUseSkill(item.id)}
                    className="block w-full p-3 text-left"
                  >
                    <div className="truncate text-[13px] font-semibold">
                      {item.title}
                    </div>
                    <p className="mt-1 line-clamp-2 min-h-8 text-[10px] leading-4 text-muted-foreground">
                      {item.description}
                    </p>
                    <div className="mt-3 flex items-center gap-1 text-[9px] text-muted-foreground">
                      <span>Octopus Design</span>
                      {installed ? (
                        <CheckIcon
                          className={cn(
                            "size-3",
                            installed.enabled
                              ? "text-emerald-500"
                              : "text-amber-500",
                          )}
                        />
                      ) : null}
                      <span className="ml-auto inline-flex items-center gap-1">
                        <ArchiveIcon className="size-2.5" />
                        {item.downloads}
                      </span>
                    </div>
                  </button>
                </article>
              );
            })}
          </div>
        </div>
      </div>
      <Dialog
        open={Boolean(detailSkill)}
        onOpenChange={(open) => {
          if (!open) setDetailSkillId(null);
        }}
      >
        <DialogContent className="flex h-[78vh] max-h-[760px] flex-col gap-0 overflow-hidden p-0 sm:max-w-[920px]">
          {detailSkill ? (
            <>
              <DialogHeader className="shrink-0 border-b border-border-subtle px-6 py-4 pr-12">
                <div className="flex items-center gap-2">
                  <DialogTitle className="text-[15px]">
                    {detailSkill.title}
                  </DialogTitle>
                  <span className="rounded-md bg-muted px-2 py-1 text-[9px] text-muted-foreground">
                    {detailSkill.category}
                  </span>
                </div>
                <DialogDescription className="max-w-3xl text-[11px] leading-5">
                  {detailSkill.description}
                </DialogDescription>
              </DialogHeader>
              <div className="flex min-h-0 flex-1">
                <aside className="w-[220px] shrink-0 overflow-y-auto border-r border-border-subtle bg-muted/20 p-2">
                  {detailLoading ? (
                    <div className="grid h-32 place-items-center">
                      <Loader2Icon className="size-4 animate-spin" />
                    </div>
                  ) : (
                    detailFiles.map((file) => {
                      const nested = file.path.includes("/");
                      return (
                        <button
                          key={file.path}
                          onClick={() => setDetailFilePath(file.path)}
                          className={cn(
                            "flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-[10px] hover:bg-muted",
                            nested && "pl-5",
                            detailFilePath === file.path &&
                              "bg-muted font-medium",
                          )}
                        >
                          {nested ? (
                            <BookOpenIcon className="size-3 shrink-0" />
                          ) : (
                            <ArchiveIcon className="size-3 shrink-0" />
                          )}
                          <span className="truncate">{file.path}</span>
                        </button>
                      );
                    })
                  )}
                </aside>
                <section className="flex min-w-0 flex-1 flex-col">
                  <div className="flex h-10 shrink-0 items-center border-b border-border-subtle px-4 text-[10px] font-medium">
                    {detailFilePath || "Skill 文件"}
                    <span className="ml-auto rounded bg-muted px-1.5 py-0.5 text-[8px] text-muted-foreground">
                      {detailFilePath.endsWith(".json") ? "JSON" : "Markdown"}
                    </span>
                  </div>
                  <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words px-5 py-4 font-sans text-[11px] leading-6 text-foreground">
                    {detailFiles.find((file) => file.path === detailFilePath)
                      ?.content ||
                      (detailLoading ? "正在读取…" : "没有可预览的文本文件")}
                  </pre>
                </section>
              </div>
              <DialogFooter className="shrink-0 border-t border-border-subtle px-5 py-3">
                <span className="mr-auto self-center text-[9px] text-muted-foreground">
                  Octopus 原创 · Apache-2.0
                </span>
                <Button
                  size="sm"
                  className="rounded-lg"
                  disabled={
                    enableSkill.isPending || enableMarketSkill.isPending
                  }
                  onClick={() => {
                    void handleUseSkill(detailSkill.id);
                    setDetailSkillId(null);
                  }}
                >
                  {installedByName.get(detailSkill.id)?.enabled
                    ? "加入画布"
                    : installedByName.get(detailSkill.id)
                      ? "启用并加入"
                      : "安装并加入"}
                </Button>
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}

function formatModelSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

function ComfyUIView({
  onUse,
}: {
  onUse: (id: string, title: string) => void;
}) {
  const [checking, setChecking] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const [comfyProcess, setComfyProcess] = useState({
    owned: false,
    running: false,
  });
  const [dependencies, setDependencies] = useState<{
    detected: boolean;
    path: string | null;
    modelCounts: Record<string, number>;
    totalModels: number;
    customNodes: string[];
    totalCustomNodes: number;
    managed: boolean;
    manager: {
      installed: boolean;
      home: string;
      job: {
        running?: boolean;
        state?: string;
        phase?: string;
        action?: string;
        node_id?: string | null;
        model_group?: string | null;
        error?: string | null;
      };
      runtime?: { version?: string | null; commit?: string | null };
      logTail?: string[];
    };
  } | null>(null);
  const [environmentOpen, setEnvironmentOpen] = useState(false);
  const [tab, setTab] = useState<"market" | "mine">("market");
  const [query, setQuery] = useState("");
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(
    null,
  );
  const [selectedWorkflowDetail, setSelectedWorkflowDetail] = useState<{
    workflow: Record<
      string,
      { class_type?: string; inputs?: Record<string, unknown> }
    >;
  } | null>(null);
  const [nodeQuery, setNodeQuery] = useState("");
  const [nodeLoading, setNodeLoading] = useState(false);
  const [registryNodes, setRegistryNodes] = useState<
    Array<{
      id: string;
      name: string;
      description: string;
      publisher: string;
      repository: string;
      downloads: number;
      stars: number;
      version: string;
      dependencies: string[];
      deprecated: boolean;
      installed: boolean;
      backups: Array<{ id: string; created_at?: string }>;
    }>
  >([]);
  const [modelUrl, setModelUrl] = useState("");
  const [modelGroup, setModelGroup] = useState("checkpoints");
  const [modelLoading, setModelLoading] = useState(false);
  const [localModels, setLocalModels] = useState<
    Array<{
      id: string;
      group: string;
      name: string;
      size_bytes: number;
      modified_at?: string;
    }>
  >([]);
  const [modelBackups, setModelBackups] = useState<
    Array<{
      id: string;
      group: string;
      name: string;
      size_bytes: number;
    }>
  >([]);
  const [modelGroups, setModelGroups] = useState<string[]>([
    "checkpoints",
    "diffusion_models",
    "loras",
    "vae",
    "controlnet",
  ]);
  const [remoteWorkflows, setRemoteWorkflows] = useState<
    Array<{
      id: string;
      name: string;
      description: string;
      tags: string[];
      source: "bundled" | "user";
    }>
  >([]);
  const [runState, setRunState] = useState<{
    workflowId: string;
    promptId: string;
    state: "queued" | "running" | "completed" | "error";
    outputs: Array<{ filename: string; url: string; kind: string }>;
    detail?: string;
  } | null>(null);
  const importRef = useRef<HTMLInputElement>(null);
  const loadWorkflows = useCallback(async () => {
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/design/comfyui/workflows`,
        { headers: authHeaders() },
      );
      if (!response.ok) return;
      const payload = (await response.json()) as {
        items?: Array<{
          id: string;
          name: string;
          description?: string;
          tags?: string[];
          source: "bundled" | "user";
        }>;
      };
      setRemoteWorkflows(
        (payload.items ?? []).map((item) => ({
          ...item,
          description: item.description ?? "",
          tags: item.tags ?? [],
        })),
      );
    } catch {
      // The static marketplace remains available when the local bridge is down.
    }
  }, []);
  const loadDependencies = useCallback(async () => {
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/design/comfyui/dependencies`,
        { headers: authHeaders() },
      );
      if (!response.ok) return;
      const payload = (await response.json()) as {
        detected?: boolean;
        path?: string | null;
        model_counts?: Record<string, number>;
        total_models?: number;
        custom_nodes?: string[];
        total_custom_nodes?: number;
        managed?: boolean;
        manager?: {
          installed?: boolean;
          home?: string;
          job?: {
            running?: boolean;
            state?: string;
            phase?: string;
            action?: string;
            node_id?: string | null;
            model_group?: string | null;
            error?: string | null;
          };
          runtime?: { version?: string | null; commit?: string | null };
          log_tail?: string[];
        };
      };
      setDependencies({
        detected: payload.detected === true,
        path: payload.path ?? null,
        modelCounts: payload.model_counts ?? {},
        totalModels: payload.total_models ?? 0,
        customNodes: payload.custom_nodes ?? [],
        totalCustomNodes: payload.total_custom_nodes ?? 0,
        managed: payload.managed === true,
        manager: {
          installed: payload.manager?.installed === true,
          home: payload.manager?.home ?? "",
          job: payload.manager?.job ?? {},
          runtime: payload.manager?.runtime,
          logTail: payload.manager?.log_tail ?? [],
        },
      });
    } catch {
      // Dependency inventory is optional and never blocks the workflow market.
    }
  }, []);
  const loadRegistryNodes = useCallback(async (search = "") => {
    setNodeLoading(true);
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.set("query", search.trim());
      const response = await fetch(
        `${getBackendBaseURL()}/api/design/comfyui/custom-nodes/registry?${params}`,
        { headers: authHeaders() },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as {
        items?: typeof registryNodes;
      };
      setRegistryNodes(payload.items ?? []);
    } catch {
      toast.error("暂时无法读取 Comfy Registry");
    } finally {
      setNodeLoading(false);
    }
  }, []);
  const loadLocalModels = useCallback(async () => {
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/design/comfyui/models`,
        { headers: authHeaders() },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as {
        items?: typeof localModels;
        backups?: typeof modelBackups;
        groups?: string[];
      };
      setLocalModels(payload.items ?? []);
      setModelBackups(payload.backups ?? []);
      if (payload.groups?.length) setModelGroups(payload.groups);
    } catch {
      // Model inventory remains optional until the managed engine exists.
    }
  }, []);
  useEffect(() => {
    void loadWorkflows();
    void loadDependencies();
  }, [loadDependencies, loadWorkflows]);
  useEffect(() => {
    if (!dependencies?.manager.job.running) return;
    const timer = window.setInterval(() => void loadDependencies(), 1400);
    return () => window.clearInterval(timer);
  }, [dependencies?.manager.job.running, loadDependencies]);
  useEffect(() => {
    if (dependencies?.manager.installed) {
      void loadRegistryNodes();
      void loadLocalModels();
    }
  }, [dependencies?.manager.installed, loadLocalModels, loadRegistryNodes]);
  useEffect(() => {
    if (
      dependencies?.manager.job.state === "completed" &&
      dependencies.manager.job.action?.startsWith("node_")
    ) {
      void loadRegistryNodes();
      void loadDependencies();
    }
  }, [
    dependencies?.manager.job.action,
    dependencies?.manager.job.state,
    loadDependencies,
    loadRegistryNodes,
  ]);
  useEffect(() => {
    if (
      dependencies?.manager.job.state === "completed" &&
      dependencies.manager.job.action === "model_download"
    ) {
      void loadLocalModels();
      void loadDependencies();
    }
  }, [
    dependencies?.manager.job.action,
    dependencies?.manager.job.state,
    loadDependencies,
    loadLocalModels,
  ]);
  const catalogWorkflows = useMemo(() => {
    const remoteById = new Map(remoteWorkflows.map((item) => [item.id, item]));
    const market = COMFY_WORKFLOWS.map((item) => {
      const remote = remoteById.get(item.id);
      return {
        ...item,
        description: remote?.description || item.description,
        tags: [...(remote?.tags?.length ? remote.tags : item.tags)],
        availability:
          remote?.source === "user" ? ("user" as const) : item.availability,
        source: remote?.source,
      };
    });
    const known = new Set<string>(market.map((item) => item.id));
    const user = remoteWorkflows
      .filter((item) => item.source === "user" && !known.has(item.id))
      .map((item) => ({
        id: item.id,
        title: item.name,
        description: item.description || "用户导入的 ComfyUI 工作流",
        tags: item.tags,
        availability: "user" as const,
        source: item.source,
      }));
    return [...market, ...user];
  }, [remoteWorkflows]);
  const needle = query.trim().toLowerCase();
  const visibleWorkflows = catalogWorkflows.filter(
    (workflow) =>
      (tab === "market" || workflow.source === "user") &&
      (!needle ||
        `${workflow.title} ${workflow.description} ${workflow.tags.join(" ")}`
          .toLowerCase()
          .includes(needle)),
  );
  const selectedWorkflow = selectedWorkflowId
    ? (catalogWorkflows.find(
        (workflow) => workflow.id === selectedWorkflowId,
      ) ?? null)
    : null;
  useEffect(() => {
    if (!selectedWorkflowId) {
      setSelectedWorkflowDetail(null);
      return;
    }
    const controller = new AbortController();
    void fetch(
      `${getBackendBaseURL()}/api/design/comfyui/workflows/${encodeURIComponent(selectedWorkflowId)}`,
      { headers: authHeaders(), signal: controller.signal },
    )
      .then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return (await response.json()) as {
          workflow?: Record<
            string,
            { class_type?: string; inputs?: Record<string, unknown> }
          >;
        };
      })
      .then((payload) => {
        setSelectedWorkflowDetail({ workflow: payload.workflow ?? {} });
      })
      .catch((error: unknown) => {
        if ((error as { name?: string }).name !== "AbortError") {
          setSelectedWorkflowDetail(null);
        }
      });
    return () => controller.abort();
  }, [selectedWorkflowId]);
  const selectedWorkflowNodes = Object.values(
    selectedWorkflowDetail?.workflow ?? {},
  );
  const selectedWorkflowNodeTypes = Array.from(
    new Set(
      selectedWorkflowNodes
        .map((node) => node.class_type?.trim())
        .filter((value): value is string => Boolean(value)),
    ),
  );
  const selectedWorkflowResources = selectedWorkflowNodes.flatMap((node) =>
    Object.entries(node.inputs ?? {})
      .filter(
        ([key, value]) =>
          typeof value === "string" &&
          /(?:ckpt|checkpoint|vae|lora|control.*net|unet|clip|image|video|audio).*name|^(?:image|video|audio)$/i.test(
            key,
          ),
      )
      .map(([key, value]) => ({
        key,
        value: String(value),
        nodeType: node.class_type || "ComfyUI 节点",
      })),
  );
  const check = async () => {
    setChecking(true);
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/design/comfyui/status`,
        {
          headers: authHeaders(),
          signal: AbortSignal.timeout(2800),
        },
      );
      const payload = (await response.json()) as {
        online?: boolean;
        process?: { owned?: boolean; running?: boolean };
      };
      setOnline(response.ok && payload.online === true);
      setComfyProcess({
        owned: payload.process?.owned === true,
        running: payload.process?.running === true,
      });
    } catch {
      setOnline(false);
    } finally {
      void loadDependencies();
      setChecking(false);
    }
  };
  const controlLocalService = async (action: "start" | "stop") => {
    setChecking(true);
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/design/comfyui/${action}`,
        { method: "POST", headers: authHeaders() },
      );
      const payload = (await response.json()) as {
        ok?: boolean;
        state?: string;
        process?: { owned?: boolean; running?: boolean };
      };
      if (!response.ok || !payload.ok) {
        throw new Error(payload.state || `HTTP ${response.status}`);
      }
      setComfyProcess({
        owned: payload.process?.owned === true,
        running: payload.process?.running === true,
      });
      if (action === "start") {
        toast.success("ComfyUI 正在启动");
        window.setTimeout(() => void check(), 900);
      } else {
        setOnline(false);
        toast.success("已停止由 Octopus 启动的 ComfyUI");
      }
    } catch {
      toast.error(
        action === "start"
          ? "未能启动，请确认本地 ComfyUI 安装完整"
          : "该服务不是由 Octopus 启动，无法代为停止",
      );
    } finally {
      setChecking(false);
    }
  };
  const controlManagedComfy = async (
    action: "install" | "update" | "manager/cancel",
  ) => {
    setChecking(true);
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/design/comfyui/${action}`,
        { method: "POST", headers: authHeaders() },
      );
      const payload = (await response.json()) as {
        ok?: boolean;
        state?: string;
        detail?: string;
      };
      if (!response.ok || !payload.ok)
        throw new Error(payload.detail || payload.state || "操作失败");
      await loadDependencies();
      if (action === "manager/cancel") {
        toast.success("已取消 ComfyUI 安装任务");
      } else {
        toast.success(
          action === "install"
            ? "开始安装 ComfyUI；不会自动下载模型权重"
            : "开始更新 ComfyUI",
        );
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "ComfyUI 操作失败");
    } finally {
      setChecking(false);
    }
  };
  const controlCustomNode = async (
    action: "install" | "update" | "uninstall" | "rollback",
    nodeId: string,
    backupId?: string,
  ) => {
    const warning =
      action === "install"
        ? "该扩展来自 Comfy Registry，安装时可能执行第三方依赖脚本。确认安装？"
        : action === "update"
          ? "更新前会自动备份当前版本；扩展依赖也可能变化。确认更新？"
          : action === "uninstall"
            ? "扩展会移入可恢复区，不会永久删除。确认卸载？"
            : "当前扩展会先备份，再恢复到所选历史版本。确认回滚？";
    if (!window.confirm(warning)) return;
    setNodeLoading(true);
    try {
      const base = `${getBackendBaseURL()}/api/design/comfyui/custom-nodes`;
      let response: Response;
      if (action === "install" || action === "update") {
        response = await fetch(`${base}/${action}`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({ node_id: nodeId }),
        });
      } else if (action === "uninstall") {
        response = await fetch(`${base}/${encodeURIComponent(nodeId)}`, {
          method: "DELETE",
          headers: authHeaders(),
        });
      } else {
        response = await fetch(
          `${base}/${encodeURIComponent(nodeId)}/rollback`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body: JSON.stringify({ backup_id: backupId }),
          },
        );
      }
      const payload = (await response.json()) as {
        ok?: boolean;
        state?: string;
        detail?: string;
      };
      if (!response.ok || !payload.ok)
        throw new Error(payload.detail || payload.state || "扩展操作失败");
      await loadDependencies();
      await loadRegistryNodes(nodeQuery);
      toast.success(
        action === "install"
          ? "扩展开始安装"
          : action === "update"
            ? "扩展开始更新"
            : action === "uninstall"
              ? "扩展已移入可恢复区"
              : "扩展已回滚",
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "扩展操作失败");
    } finally {
      setNodeLoading(false);
    }
  };
  const controlModel = async (
    action: "download" | "remove" | "restore",
    payload?: { group?: string; name?: string; backupId?: string },
  ) => {
    const warning =
      action === "download"
        ? `将从公开来源下载模型到 ${modelGroup}。模型通常体积较大，确认开始？`
        : action === "remove"
          ? "模型会移入可恢复区，不会永久删除。确认移除？"
          : "确认恢复该模型？若目标位置已有同名模型，恢复会被拒绝。";
    if (!window.confirm(warning)) return;
    setModelLoading(true);
    try {
      const body =
        action === "download"
          ? { url: modelUrl.trim(), group: modelGroup }
          : action === "remove"
            ? { group: payload?.group, name: payload?.name }
            : { backup_id: payload?.backupId };
      const response = await fetch(
        `${getBackendBaseURL()}/api/design/comfyui/models/${action}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify(body),
        },
      );
      const result = (await response.json()) as {
        ok?: boolean;
        state?: string;
        detail?: string;
      };
      if (!response.ok || !result.ok)
        throw new Error(result.detail || result.state || "模型操作失败");
      if (action === "download") {
        setModelUrl("");
        await loadDependencies();
        toast.success("模型下载已开始，可在后台继续");
      } else {
        await loadLocalModels();
        await loadDependencies();
        toast.success(
          action === "remove" ? "模型已移入可恢复区" : "模型已恢复",
        );
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "模型操作失败");
    } finally {
      setModelLoading(false);
    }
  };
  const importWorkflow = async (file: File) => {
    try {
      const parsed = JSON.parse(await file.text()) as Record<string, unknown>;
      const workflow =
        parsed.workflow && typeof parsed.workflow === "object"
          ? (parsed.workflow as Record<string, unknown>)
          : parsed;
      const response = await fetch(
        `${getBackendBaseURL()}/api/design/comfyui/workflows/import`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({
            name: file.name.replace(/\.json$/i, ""),
            workflow,
          }),
        },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await loadWorkflows();
      setTab("mine");
      toast.success("ComfyUI 工作流已导入");
    } catch {
      toast.error("工作流 JSON 无法导入，请检查文件格式");
    }
  };
  const runWorkflow = async (workflowId: string) => {
    setRunState({
      workflowId,
      promptId: "",
      state: "queued",
      outputs: [],
    });
    try {
      const response = await fetch(
        `${getBackendBaseURL()}/api/design/comfyui/queue`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({ workflow_id: workflowId }),
        },
      );
      const payload = (await response.json()) as {
        prompt_id?: string;
        detail?: string;
      };
      if (!response.ok || !payload.prompt_id)
        throw new Error(payload.detail || `HTTP ${response.status}`);
      setRunState({
        workflowId,
        promptId: payload.prompt_id,
        state: "running",
        outputs: [],
      });
    } catch (error) {
      setRunState({
        workflowId,
        promptId: "",
        state: "error",
        outputs: [],
        detail: error instanceof Error ? error.message : "工作流运行失败",
      });
    }
  };
  useEffect(() => {
    if (!runState?.promptId || runState.state !== "running") return;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(
          `${getBackendBaseURL()}/api/design/comfyui/history/${encodeURIComponent(runState.promptId)}`,
          { headers: authHeaders() },
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = (await response.json()) as {
          state?: "pending" | "running" | "completed";
          outputs?: Array<{ filename: string; url: string; kind: string }>;
        };
        if (cancelled) return;
        setRunState((current) =>
          current?.promptId === runState.promptId
            ? {
                ...current,
                state: payload.state === "completed" ? "completed" : "running",
                outputs: payload.outputs ?? [],
              }
            : current,
        );
      } catch (error) {
        if (!cancelled)
          setRunState((current) =>
            current?.promptId === runState.promptId
              ? {
                  ...current,
                  state: "error",
                  detail:
                    error instanceof Error ? error.message : "结果查询失败",
                }
              : current,
          );
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [runState?.promptId, runState?.state]);
  return (
    <div className="h-full overflow-y-auto bg-background px-11 py-9">
      <div className="mx-auto max-w-[1120px]">
        <div className="flex items-start">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              ComfyUI 工作流
            </h1>
            <p className="mt-1.5 text-xs text-muted-foreground">
              支持本地部署，可手动运行，也可作为画布节点由 Agent 调用
            </p>
          </div>
        </div>
        <div className="mt-7 flex gap-2">
          <Button
            className="h-9 rounded-[10px] bg-foreground px-4 text-[11px] text-background"
            onClick={() => importRef.current?.click()}
          >
            <PlusIcon className="mr-1.5 size-3.5" />
            导入/新建工作流
          </Button>
          <input
            ref={importRef}
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void importWorkflow(file);
              event.target.value = "";
            }}
          />
          <Button
            variant="outline"
            className="h-9 rounded-[10px] px-4 text-[11px]"
            onClick={() => onUse("blank", "空白 ComfyUI 工作流")}
          >
            <PlusIcon className="mr-1.5 size-4" />
            空白工作流
          </Button>
          <Button
            variant="outline"
            className="h-9 rounded-[10px] px-4 text-[11px]"
            onClick={() =>
              toast.info(
                "可从 Comfy Registry 安装节点，也可导入开源 workflow JSON",
              )
            }
          >
            <BookOpenIcon className="mr-1.5 size-4" />
            探索开源
          </Button>
          <Button
            variant="ghost"
            className="ml-auto h-9 rounded-[10px] px-3 text-[10px] text-muted-foreground"
            onClick={() => setEnvironmentOpen((value) => !value)}
          >
            <span
              className={cn(
                "mr-1.5 size-1.5 rounded-full",
                online === true
                  ? "bg-emerald-500"
                  : online === false
                    ? "bg-red-500"
                    : "bg-zinc-400",
              )}
            />
            <Settings2Icon className="mr-1.5 size-4" />
            本地环境
            <ChevronDownIcon
              className={cn(
                "ml-1 size-3.5 transition-transform",
                environmentOpen && "rotate-180",
              )}
            />
          </Button>
          {environmentOpen ? (
            <>
              <Button
                variant="outline"
                className="rounded-xl"
                onClick={check}
                disabled={checking}
              >
                {checking ? (
                  <Loader2Icon className="mr-1.5 size-4 animate-spin" />
                ) : (
                  <Redo2Icon className="mr-1.5 size-4" />
                )}
                检测本地服务
              </Button>
              {dependencies?.detected && online !== true ? (
                <Button
                  variant="outline"
                  className="rounded-xl"
                  onClick={() => void controlLocalService("start")}
                  disabled={checking || comfyProcess.running}
                >
                  <CirclePlayIcon className="mr-1.5 size-4" />
                  启动本地服务
                </Button>
              ) : null}
              {dependencies &&
              !dependencies.detected &&
              !dependencies.manager.job.running ? (
                <Button
                  variant="outline"
                  className="rounded-xl border-violet-200 text-violet-700"
                  onClick={() => void controlManagedComfy("install")}
                  disabled={checking}
                >
                  <ArchiveIcon className="mr-1.5 size-4" />
                  安装本地引擎
                </Button>
              ) : null}
              {dependencies?.manager.installed &&
              !dependencies.manager.job.running ? (
                <Button
                  variant="ghost"
                  className="rounded-xl text-muted-foreground"
                  onClick={() => void controlManagedComfy("update")}
                  disabled={checking || online === true}
                  title={online === true ? "请先停止本地服务再更新" : undefined}
                >
                  <Redo2Icon className="mr-1.5 size-4" />
                  更新引擎
                </Button>
              ) : null}
              {dependencies?.manager.job.running ? (
                <Button
                  variant="ghost"
                  className="rounded-xl text-amber-700"
                  onClick={() => void controlManagedComfy("manager/cancel")}
                  disabled={checking}
                >
                  <XIcon className="mr-1.5 size-4" />
                  取消
                  {dependencies.manager.job.action === "update" ||
                  dependencies.manager.job.action === "node_update"
                    ? "更新"
                    : dependencies.manager.job.action === "model_download"
                      ? "下载"
                      : "安装"}
                </Button>
              ) : null}
              {online === true && comfyProcess.owned ? (
                <Button
                  variant="ghost"
                  className="rounded-xl text-muted-foreground"
                  onClick={() => void controlLocalService("stop")}
                  disabled={checking}
                >
                  <XIcon className="mr-1.5 size-4" />
                  停止服务
                </Button>
              ) : null}
            </>
          ) : null}
        </div>
        {environmentOpen && dependencies ? (
          <div className="mt-4 grid grid-cols-[1.35fr_0.65fr_0.65fr] overflow-hidden rounded-2xl border bg-muted/20">
            <div className="min-w-0 px-4 py-3.5">
              <div className="flex items-center gap-2 text-[11px] font-medium">
                <FolderIcon className="size-3.5 text-sky-600" />
                本地创作环境
              </div>
              <p
                className="mt-1.5 truncate text-[10px] text-muted-foreground"
                title={dependencies.path ?? undefined}
              >
                {dependencies.detected
                  ? dependencies.path
                  : "尚未找到 ComfyUI 目录，工作流市场仍可浏览"}
              </p>
            </div>
            <div className="border-l px-4 py-3.5">
              <div className="text-lg font-semibold tabular-nums">
                {dependencies.totalModels}
              </div>
              <div className="mt-0.5 text-[9px] text-muted-foreground">
                本地模型
              </div>
            </div>
            <div className="border-l px-4 py-3.5">
              <div className="text-lg font-semibold tabular-nums">
                {dependencies.totalCustomNodes}
              </div>
              <div className="mt-0.5 text-[9px] text-muted-foreground">
                节点扩展
              </div>
            </div>
          </div>
        ) : null}
        {environmentOpen &&
          (dependencies?.manager.job.running ||
          dependencies?.manager.job.state === "failed" ? (
            <div
              className={cn(
                "mt-3 rounded-xl border px-4 py-3 text-[10px]",
                dependencies.manager.job.state === "failed"
                  ? "border-red-200 bg-red-50 text-red-800"
                  : "border-violet-200 bg-violet-50 text-violet-800",
              )}
            >
              <div className="flex items-center gap-2 font-medium">
                {dependencies.manager.job.running ? (
                  <Loader2Icon className="size-3.5 animate-spin" />
                ) : null}
                {dependencies.manager.job.state === "failed"
                  ? "ComfyUI 安装未完成"
                  : dependencies.manager.job.phase === "creating_runtime"
                    ? "正在创建隔离运行环境"
                    : dependencies.manager.job.phase === "installing_cli"
                      ? "正在安装官方管理工具"
                      : dependencies.manager.job.action === "update"
                        ? "正在更新 ComfyUI"
                        : dependencies.manager.job.action === "node_update"
                          ? `正在更新扩展 ${dependencies.manager.job.node_id || ""}`
                          : dependencies.manager.job.action === "node_install"
                            ? `正在安装扩展 ${dependencies.manager.job.node_id || ""}`
                            : dependencies.manager.job.action ===
                                "model_download"
                              ? `正在下载模型到 ${dependencies.manager.job.model_group || "models"}`
                              : "正在下载并安装 ComfyUI"}
              </div>
              <p className="mt-1 opacity-80">
                {dependencies.manager.job.error ||
                  "可以离开此页面，安装任务会在后台继续；模型权重仍由你自行选择。"}
              </p>
            </div>
          ) : null)}
        {environmentOpen && dependencies?.manager.installed ? (
          <section className="mt-5 rounded-2xl border border-border-default bg-background p-4">
            <div className="flex items-start gap-3">
              <div>
                <h2 className="text-[13px] font-semibold">模型中心</h2>
                <p className="mt-0.5 text-[9px] text-muted-foreground">
                  仅支持 Hugging Face / Civitai 公开链接 · 每个模型单独授权
                </p>
              </div>
              <span className="flex-1" />
              <span className="rounded-md bg-muted px-2 py-1 text-[9px] text-muted-foreground">
                {localModels.length} 个模型 ·{" "}
                {formatModelSize(
                  localModels.reduce((sum, model) => sum + model.size_bytes, 0),
                )}
              </span>
            </div>
            <form
              className="mt-3 grid grid-cols-[minmax(0,1fr)_150px_auto] gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (modelUrl.trim()) void controlModel("download");
              }}
            >
              <Input
                value={modelUrl}
                onChange={(event) => setModelUrl(event.target.value)}
                placeholder="粘贴 Hugging Face 文件链接或 Civitai 模型链接"
                className="h-9 rounded-lg text-[10px]"
              />
              <select
                value={modelGroup}
                onChange={(event) => setModelGroup(event.target.value)}
                className="h-9 rounded-lg border border-input bg-background px-2 text-[10px] outline-none"
                aria-label="模型目录"
              >
                {modelGroups.map((group) => (
                  <option key={group} value={group}>
                    {group}
                  </option>
                ))}
              </select>
              <Button
                type="submit"
                className="h-9 rounded-lg px-3 text-[10px]"
                disabled={
                  modelLoading ||
                  !modelUrl.trim() ||
                  online === true ||
                  dependencies.manager.job.running
                }
              >
                {modelLoading ? (
                  <Loader2Icon className="mr-1 size-3.5 animate-spin" />
                ) : (
                  <ArchiveIcon className="mr-1 size-3.5" />
                )}
                下载模型
              </Button>
            </form>
            <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
              {localModels.map((model) => (
                <div
                  key={model.id}
                  className="flex min-w-0 items-center gap-2 rounded-xl border border-border-subtle bg-muted/15 px-3 py-2.5"
                >
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-sky-100 text-sky-700">
                    <ArchiveIcon className="size-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[10px] font-medium">
                      {model.name}
                    </div>
                    <div className="mt-0.5 text-[8px] text-muted-foreground">
                      {model.group} · {formatModelSize(model.size_bytes)}
                    </div>
                  </div>
                  <button
                    onClick={() =>
                      void controlModel("remove", {
                        group: model.group,
                        name: model.name,
                      })
                    }
                    disabled={modelLoading || online === true}
                    className="rounded px-2 py-1 text-[9px] text-red-600 hover:bg-red-50 disabled:opacity-40"
                  >
                    移除
                  </button>
                </div>
              ))}
            </div>
            {modelBackups.length > 0 ? (
              <div className="mt-3 border-t border-border-subtle pt-3">
                <div className="mb-2 text-[9px] font-medium text-muted-foreground">
                  可恢复模型
                </div>
                <div className="flex flex-wrap gap-2">
                  {modelBackups.map((backup) => (
                    <button
                      key={backup.id}
                      onClick={() =>
                        void controlModel("restore", { backupId: backup.id })
                      }
                      disabled={modelLoading || online === true}
                      className="rounded-lg border px-2.5 py-1.5 text-[9px] hover:bg-muted disabled:opacity-40"
                    >
                      恢复 {backup.name} · {formatModelSize(backup.size_bytes)}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </section>
        ) : null}
        {environmentOpen && dependencies?.manager.installed ? (
          <section className="mt-5 rounded-2xl border border-border-default bg-background p-4">
            <div className="flex items-center gap-3">
              <div>
                <h2 className="text-[13px] font-semibold">节点扩展</h2>
                <p className="mt-0.5 text-[9px] text-muted-foreground">
                  来自官方 Comfy Registry · 修改前需停止本地服务
                </p>
              </div>
              <span className="flex-1" />
              <form
                className="flex w-72 gap-1.5"
                onSubmit={(event) => {
                  event.preventDefault();
                  void loadRegistryNodes(nodeQuery);
                }}
              >
                <Input
                  value={nodeQuery}
                  onChange={(event) => setNodeQuery(event.target.value)}
                  placeholder="输入 Registry ID 精确搜索"
                  className="h-8 rounded-lg text-[10px]"
                />
                <Button
                  type="submit"
                  variant="outline"
                  size="sm"
                  className="h-8 rounded-lg px-2.5"
                  disabled={nodeLoading}
                >
                  {nodeLoading ? (
                    <Loader2Icon className="size-3.5 animate-spin" />
                  ) : (
                    <SearchIcon className="size-3.5" />
                  )}
                </Button>
              </form>
            </div>
            <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
              {registryNodes.map((node) => (
                <article
                  key={node.id}
                  className="rounded-xl border border-border-subtle bg-muted/15 p-3"
                >
                  <div className="flex items-start gap-2">
                    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-violet-100 text-violet-700">
                      <PuzzleIcon className="size-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-[11px] font-semibold">
                          {node.name}
                        </span>
                        {node.installed ? (
                          <span className="shrink-0 rounded bg-emerald-100 px-1 py-0.5 text-[8px] text-emerald-700">
                            已安装
                          </span>
                        ) : null}
                      </div>
                      <div className="mt-0.5 truncate text-[8px] text-muted-foreground">
                        {node.id} · v{node.version || "latest"}
                      </div>
                    </div>
                  </div>
                  <p className="mt-2 line-clamp-2 min-h-7 text-[9px] leading-3.5 text-muted-foreground">
                    {node.description || "ComfyUI 节点扩展"}
                  </p>
                  <div className="mt-2 flex items-center gap-1.5 text-[8px] text-muted-foreground">
                    <span>{node.downloads.toLocaleString()} 下载</span>
                    <span>★ {node.stars.toLocaleString()}</span>
                    <span className="flex-1" />
                    {node.installed ? (
                      <>
                        {node.backups.length > 0 ? (
                          <button
                            onClick={() =>
                              void controlCustomNode(
                                "rollback",
                                node.id,
                                node.backups[0]?.id,
                              )
                            }
                            disabled={nodeLoading || online === true}
                            className="rounded px-1.5 py-1 hover:bg-muted disabled:opacity-40"
                          >
                            回滚
                          </button>
                        ) : null}
                        <button
                          onClick={() =>
                            void controlCustomNode("update", node.id)
                          }
                          disabled={nodeLoading || online === true}
                          className="rounded px-1.5 py-1 hover:bg-muted disabled:opacity-40"
                        >
                          更新
                        </button>
                        <button
                          onClick={() =>
                            void controlCustomNode("uninstall", node.id)
                          }
                          disabled={nodeLoading || online === true}
                          className="rounded px-1.5 py-1 text-red-600 hover:bg-red-50 disabled:opacity-40"
                        >
                          卸载
                        </button>
                      </>
                    ) : (
                      <button
                        onClick={() =>
                          void controlCustomNode("install", node.id)
                        }
                        disabled={nodeLoading || online === true}
                        className="rounded-md bg-foreground px-2 py-1 text-background disabled:opacity-40"
                      >
                        安装
                      </button>
                    )}
                  </div>
                </article>
              ))}
            </div>
          </section>
        ) : null}
        {runState ? (
          <div
            className={cn(
              "mt-4 rounded-xl border px-4 py-3 text-xs",
              runState.state === "error"
                ? "border-red-200 bg-red-50 text-red-800"
                : runState.state === "completed"
                  ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                  : "border-violet-200 bg-violet-50 text-violet-800",
            )}
          >
            <div className="flex items-center gap-2 font-medium">
              {runState.state === "queued" || runState.state === "running" ? (
                <Loader2Icon className="size-3.5 animate-spin" />
              ) : runState.state === "completed" ? (
                <CheckIcon className="size-3.5" />
              ) : (
                <XIcon className="size-3.5" />
              )}
              {runState.state === "queued"
                ? "正在提交工作流"
                : runState.state === "running"
                  ? "ComfyUI 正在生成"
                  : runState.state === "completed"
                    ? `生成完成 · ${runState.outputs.length} 个输出`
                    : `运行失败 · ${runState.detail || "请检查本地服务和模型"}`}
            </div>
            {runState.outputs.length ? (
              <div className="mt-3 flex gap-2 overflow-x-auto">
                {runState.outputs.map((output) => (
                  <a
                    key={`${output.kind}:${output.filename}`}
                    href={output.url}
                    target="_blank"
                    rel="noreferrer"
                    className="block shrink-0 overflow-hidden rounded-lg border bg-background"
                  >
                    {output.kind === "images" ? (
                      <img
                        src={output.url}
                        alt={output.filename}
                        className="h-24 w-32 object-cover"
                      />
                    ) : (
                      <span className="block max-w-40 truncate px-3 py-2">
                        {output.filename}
                      </span>
                    )}
                  </a>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
        <div className="mt-8 flex items-center border-t border-border-subtle pt-3">
          <button
            onClick={() => setTab("market")}
            className={cn(
              "relative h-9 px-0 text-[12px] font-medium",
              tab === "market"
                ? "text-foreground after:absolute after:bottom-0 after:left-0 after:right-0 after:h-0.5 after:bg-foreground"
                : "text-muted-foreground",
            )}
          >
            精选工作流
          </button>
          <button
            onClick={() => setTab("mine")}
            className={cn(
              "relative ml-7 h-9 px-0 text-[12px] font-medium",
              tab === "mine"
                ? "text-foreground after:absolute after:bottom-0 after:left-0 after:right-0 after:h-0.5 after:bg-foreground"
                : "text-muted-foreground",
            )}
          >
            我的工作流
          </button>
          <span className="flex-1" />
          <div className="relative w-60">
            <SearchIcon className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-9 rounded-[10px] pl-9 text-[11px]"
              placeholder="搜索工作流"
            />
          </div>
          {selectedWorkflow ? (
            <Button
              variant="ghost"
              size="icon"
              className="ml-2 size-9 rounded-xl bg-foreground text-background hover:bg-foreground/85 hover:text-background"
              onClick={() => setSelectedWorkflowId(null)}
              aria-label="退出详情"
            >
              <XIcon className="size-4" />
            </Button>
          ) : null}
        </div>
        {selectedWorkflow ? (
          <div className="mt-6 grid min-h-[520px] grid-cols-[minmax(0,1fr)_240px] gap-8">
            <section className="min-w-0">
              <h2 className="text-[20px] font-semibold leading-7">
                {selectedWorkflow.title}
              </h2>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {selectedWorkflow.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-md bg-muted px-2 py-1 text-[9px] text-muted-foreground"
                  >
                    {tag}
                  </span>
                ))}
              </div>
              <p className="mt-7 max-w-2xl whitespace-pre-line text-[12px] leading-6 text-muted-foreground">
                {selectedWorkflow.description}
                {"\n"}
                {selectedWorkflow.availability === "dependency"
                  ? "这是能力目录，需要先安装页面列出的模型或扩展，Octopus 不会静默下载大模型。"
                  : "工作流可在本机手动运行，也可加入画布交给 Agent 调用。模型和输入文件始终由你选择。"}
              </p>
              <Button
                className="mt-7 h-11 w-full max-w-xl rounded-xl bg-violet-600 text-white hover:bg-violet-700"
                disabled={selectedWorkflow.availability === "dependency"}
                onClick={() =>
                  onUse(selectedWorkflow.id, selectedWorkflow.title)
                }
              >
                {selectedWorkflow.availability === "dependency"
                  ? "缺少本地依赖"
                  : "加入画布"}
              </Button>
              <div className="mt-7 max-w-xl rounded-2xl border border-border-default p-4">
                <div className="flex items-center gap-2">
                  <h3 className="text-[12px] font-semibold">资源文件</h3>
                  {selectedWorkflowDetail ? (
                    <span className="text-[9px] text-muted-foreground">
                      {selectedWorkflowNodes.length} 个节点 ·{" "}
                      {selectedWorkflowResources.length + 1} 个文件/输入
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 text-[9px] text-muted-foreground">
                  工作流文件以及运行时需要由用户选择的本地资源
                </p>
                <div className="mt-3 space-y-2 text-[10px]">
                  <div className="flex items-center gap-2 rounded-lg bg-muted/45 px-3 py-2">
                    <WorkflowIcon className="size-3.5" />
                    <span className="min-w-0 flex-1 truncate">
                      {selectedWorkflow.id}.json
                    </span>
                    <span className="text-muted-foreground">工作流</span>
                  </div>
                  {selectedWorkflowResources.length ? (
                    selectedWorkflowResources.map((resource) => (
                      <div
                        key={`${resource.nodeType}:${resource.key}:${resource.value}`}
                        className="flex items-center gap-2 rounded-lg bg-muted/45 px-3 py-2"
                      >
                        <ArchiveIcon className="size-3.5" />
                        <span className="min-w-0 flex-1 truncate">
                          {resource.value}
                        </span>
                        <span className="shrink-0 text-muted-foreground">
                          {resource.key}
                        </span>
                      </div>
                    ))
                  ) : (
                    <div className="flex items-center gap-2 rounded-lg bg-muted/45 px-3 py-2">
                      <ArchiveIcon className="size-3.5" />
                      <span className="min-w-0 flex-1 truncate">
                        {selectedWorkflow.availability === "dependency"
                          ? selectedWorkflow.tags.join(" · ")
                          : "未声明额外模型文件"}
                      </span>
                      <span className="text-muted-foreground">本地资源</span>
                    </div>
                  )}
                </div>
                {selectedWorkflowNodeTypes.length ? (
                  <div className="mt-3 flex flex-wrap gap-1">
                    {selectedWorkflowNodeTypes.map((nodeType) => (
                      <span
                        key={nodeType}
                        className="rounded bg-muted px-1.5 py-1 text-[8px] text-muted-foreground"
                      >
                        {nodeType}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
              <div className="mt-5 max-w-xl">
                <h3 className="text-[12px] font-semibold">来源与许可</h3>
                <div className="mt-2 rounded-xl border border-border-default px-3 py-2.5 text-[10px]">
                  <div className="font-medium">Octopus 原创工作流模板</div>
                  <div className="mt-0.5 text-muted-foreground">
                    Apache-2.0 · 兼容 ComfyUI 工作流格式
                  </div>
                </div>
              </div>
            </section>
            <aside className="space-y-2">
              {visibleWorkflows.map((workflow) => (
                <button
                  key={workflow.id}
                  onClick={() => setSelectedWorkflowId(workflow.id)}
                  className={cn(
                    "w-full rounded-xl border p-3 text-left transition hover:bg-muted/50",
                    workflow.id === selectedWorkflow.id
                      ? "border-violet-300 bg-violet-50/60"
                      : "border-border-subtle",
                  )}
                >
                  <div className="truncate text-[10px] font-semibold">
                    {workflow.title}
                  </div>
                  <p className="mt-1 line-clamp-2 text-[9px] leading-4 text-muted-foreground">
                    {workflow.description}
                  </p>
                </button>
              ))}
            </aside>
          </div>
        ) : (
          <div className="mt-5 grid grid-cols-2 gap-5 md:grid-cols-4">
            {visibleWorkflows.map((workflow, index) => (
              <div
                key={workflow.id}
                className={cn(
                  "group overflow-hidden rounded-[12px] border border-border-subtle bg-background text-left transition",
                  workflow.availability !== "dependency"
                    ? "hover:-translate-y-0.5 hover:shadow-lg"
                    : "opacity-75 hover:border-amber-300",
                )}
              >
                <button
                  type="button"
                  onClick={() => setSelectedWorkflowId(workflow.id)}
                  className="block w-full text-left"
                >
                  <div
                    className={cn(
                      "relative h-28 overflow-hidden",
                      index % 4 === 0
                        ? "bg-[radial-gradient(circle_at_68%_28%,rgba(255,255,255,.9),transparent_18%),radial-gradient(circle_at_35%_70%,#b7d7ff,transparent_36%),linear-gradient(135deg,#4d6687,#101827)]"
                        : index % 4 === 1
                          ? "bg-[radial-gradient(circle_at_28%_30%,#dfd5ff,transparent_28%),radial-gradient(circle_at_72%_75%,#8ca6ff,transparent_35%),linear-gradient(135deg,#1f2937,#63558d)]"
                          : index % 4 === 2
                            ? "bg-[radial-gradient(circle_at_65%_22%,#ffe7c2,transparent_24%),radial-gradient(circle_at_28%_80%,#9fd1bb,transparent_38%),linear-gradient(135deg,#263b39,#80714d)]"
                            : "bg-[radial-gradient(circle_at_24%_35%,#ffc7df,transparent_25%),radial-gradient(circle_at_78%_75%,#bc9cff,transparent_35%),linear-gradient(135deg,#3b304f,#76647b)]",
                    )}
                  >
                    <div className="absolute inset-0 bg-[linear-gradient(115deg,transparent_20%,rgba(255,255,255,.22)_21%,transparent_22%,transparent_48%,rgba(255,255,255,.12)_49%,transparent_50%)] opacity-70" />
                    <img
                      src={
                        COMFY_WORKFLOW_COVERS[
                          index % COMFY_WORKFLOW_COVERS.length
                        ]
                      }
                      alt=""
                      className="absolute inset-0 size-full object-cover opacity-90 transition duration-300 group-hover:scale-[1.03]"
                    />
                    <div className="absolute inset-0 bg-gradient-to-r from-black/45 via-black/10 to-transparent" />
                    <div className="absolute left-4 top-4 text-white drop-shadow-sm">
                      <div className="text-[8px] font-semibold tracking-[0.22em] text-white/70">
                        OCTOPUS FLOW
                      </div>
                      <div className="mt-1.5 max-w-36 text-[15px] font-semibold leading-[18px]">
                        {workflow.title}
                      </div>
                    </div>
                    <span className="absolute bottom-3 left-4 rounded-full border border-white/25 bg-black/20 px-2 py-1 text-[7px] font-medium text-white/85 backdrop-blur-sm">
                      {workflow.tags[0] || "WORKFLOW"}
                    </span>
                    <WorkflowIcon className="absolute bottom-3 right-3 size-8 text-white/65 transition-transform group-hover:scale-110" />
                    <span className="absolute inset-0 flex items-center justify-center gap-1.5 bg-black/40 opacity-0 backdrop-blur-[1px] transition-opacity group-hover:opacity-100">
                      <span
                        className={cn(
                          "rounded-lg px-3 py-1.5 text-[9px] font-medium",
                          workflow.availability === "dependency"
                            ? "bg-white/85 text-zinc-500"
                            : "bg-white text-zinc-950",
                        )}
                      >
                        {workflow.availability === "dependency"
                          ? "查看依赖"
                          : "查看详情"}
                      </span>
                    </span>
                  </div>
                  <div className="p-3 pb-2">
                    <div className="flex items-center gap-2 text-[12px] font-semibold">
                      <span className="min-w-0 flex-1 truncate">
                        {workflow.title}
                      </span>
                      <span
                        className={cn(
                          "shrink-0 rounded-full px-1.5 py-0.5 text-[8px] font-medium",
                          workflow.availability !== "dependency"
                            ? "bg-emerald-50 text-emerald-700"
                            : "bg-amber-50 text-amber-700",
                        )}
                      >
                        {workflow.availability === "bundled"
                          ? "已内置"
                          : workflow.availability === "user"
                            ? "已导入"
                            : "需依赖"}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-muted-foreground">
                      {workflow.description}
                    </p>
                    <div className="mt-2 flex items-center text-[8px] text-muted-foreground">
                      <span className="rounded bg-muted px-1.5 py-0.5">
                        {workflow.source === "user"
                          ? "用户导入"
                          : "Octopus 原创"}
                      </span>
                      <span className="ml-auto">{workflow.tags[0]}</span>
                    </div>
                  </div>
                </button>
                <div className="flex gap-1 border-t border-border-subtle px-3 py-2 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 flex-1 rounded-lg text-[9px]"
                    disabled={workflow.availability === "dependency"}
                    onClick={() => onUse(workflow.id, workflow.title)}
                  >
                    加入画布
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 flex-1 rounded-lg text-[9px]"
                    disabled={
                      workflow.availability === "dependency" ||
                      (runState?.workflowId === workflow.id &&
                        ["queued", "running"].includes(runState.state))
                    }
                    onClick={() => void runWorkflow(workflow.id)}
                  >
                    直接运行
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
        {online === false ? (
          <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900">
            <div className="font-semibold">没有发现 ComfyUI</div>
            <p className="mt-1 leading-5 text-amber-800">
              启动本机 ComfyUI 并监听 127.0.0.1:8188 后再检测。Octopus
              只连接你的本地服务，不会自动下载数十 GB 的模型。
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default function DesignPage({
  embeddedProject,
}: {
  embeddedProject?: { id: string; name?: string | null };
} = {}) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { user } = useAuth();
  const projectId =
    embeddedProject?.id || searchParams.get("project")?.trim() || null;
  const projectName =
    embeddedProject?.name || searchParams.get("name")?.trim() || null;
  const storageKey = projectId
    ? `${DESIGN_CANVAS_STORAGE_KEY}:project:${projectId}`
    : DESIGN_CANVAS_STORAGE_KEY;
  const stageRef = useRef<HTMLDivElement>(null);
  const [section, setSection] = useState<DesignSection>(
    projectId ? "canvas" : "home",
  );
  const [layout, setLayout] = useState<WorkspaceLayout>(
    embeddedProject ? "canvas" : "split",
  );
  const [layoutOpen, setLayoutOpen] = useState(false);
  const [document, setDocument] = useState<DesignCanvasDocument>(() => {
    const raw =
      typeof window === "undefined"
        ? null
        : window.localStorage.getItem(storageKey);
    const initial = parseDesignCanvas(raw);
    return projectName && !raw
      ? { ...initial, title: `${projectName} · 创作画布` }
      : initial;
  });
  const activeStorageKeyRef = useRef(storageKey);
  const documentRef = useRef(document);
  documentRef.current = document;
  const serverRevisionRef = useRef(0);
  const serverReadyRef = useRef(false);
  const activeServerProjectRef = useRef<string | null>(projectId);
  const lastSyncedDocumentRef = useRef("");
  const serverSaveChainRef = useRef(Promise.resolve());
  const canvasChannelRef = useRef<BroadcastChannel | null>(null);
  const presenceClientIdRef = useRef(
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `canvas-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`,
  );
  const presencePointerRef = useRef<{ x: number; y: number } | null>(null);
  const [presenceMembers, setPresenceMembers] = useState<
    CanvasPresenceMember[]
  >([]);
  const [canvasSyncState, setCanvasSyncState] = useState<CanvasSyncState>(
    projectId ? "loading" : "local",
  );
  const [pendingCanvasConflict, setPendingCanvasConflict] =
    useState<PendingCanvasConflict | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [toolMode, setToolMode] = useState<ToolMode>("select");
  const [zoom, setZoom] = useState(0.83);
  const [pan, setPan] = useState({ x: 80, y: 80 });
  const [addOpen, setAddOpen] = useState(false);
  const [addTab, setAddTab] = useState<AddTab>("nodes");
  const [query, setQuery] = useState("");
  const [assetsOpen, setAssetsOpen] = useState(false);
  const [embeddedSurface, setEmbeddedSurface] = useState<EmbeddedSurface>(null);
  const [comfyNative, setComfyNative] = useState(false);
  const [embeddedChatUrl, setEmbeddedChatUrl] = useState<string | null>(null);
  const { skills, isLoading: skillsLoading } = useSkills();
  const { plugins, isLoading: pluginsLoading } = usePlugins();
  const { plugins: hubPlugins, isLoading: hubPluginsLoading } = useHubPlugins();
  const { agents, isLoading: agentsLoading } = useAgents();
  const designPlugins = useMemo(
    () => [
      ...plugins,
      ...hubPlugins
        .filter((plugin) => !plugins.some((item) => item.id === plugin.id))
        .map((plugin) => ({
          id: plugin.id,
          name: plugin.display_name || plugin.name,
          description: plugin.description,
          enabled: plugin.enabled,
        })),
    ],
    [hubPlugins, plugins],
  );

  const reconcileRemoteCanvas = useCallback(
    (payload: CanvasServerPayload) => {
      if (!projectId || !payload.document) return;
      const revision = payload.revision ?? 0;
      if (revision <= serverRevisionRef.current) return;
      const remote = parseDesignCanvas(JSON.stringify(payload.document));
      const remoteSerialized = JSON.stringify(remote);
      const local = documentRef.current;
      const localSerialized = JSON.stringify(local);
      const isDirty = localSerialized !== lastSyncedDocumentRef.current;

      serverRevisionRef.current = revision;
      if (!isDirty) {
        lastSyncedDocumentRef.current = remoteSerialized;
        serverReadyRef.current = true;
        setPendingCanvasConflict(null);
        setDocument(remote);
        setCanvasSyncState("saved");
        return;
      }

      const base = parseDesignCanvas(lastSyncedDocumentRef.current);
      const merged = mergeDesignCanvases(base, local, remote);
      lastSyncedDocumentRef.current = remoteSerialized;
      if (merged.conflicts.length === 0) {
        serverReadyRef.current = true;
        setDocument(merged.document);
        setCanvasSyncState("saving");
        toast.success("已合并其他成员的画布更新");
        return;
      }

      serverReadyRef.current = false;
      setPendingCanvasConflict({
        revision,
        remote,
        merged: merged.document,
        conflicts: merged.conflicts,
      });
      setDocument(merged.document);
      setCanvasSyncState("conflict");
      toast.warning("同一画布内容被多人修改，请确认保留方式");
    },
    [projectId],
  );

  const pullRemoteCanvas = useCallback(async () => {
    if (!projectId || pendingCanvasConflict) return;
    const response = await fetch(
      `${getBackendBaseURL()}/api/design/projects/${encodeURIComponent(projectId)}/canvas`,
      { headers: authHeaders() },
    );
    if (!response.ok)
      throw new Error(`canvas refresh failed: ${response.status}`);
    reconcileRemoteCanvas((await response.json()) as CanvasServerPayload);
  }, [pendingCanvasConflict, projectId, reconcileRemoteCanvas]);

  useEffect(() => {
    activeServerProjectRef.current = projectId;
    serverReadyRef.current = false;
    serverRevisionRef.current = 0;
    lastSyncedDocumentRef.current = "";
    setPendingCanvasConflict(null);
    if (!projectId) {
      setCanvasSyncState("local");
      return;
    }
    const controller = new AbortController();
    setCanvasSyncState("loading");
    void fetch(
      `${getBackendBaseURL()}/api/design/projects/${encodeURIComponent(projectId)}/canvas`,
      { headers: authHeaders(), signal: controller.signal },
    )
      .then(async (response) => {
        if (!response.ok)
          throw new Error(`canvas load failed: ${response.status}`);
        return (await response.json()) as CanvasServerPayload;
      })
      .then((payload) => {
        if (controller.signal.aborted) return;
        serverRevisionRef.current = payload.revision ?? 0;
        serverReadyRef.current = true;
        if (payload.document) {
          const remote = parseDesignCanvas(JSON.stringify(payload.document));
          lastSyncedDocumentRef.current = JSON.stringify(remote);
          setDocument(remote);
        } else {
          // Trigger the save effect once so an existing local project canvas
          // becomes the first shared server revision.
          setDocument((current) => ({ ...current }));
        }
        setCanvasSyncState("saved");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        console.warn("Failed to load project canvas", error);
        setCanvasSyncState("error");
      });
    return () => controller.abort();
  }, [projectId]);

  useEffect(() => {
    if (!projectId || typeof BroadcastChannel === "undefined") return;
    const channel = new BroadcastChannel(`octopus:design:${projectId}`);
    canvasChannelRef.current = channel;
    channel.onmessage = (event: MessageEvent<CanvasServerPayload>) => {
      reconcileRemoteCanvas(event.data);
    };
    return () => {
      canvasChannelRef.current = null;
      channel.close();
    };
  }, [projectId, reconcileRemoteCanvas]);

  const presenceDisplayName =
    user?.username?.trim() || user?.actor_id?.trim() || "本地成员";
  useEffect(() => {
    if (!projectId) {
      setPresenceMembers([]);
      return;
    }
    let stopped = false;
    let failureReported = false;
    const clientId = presenceClientIdRef.current;
    const endpoint = `${getBackendBaseURL()}/api/design/projects/${encodeURIComponent(projectId)}/presence`;
    const heartbeat = async () => {
      if (window.document.visibilityState === "hidden") return;
      const pointer = section === "canvas" ? presencePointerRef.current : null;
      try {
        const response = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify({
            client_id: clientId,
            display_name: presenceDisplayName,
            x: pointer?.x ?? null,
            y: pointer?.y ?? null,
            section,
          }),
        });
        if (!response.ok)
          throw new Error(`presence heartbeat failed: ${response.status}`);
        const payload = (await response.json()) as {
          self_id?: string;
          items?: CanvasPresenceMember[];
        };
        if (stopped) return;
        setPresenceMembers(
          (payload.items ?? []).filter(
            (member) => member.id !== payload.self_id,
          ),
        );
        failureReported = false;
      } catch (error) {
        if (!failureReported) {
          console.warn("Failed to update Design presence", error);
          failureReported = true;
        }
      }
    };
    void heartbeat();
    const timer = window.setInterval(() => void heartbeat(), 750);
    return () => {
      stopped = true;
      window.clearInterval(timer);
      setPresenceMembers([]);
      void fetch(`${endpoint}/${encodeURIComponent(clientId)}`, {
        method: "DELETE",
        headers: authHeaders(),
        keepalive: true,
      }).catch(() => undefined);
    };
  }, [presenceDisplayName, projectId, section]);

  useEffect(() => {
    if (!projectId || pendingCanvasConflict) return;
    const timer = window.setInterval(() => {
      void pullRemoteCanvas().catch((error: unknown) => {
        console.warn("Failed to refresh project canvas", error);
      });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [pendingCanvasConflict, projectId, pullRemoteCanvas]);

  useEffect(() => {
    if (activeStorageKeyRef.current !== storageKey) {
      activeStorageKeyRef.current = storageKey;
      const raw = window.localStorage.getItem(storageKey);
      const next = parseDesignCanvas(raw);
      setDocument(
        projectName && !raw
          ? { ...next, title: `${projectName} · 创作画布` }
          : next,
      );
      return;
    }
    window.localStorage.setItem(storageKey, JSON.stringify(document));
  }, [document, projectName, storageKey]);
  useEffect(() => {
    if (!projectId || !serverReadyRef.current) return;
    const serialized = JSON.stringify(document);
    if (serialized === lastSyncedDocumentRef.current) return;
    const timer = window.setTimeout(() => {
      serverSaveChainRef.current = serverSaveChainRef.current.then(async () => {
        if (
          !serverReadyRef.current ||
          activeServerProjectRef.current !== projectId
        )
          return;
        setCanvasSyncState("saving");
        try {
          const response = await fetch(
            `${getBackendBaseURL()}/api/design/projects/${encodeURIComponent(projectId)}/canvas`,
            {
              method: "PUT",
              headers: {
                "Content-Type": "application/json",
                ...authHeaders(),
              },
              body: JSON.stringify({
                expected_revision: serverRevisionRef.current,
                document: JSON.parse(serialized) as Record<string, unknown>,
              }),
            },
          );
          if (response.status === 409) {
            await pullRemoteCanvas();
            return;
          }
          if (!response.ok)
            throw new Error(`canvas save failed: ${response.status}`);
          const payload = (await response.json()) as { revision?: number };
          if (activeServerProjectRef.current !== projectId) return;
          serverRevisionRef.current =
            payload.revision ?? serverRevisionRef.current + 1;
          lastSyncedDocumentRef.current = serialized;
          setCanvasSyncState("saved");
          canvasChannelRef.current?.postMessage({
            revision: serverRevisionRef.current,
            document: JSON.parse(serialized) as Record<string, unknown>,
          } satisfies CanvasServerPayload);
        } catch (error) {
          console.warn("Failed to save project canvas", error);
          setCanvasSyncState("error");
        }
      });
    }, 650);
    return () => window.clearTimeout(timer);
  }, [document, projectId, pullRemoteCanvas]);

  const resolveCanvasConflict = useCallback(
    (choice: "merge" | "remote") => {
      if (!pendingCanvasConflict) return;
      serverRevisionRef.current = pendingCanvasConflict.revision;
      serverReadyRef.current = true;
      setPendingCanvasConflict(null);
      if (choice === "remote") {
        const serialized = JSON.stringify(pendingCanvasConflict.remote);
        lastSyncedDocumentRef.current = serialized;
        setDocument(pendingCanvasConflict.remote);
        setCanvasSyncState("saved");
        toast.success("已载入成员的最新画布");
        return;
      }
      setCanvasSyncState("saving");
      setDocument({ ...pendingCanvasConflict.merged });
    },
    [pendingCanvasConflict],
  );
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.data?.type === "octopus.design.close-surface") {
        setEmbeddedSurface(null);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);
  const selectedNode = document.nodes.find((node) => node.id === selectedId);
  const patchNode = useCallback(
    (id: string, patch: Partial<DesignCanvasNode>) =>
      setDocument((current) => ({
        ...current,
        nodes: current.nodes.map((node) =>
          node.id === id ? { ...node, ...patch } : node,
        ),
      })),
    [],
  );
  const addNode = useCallback(
    (
      kind: DesignNodeKind,
      title: string,
      description: string,
      binding?: DesignCanvasNode["binding"],
      extras?: Pick<DesignCanvasNode, "asset" | "height" | "width">,
    ) => {
      const rect = stageRef.current?.getBoundingClientRect();
      const node: DesignCanvasNode = {
        id: nextNodeId(kind),
        kind,
        title,
        description,
        binding,
        ...extras,
        x: ((rect?.width ?? 850) / 2 - pan.x) / zoom - NODE_WIDTH / 2,
        y: ((rect?.height ?? 620) / 2 - pan.y) / zoom - NODE_HEIGHT / 2,
      };
      setDocument((current) =>
        appendDesignNode(
          current,
          node,
          current.mode === "workflow" ? selectedId : null,
        ),
      );
      setSelectedId(node.id);
      setAddOpen(false);
      return node.id;
    },
    [pan.x, pan.y, selectedId, zoom],
  );
  const placeOrLocateArtifact = useCallback(
    (artifact: ProjectArtifact) => {
      const existing = document.nodes.find(
        (node) => node.asset?.id === artifact.id,
      );
      if (existing) {
        const rect = stageRef.current?.getBoundingClientRect();
        setSelectedId(existing.id);
        setPan({
          x:
            (rect?.width ?? 850) / 2 -
            (existing.x + (existing.width ?? NODE_WIDTH) / 2) * zoom,
          y:
            (rect?.height ?? 620) / 2 -
            (existing.y + (existing.height ?? NODE_HEIGHT) / 2) * zoom,
        });
        toast.success("已在画布中定位");
        return;
      }
      const kind = artifactNodeKind(artifact);
      addNode(
        kind,
        artifact.name,
        artifact.summary || artifact.path || artifact.kind || "可复用资产",
        { type: "asset", id: artifact.id },
        {
          height: kind === "image" && artifact.url ? 240 : undefined,
          asset: {
            id: artifact.id,
            kind: artifact.kind || kind,
            path: artifact.path,
            url: artifact.url,
            projectId: artifact.category ? undefined : (projectId ?? undefined),
            source: artifact.task_id || artifact.milestone_id,
          },
        },
      );
      toast.success("资产已加入画布");
    },
    [addNode, document.nodes, projectId, zoom],
  );
  const removeSelected = () => {
    if (!selectedId) return;
    setDocument((current) => ({
      ...current,
      nodes: current.nodes.filter((node) => node.id !== selectedId),
      edges: current.edges.filter(
        (edge) => edge.source !== selectedId && edge.target !== selectedId,
      ),
    }));
    setSelectedId(null);
  };
  const fitCanvas = useCallback(() => {
    const rect = stageRef.current?.getBoundingClientRect();
    if (!rect || !document.nodes.length) return;
    const minX = Math.min(...document.nodes.map((node) => node.x));
    const minY = Math.min(...document.nodes.map((node) => node.y));
    const maxX = Math.max(
      ...document.nodes.map((node) => node.x + (node.width ?? NODE_WIDTH)),
    );
    const maxY = Math.max(
      ...document.nodes.map((node) => node.y + (node.height ?? NODE_HEIGHT)),
    );
    const next = Math.min(
      1,
      Math.max(
        MIN_ZOOM,
        Math.min(
          (rect.width - 120) / (maxX - minX),
          (rect.height - 120) / (maxY - minY),
        ),
      ),
    );
    setZoom(next);
    setPan({
      x: (rect.width - (maxX - minX) * next) / 2 - minX * next,
      y: (rect.height - (maxY - minY) * next) / 2 - minY * next,
    });
  }, [document.nodes]);
  const runCanvas = (extra?: string) => {
    const base = designCanvasRunPrompt(document);
    const prompt = extra?.trim() ? `${extra.trim()}\n\n${base}` : base;
    const agent =
      document.nodes.find((node) => node.binding?.type === "agent")?.binding
        ?.id ?? "general";
    const params = new URLSearchParams({
      prompt,
      agent,
      embedded: "design",
    });
    if (projectId) params.set("project", projectId);
    const shellBase = window.location.href.split("#", 1)[0];
    setEmbeddedChatUrl(
      `${shellBase}#/workspace/realtime/new?${params.toString()}`,
    );
    if (layout === "canvas") setLayout("split");
  };
  const handleStagePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget && toolMode !== "hand") return;
    if (toolMode === "select") setSelectedId(null);
    const startX = event.clientX;
    const startY = event.clientY;
    const origin = pan;
    const move = (next: PointerEvent) =>
      setPan({
        x: origin.x + next.clientX - startX,
        y: origin.y + next.clientY - startY,
      });
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end, { once: true });
  };
  const handleWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (event.ctrlKey || event.metaKey)
      setZoom((current) =>
        Math.min(
          MAX_ZOOM,
          Math.max(MIN_ZOOM, current * (event.deltaY > 0 ? 0.9 : 1.1)),
        ),
      );
    else
      setPan((current) => ({
        x: current.x - event.deltaX,
        y: current.y - event.deltaY,
      }));
  };
  const handleStagePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const bounds = stageRef.current?.getBoundingClientRect();
    if (!bounds) return;
    presencePointerRef.current = {
      x: (event.clientX - bounds.left - pan.x) / zoom,
      y: (event.clientY - bounds.top - pan.y) / zoom,
    };
  };

  const canvasSurface = (
    <main
      ref={stageRef}
      data-testid="design-infinite-canvas"
      onPointerDown={handleStagePointerDown}
      onPointerMove={handleStagePointerMove}
      onPointerLeave={() => {
        presencePointerRef.current = null;
      }}
      onWheel={handleWheel}
      className={cn(
        "relative min-w-0 flex-1 touch-none overflow-hidden bg-[#fafafa] dark:bg-[#0a0a0a]",
        toolMode === "hand" && "cursor-grab active:cursor-grabbing",
      )}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-55"
        style={{
          backgroundImage:
            "radial-gradient(circle, color-mix(in oklch, var(--foreground) 18%, transparent) 1px, transparent 1px)",
          backgroundSize: `${24 * zoom}px ${24 * zoom}px`,
          backgroundPosition: `${pan.x}px ${pan.y}px`,
        }}
      />
      <div
        className="pointer-events-none absolute left-0 top-0 h-[3000px] w-[4200px] origin-top-left"
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
        }}
      >
        <EdgeLayer document={document} />
        {document.nodes.map((node) => (
          <CanvasNode
            key={node.id}
            node={node}
            selected={node.id === selectedId}
            zoom={zoom}
            mode={toolMode}
            onSelect={() => setSelectedId(node.id)}
            onMove={(x, y) => patchNode(node.id, { x, y })}
          />
        ))}
      </div>
      {presenceMembers
        .filter(
          (member) =>
            member.section === "canvas" &&
            typeof member.x === "number" &&
            typeof member.y === "number",
        )
        .map((member) => (
          <div
            key={member.id}
            aria-hidden
            className="pointer-events-none absolute z-10 transition-[left,top] duration-200 ease-out"
            style={{
              left: pan.x + (member.x ?? 0) * zoom,
              top: pan.y + (member.y ?? 0) * zoom,
            }}
          >
            <svg
              width="18"
              height="22"
              viewBox="0 0 18 22"
              className="drop-shadow-sm"
            >
              <path
                d="M2 1.5 16 12l-7.1 1.2L5.4 20Z"
                fill={member.color}
                stroke="white"
                strokeWidth="1.5"
                strokeLinejoin="round"
              />
            </svg>
            <span
              className="absolute left-3 top-4 whitespace-nowrap rounded-md px-1.5 py-0.5 text-[9px] font-medium text-white shadow-sm"
              style={{ backgroundColor: member.color }}
            >
              {member.display_name}
            </span>
          </div>
        ))}
      <div className="absolute right-3 top-3 z-20 flex h-9 items-center gap-0.5 rounded-[12px] border border-[#0000000f] bg-white/90 px-1 shadow-[0_2px_5px_rgba(0,0,0,.08)] backdrop-blur dark:border-[#4a4a4a] dark:bg-[#1a1a1a]/90">
        <button
          onClick={() => setDocument((current) => tidyDesignCanvas(current))}
          className="grid size-7 place-items-center rounded-lg hover:bg-muted"
          title="整理"
        >
          <Redo2Icon className="size-3.5" />
        </button>
        <button
          onClick={() => setZoom((value) => Math.max(MIN_ZOOM, value - 0.1))}
          className="grid size-7 place-items-center rounded-lg hover:bg-muted"
          title="缩小"
        >
          <MinusIcon className="size-3.5" />
        </button>
        <button
          onClick={fitCanvas}
          className="min-w-10 px-1 text-[10px] text-muted-foreground"
        >
          {Math.round(zoom * 100)}%
        </button>
        <button
          onClick={() => setZoom((value) => Math.min(MAX_ZOOM, value + 0.1))}
          className="grid size-7 place-items-center rounded-lg hover:bg-muted"
          title="放大"
        >
          <PlusIcon className="size-3.5" />
        </button>
        <button
          className="grid size-7 place-items-center rounded-lg hover:bg-muted"
          title="画布设置"
        >
          <Settings2Icon className="size-3.5" />
        </button>
        <button
          className="grid size-7 place-items-center rounded-lg hover:bg-muted"
          title="小地图"
        >
          <Grid2X2Icon className="size-3.5" />
        </button>
      </div>
      <div className="absolute bottom-4 left-1/2 z-30 flex h-11 -translate-x-1/2 items-center gap-1 rounded-[12px] border border-[#0000000f] bg-white/90 px-1.5 shadow-[0_2px_5px_rgba(0,0,0,.08)] backdrop-blur dark:border-[#4a4a4a] dark:bg-[#1a1a1a]/90">
        <button
          onClick={() => setAddOpen((value) => !value)}
          className="grid size-8 place-items-center rounded-full bg-foreground text-background"
          title="添加节点"
        >
          <PlusIcon className="size-4" />
        </button>
        <button
          onClick={() => setToolMode("select")}
          className={cn(
            "grid size-8 place-items-center rounded-lg",
            toolMode === "select" ? "bg-muted" : "hover:bg-muted",
          )}
          title="选择 V"
        >
          <MousePointer2Icon className="size-4" />
        </button>
        <button
          onClick={() => setToolMode("hand")}
          className={cn(
            "grid size-8 place-items-center rounded-lg",
            toolMode === "hand" ? "bg-muted" : "hover:bg-muted",
          )}
          title="移动 H"
        >
          <HandIcon className="size-4" />
        </button>
        <span className="mx-0.5 h-5 w-px bg-border-subtle" />
        <button
          onClick={() => setAssetsOpen((value) => !value)}
          className={cn(
            "grid size-8 place-items-center rounded-lg",
            assetsOpen ? "bg-muted" : "hover:bg-muted",
          )}
          title="项目资产"
        >
          <FolderIcon className="size-4" />
        </button>
        <button
          className="grid size-8 place-items-center rounded-lg hover:bg-muted"
          title="帮助"
        >
          <CircleHelpIcon className="size-4" />
        </button>
      </div>
      {addOpen ? (
        <AddNodePopover
          tab={addTab}
          query={query}
          agents={agents}
          skills={skills}
          plugins={designPlugins}
          loading={
            (addTab === "agents" && agentsLoading) ||
            (addTab === "skills" && skillsLoading) ||
            (addTab === "plugins" && (pluginsLoading || hubPluginsLoading))
          }
          onTab={setAddTab}
          onQuery={setQuery}
          onAdd={addNode}
          onClose={() => setAddOpen(false)}
        />
      ) : null}
      {selectedNode ? (
        <div className="absolute bottom-4 right-4 z-30 w-64 rounded-[12px] border border-[#e6e6e6] bg-white p-3 shadow-[0_8px_32px_rgba(0,0,0,.08),0_2px_8px_rgba(0,0,0,.04)] dark:border-[#454545] dark:bg-[#1a1a1a]">
          <div className="flex items-center">
            <span className="text-xs font-semibold">节点设置</span>
            <span className="flex-1" />
            <button onClick={() => setSelectedId(null)}>
              <XIcon className="size-3.5" />
            </button>
          </div>
          <Input
            value={selectedNode.title}
            onChange={(event) =>
              patchNode(selectedNode.id, { title: event.target.value })
            }
            className="mt-3 h-8 text-xs"
          />
          <Textarea
            value={selectedNode.description}
            onChange={(event) =>
              patchNode(selectedNode.id, { description: event.target.value })
            }
            className="mt-2 min-h-20 resize-none text-xs"
          />
          {selectedNode.kind === "director" ? (
            <Button
              className="mt-2 w-full rounded-lg text-xs"
              onClick={() => setEmbeddedSurface("director")}
            >
              打开导演台
            </Button>
          ) : null}
          {selectedNode.kind === "editor" ? (
            <Button
              className="mt-2 w-full rounded-lg text-xs"
              onClick={() => setEmbeddedSurface("editor")}
            >
              打开剪辑工坊
            </Button>
          ) : null}
          {selectedNode.kind === "comfyui" ? (
            <Button
              className="mt-2 w-full rounded-lg text-xs"
              onClick={() => {
                setComfyNative(false);
                setEmbeddedSurface("comfyui");
              }}
            >
              打开 ComfyUI
            </Button>
          ) : null}
          <button
            onClick={removeSelected}
            className="mt-2 flex items-center gap-1.5 text-[10px] text-destructive"
          >
            <Trash2Icon className="size-3" />
            删除节点
          </button>
        </div>
      ) : null}
      {embeddedSurface ? (
        <div className="absolute inset-0 z-50 flex flex-col overflow-hidden bg-background">
          {embeddedSurface === "director" ? (
            <DirectorStage
              sceneId={projectId || selectedNode?.id || "default"}
              onClose={() => setEmbeddedSurface(null)}
            />
          ) : embeddedSurface === "editor" ? (
            <PluginNodeFrame
              title="AI 剪辑工坊"
              src={`${getBackendBaseURL()}/api/plugins/clip-studio/page?project=${encodeURIComponent(projectId || selectedNode?.id || "default")}`}
              projectId={projectId}
              pluginId="clip-studio"
              nodeId={selectedNode?.id || "clip-studio"}
              className="min-h-0 flex-1 border-0 bg-background"
            />
          ) : !comfyNative ? (
            <ComfyWorkflowEditor
              workflowId={
                selectedNode?.binding?.type === "workflow"
                  ? selectedNode.binding.id
                  : "blank"
              }
              onClose={() => setEmbeddedSurface(null)}
              onOpenNative={() => setComfyNative(true)}
            />
          ) : (
            <>
              <div className="flex h-11 shrink-0 items-center border-b border-border-subtle px-3">
                <span className="text-xs font-semibold">ComfyUI 工作流</span>
                <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[8px] text-muted-foreground">
                  本机原生界面
                </span>
                <span className="flex-1" />
                <Button
                  variant="ghost"
                  size="sm"
                  className="mr-1 h-8 text-[10px]"
                  onClick={() => setComfyNative(false)}
                >
                  返回 Octopus 编辑器
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-8"
                  onClick={() => setEmbeddedSurface(null)}
                >
                  <XIcon className="size-4" />
                </Button>
              </div>
              <iframe
                title="ComfyUI 工作流"
                src="http://127.0.0.1:8188"
                className="min-h-0 flex-1 border-0 bg-background"
                sandbox="allow-scripts allow-same-origin allow-downloads allow-forms"
              />
            </>
          )}
        </div>
      ) : null}
    </main>
  );

  return (
    <div className="relative flex h-full min-h-0 w-full flex-col overflow-hidden bg-background">
      <header className="flex h-12 shrink-0 items-center border-b border-border-subtle bg-background px-2.5">
        {!embeddedProject ? (
          <Button
            variant="ghost"
            size="icon"
            className="size-8"
            onClick={() =>
              projectId ? navigate("/workspace/projects") : navigate(-1)
            }
            aria-label="返回"
          >
            <ArrowLeftIcon className="size-4" />
          </Button>
        ) : null}
        <div className="ml-1 flex min-w-0 items-center gap-2">
          <span className="grid size-7 place-items-center rounded-lg bg-violet-100 text-violet-600">
            <WandSparklesIcon className="size-3.5" />
          </span>
          {section === "home" ? (
            <span className="text-[13px] font-semibold">Octopus Design</span>
          ) : (
            <input
              value={document.title}
              onChange={(event) =>
                setDocument((current) => ({
                  ...current,
                  title: event.target.value,
                }))
              }
              className="w-44 truncate bg-transparent text-[13px] font-semibold outline-none"
              aria-label="画布名称"
            />
          )}
          {projectId ? (
            <span className="hidden max-w-40 truncate rounded-md bg-muted px-2 py-1 text-[10px] font-medium text-muted-foreground lg:inline">
              项目 · {projectName || projectId}
            </span>
          ) : null}
          {projectId ? (
            <span
              className={cn(
                "hidden text-[9px] text-muted-foreground xl:inline",
                canvasSyncState === "conflict" && "text-amber-600",
                canvasSyncState === "error" && "text-red-600",
              )}
            >
              {canvasSyncState === "loading"
                ? "正在载入"
                : canvasSyncState === "saving"
                  ? "正在保存"
                  : canvasSyncState === "saved"
                    ? "已同步"
                    : canvasSyncState === "conflict"
                      ? "版本冲突"
                      : canvasSyncState === "error"
                        ? "仅本地保存"
                        : "本地画布"}
            </span>
          ) : null}
          {projectId ? (
            <div
              className="hidden items-center -space-x-1.5 sm:flex"
              title={`${presenceMembers.length + 1} 位成员在线`}
            >
              <span className="grid size-6 place-items-center rounded-full border-2 border-background bg-foreground text-[8px] font-semibold text-background">
                {presenceDisplayName.slice(0, 1).toUpperCase()}
              </span>
              {presenceMembers.slice(0, 3).map((member) => (
                <span
                  key={member.id}
                  className="grid size-6 place-items-center rounded-full border-2 border-background text-[8px] font-semibold text-white"
                  style={{ backgroundColor: member.color }}
                  title={`${member.display_name} · ${member.section === "canvas" ? "画布" : member.section}`}
                >
                  {member.display_name.slice(0, 1).toUpperCase()}
                </span>
              ))}
              {presenceMembers.length > 3 ? (
                <span className="grid size-6 place-items-center rounded-full border-2 border-background bg-muted text-[8px] font-medium text-muted-foreground">
                  +{presenceMembers.length - 3}
                </span>
              ) : null}
            </div>
          ) : null}
          {pendingCanvasConflict ? (
            <span className="hidden items-center gap-1 xl:flex">
              <button
                type="button"
                onClick={() => resolveCanvasConflict("merge")}
                className="rounded-md bg-amber-100 px-2 py-1 text-[9px] font-medium text-amber-800 transition hover:bg-amber-200"
                title={`本地优先合并 ${pendingCanvasConflict.conflicts.length} 处冲突`}
              >
                合并保存
              </button>
              <button
                type="button"
                onClick={() => resolveCanvasConflict("remote")}
                className="rounded-md px-2 py-1 text-[9px] text-muted-foreground transition hover:bg-muted"
              >
                载入新版
              </button>
            </span>
          ) : null}
        </div>
        <nav
          className={cn(
            "ml-5 h-full items-center gap-1 text-[11px]",
            embeddedProject ? "hidden xl:flex" : "flex",
          )}
        >
          {(
            [
              ["home", "开始创作"],
              ["canvas", "创作画布"],
              ["assets", "资产中心"],
              ["skills", "Skill"],
              ["comfyui", "ComfyUI"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              onClick={() => setSection(id)}
              className={cn(
                "relative h-full px-2.5 text-muted-foreground",
                section === id &&
                  "font-medium text-foreground after:absolute after:bottom-0 after:left-2 after:right-2 after:h-0.5 after:rounded-full after:bg-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </nav>
        <span className="flex-1" />
        {section === "canvas" ? (
          <>
            <div className="mr-1 flex rounded-lg bg-muted/70 p-0.5 text-[10px]">
              <button
                onClick={() =>
                  setDocument((current) => ({ ...current, mode: "freeform" }))
                }
                className={cn(
                  "rounded-md px-2.5 py-1.5",
                  document.mode === "freeform" &&
                    "bg-background font-medium shadow-sm",
                )}
              >
                自由画布
              </button>
              <button
                onClick={() =>
                  setDocument((current) => ({ ...current, mode: "workflow" }))
                }
                className={cn(
                  "rounded-md px-2.5 py-1.5",
                  document.mode === "workflow" &&
                    "bg-background font-medium shadow-sm",
                )}
              >
                工作流
              </button>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-8 gap-1 text-[11px]"
              onClick={() => runCanvas()}
            >
              <CirclePlayIcon className="size-3.5" />
              交给 AI
            </Button>
            <div className="relative">
              <Button
                variant="ghost"
                size="icon"
                className="size-8"
                onClick={() => setLayoutOpen((value) => !value)}
                aria-label="工作区布局"
              >
                <LayoutPanelLeftIcon className="size-4" />
              </Button>
              {layoutOpen ? (
                <div className="absolute right-0 top-10 z-50 w-52 rounded-xl border border-border-default bg-background p-2 shadow-xl">
                  <div className="px-2 pb-2 pt-1 text-[10px] font-semibold text-muted-foreground">
                    布局模式
                  </div>
                  {(
                    [
                      ["split", "对话 + 画布", PanelRightIcon],
                      ["chat-left", "对话在左", PanelLeftCloseIcon],
                      ["chat", "仅对话", MessageSquareIcon],
                      ["canvas", "仅画布", Maximize2Icon],
                    ] as const
                  ).map(([id, label, Icon]) => (
                    <button
                      key={id}
                      onClick={() => {
                        setLayout(id);
                        setLayoutOpen(false);
                      }}
                      className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-[11px] hover:bg-muted"
                    >
                      <Icon className="size-3.5" />
                      {label}
                      <span className="flex-1" />
                      {layout === id ? (
                        <CheckIcon className="size-3.5" />
                      ) : null}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </>
        ) : null}
      </header>
      <div className="min-h-0 flex-1">
        {section === "home" ? (
          <DesignHomeView
            onStart={(prompt) => {
              addNode("brief", "创作需求", prompt);
              setSection("canvas");
              runCanvas(prompt);
            }}
            onOpenSkills={() => setSection("skills")}
            onOpenComfy={() => setSection("comfyui")}
            onOpenCanvas={() => setSection("canvas")}
          />
        ) : null}
        {section === "assets" ? (
          <AssetsView
            agents={agents}
            projectId={projectId}
            onUseAgent={(agent) => {
              addNode(
                "agent",
                agent.display_name || agent.name,
                agent.description || "Octopus AI 创作角色",
                { type: "agent", id: agent.name },
              );
              setSection("canvas");
              toast.success("角色资产已加入画布");
            }}
            onUseArtifact={(artifact) => {
              placeOrLocateArtifact(artifact);
              setSection("canvas");
            }}
          />
        ) : null}
        {section === "skills" ? (
          <SkillsView
            installedSkills={skills}
            loading={skillsLoading}
            onUse={(id) => {
              const skill = CREATIVE_SKILL_COLLECTION.find(
                (item) => item.id === id,
              );
              if (skill) {
                addNode("skill", skill.title, skill.description, {
                  type: "skill",
                  id,
                });
                setSection("canvas");
                toast.success("Skill 已加入画布");
              }
            }}
          />
        ) : null}
        {section === "comfyui" ? (
          <ComfyUIView
            onUse={(id, title) => {
              addNode(
                "comfyui",
                title,
                "连接本机 ComfyUI，运行节点式生成工作流",
                { type: "workflow", id },
              );
              setSection("canvas");
              toast.success("ComfyUI 工作流已加入画布");
            }}
          />
        ) : null}
        {section === "canvas" ? (
          <div className="flex h-full min-h-0">
            {layout === "chat-left" || layout === "chat" ? (
              <ChatPanel
                chatUrl={embeddedChatUrl}
                onRun={runCanvas}
                onNew={() => setEmbeddedChatUrl(null)}
                onClose={() => setLayout("canvas")}
              />
            ) : null}
            {layout !== "chat" ? canvasSurface : null}
            {layout !== "chat" && assetsOpen ? (
              <CanvasAssetsPanel
                projectId={projectId}
                document={document}
                onClose={() => setAssetsOpen(false)}
                onPick={placeOrLocateArtifact}
              />
            ) : null}
            {layout === "split" ? (
              <ChatPanel
                chatUrl={embeddedChatUrl}
                onRun={runCanvas}
                onNew={() => setEmbeddedChatUrl(null)}
                onClose={() => setLayout("canvas")}
              />
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
