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
  BotIcon,
  CheckIcon,
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
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useAgents } from "@/core/agents/hooks";
import type { Agent } from "@/core/agents/types";
import { authHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useHubPlugins, usePlugins } from "@/core/plugins/hooks";
import { useSkills } from "@/core/skills/hooks";
import { cn } from "@/lib/utils";

import {
  appendDesignNode,
  DESIGN_CANVAS_STORAGE_KEY,
  designCanvasRunPrompt,
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

type ToolMode = "select" | "hand";
type AddTab = "nodes" | "agents" | "skills" | "plugins";
type EmbeddedSurface = "director" | "editor" | "comfyui" | null;
type CanvasSyncState =
  | "local"
  | "loading"
  | "saving"
  | "saved"
  | "conflict"
  | "error";

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

function EdgeLayer({ document }: { document: DesignCanvasDocument }) {
  if (document.mode !== "workflow") return null;
  return (
    <svg className="pointer-events-none absolute inset-0 size-full overflow-visible">
      {document.edges.map((edge) => {
        const source = document.nodes.find((node) => node.id === edge.source);
        const target = document.nodes.find((node) => node.id === edge.target);
        if (!source || !target) return null;
        const sx = source.x + (source.width ?? NODE_WIDTH);
        const sy = source.y + 61;
        const tx = target.x;
        const ty = target.y + 61;
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
        <p className="mt-2.5 line-clamp-2 text-[11px] leading-[17px] text-muted-foreground">
          {node.description}
        </p>
      </div>
      <span className="absolute -left-1 top-[58px] size-2 rounded-full bg-foreground/25" />
      <span className="absolute -right-1 top-[58px] size-2 rounded-full bg-foreground/50" />
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

function AssetsView({
  agents,
  onUseAgent,
}: {
  agents: Agent[];
  onUseAgent: (agent: Agent) => void;
}) {
  const [grid, setGrid] = useState(true);
  const [category, setCategory] = useState("所有类型");
  const [query, setQuery] = useState("");
  const categories = ["所有类型", "角色", "场景", "风格包", "道具", "自定义"];
  const needle = query.trim().toLowerCase();
  const visibleAgents =
    category === "所有类型" || category === "角色"
      ? agents.filter((agent) =>
          `${agent.display_name ?? agent.name} ${agent.description ?? ""}`
            .toLowerCase()
            .includes(needle),
        )
      : [];
  return (
    <div className="h-full overflow-y-auto bg-background px-11 py-9">
      <div className="mx-auto max-w-5xl">
        <h1 className="text-2xl font-semibold tracking-tight">资产中心</h1>
        <p className="mt-1.5 text-xs text-muted-foreground">
          沉淀可复用的角色、场景、风格包、道具等素材，在新的创作空间中快速调用
        </p>
        <div className="mt-7 flex gap-2">
          <Button
            className="rounded-xl"
            onClick={() => toast.info("可从画布节点或本地文件创建新资产")}
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
        {visibleAgents.length > 0 ? (
          <div
            className={cn(
              "mt-6",
              grid
                ? "grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4"
                : "flex flex-col gap-2",
            )}
          >
            {visibleAgents.map((agent) => {
              const title = agent.display_name || agent.name;
              const imageUrl = agent.avatar_url || agent.visual_urls?.portrait;
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
                  <div className={cn("min-w-0 flex-1", grid ? "p-3" : "ml-3")}>
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
        ) : (
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
        )}
      </div>
    </div>
  );
}

function SkillsView({ onUse }: { onUse: (id: string) => void }) {
  const [category, setCategory] = useState("全部");
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<"market" | "mine">("market");
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
  const items = CREATIVE_SKILL_COLLECTION.filter(
    (item) =>
      (category === "全部" ||
        category === "精选" ||
        item.category === category) &&
      (!needle ||
        `${item.title} ${item.description} ${item.category}`
          .toLowerCase()
          .includes(needle)),
  );

  return (
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
            onClick={() => toast.info("支持从 Skill 目录或压缩包安装")}
          >
            <PlusIcon className="mr-1.5 size-3.5" />
            安装 Skill
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
            {tab === "market" ? "官方精选" : "已安装 Skill"}
          </h2>
          <span className="ml-2 text-[10px] text-muted-foreground">
            {items.length}
          </span>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-4">
          {items.map((item) => {
            const Icon = item.icon;
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
                  <div className="absolute inset-0 bg-[radial-gradient(circle_at_25%_15%,rgba(255,255,255,.65),transparent_34%)]" />
                  <Icon className="absolute bottom-4 right-5 size-11 text-foreground/45" />
                  <span className="absolute left-2.5 top-2.5 rounded-md bg-violet-600 px-1.5 py-0.5 text-[8px] font-medium text-white">
                    官方
                  </span>
                  <div className="absolute inset-0 flex items-center justify-center gap-1.5 bg-black/40 opacity-0 backdrop-blur-[1px] transition-opacity group-hover:opacity-100">
                    <button
                      onClick={() => toast.info(item.description)}
                      className="rounded-lg bg-white/92 px-2.5 py-1.5 text-[9px] font-medium text-zinc-900"
                    >
                      查看详情
                    </button>
                    <button
                      onClick={() => onUse(item.id)}
                      className="rounded-lg bg-zinc-950/90 px-2.5 py-1.5 text-[9px] font-medium text-white"
                    >
                      加入画布
                    </button>
                  </div>
                </div>
                <button
                  onClick={() => onUse(item.id)}
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
                    <CheckIcon className="size-3 text-violet-500" />
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
  );
}

function ComfyUIView({
  onUse,
}: {
  onUse: (id: string, title: string) => void;
}) {
  const [checking, setChecking] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const [dependencies, setDependencies] = useState<{
    detected: boolean;
    path: string | null;
    modelCounts: Record<string, number>;
    totalModels: number;
    customNodes: string[];
    totalCustomNodes: number;
  } | null>(null);
  const [tab, setTab] = useState<"market" | "mine">("market");
  const [query, setQuery] = useState("");
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
      };
      setDependencies({
        detected: payload.detected === true,
        path: payload.path ?? null,
        modelCounts: payload.model_counts ?? {},
        totalModels: payload.total_models ?? 0,
        customNodes: payload.custom_nodes ?? [],
        totalCustomNodes: payload.total_custom_nodes ?? 0,
      });
    } catch {
      // Dependency inventory is optional and never blocks the workflow market.
    }
  }, []);
  useEffect(() => {
    void loadWorkflows();
    void loadDependencies();
  }, [loadDependencies, loadWorkflows]);
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
      const payload = (await response.json()) as { online?: boolean };
      setOnline(response.ok && payload.online === true);
    } catch {
      setOnline(false);
    } finally {
      void loadDependencies();
      setChecking(false);
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
      <div className="mx-auto max-w-5xl">
        <div className="flex items-start">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">
              ComfyUI 工作流
            </h1>
            <p className="mt-1.5 text-xs text-muted-foreground">
              支持本地部署，可手动运行，也可作为画布节点由 Agent 调用
            </p>
          </div>
          <span className="flex-1" />
          <div
            className={cn(
              "mt-1 flex items-center gap-2 rounded-full border px-3 py-1.5 text-[10px]",
              online === true
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : online === false
                  ? "border-red-200 bg-red-50 text-red-700"
                  : "text-muted-foreground",
            )}
          >
            <span
              className={cn(
                "size-1.5 rounded-full",
                online === true
                  ? "bg-emerald-500"
                  : online === false
                    ? "bg-red-500"
                    : "bg-zinc-400",
              )}
            />
            {online === true
              ? "本地服务在线"
              : online === false
                ? "本地服务离线"
                : "尚未检测"}
          </div>
        </div>
        <div className="mt-7 flex gap-2">
          <Button
            className="rounded-xl"
            onClick={() => importRef.current?.click()}
          >
            <ArchiveIcon className="mr-1.5 size-4" />
            导入工作流
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
            className="rounded-xl"
            onClick={() => onUse("blank", "空白 ComfyUI 工作流")}
          >
            <PlusIcon className="mr-1.5 size-4" />
            新建工作流
          </Button>
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
        </div>
        {dependencies ? (
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
        <div className="mt-8 flex items-center border-t border-border-subtle pt-4">
          <button
            onClick={() => setTab("market")}
            className={cn(
              "rounded-lg px-3 py-2 text-xs",
              tab === "market"
                ? "bg-muted font-medium"
                : "text-muted-foreground",
            )}
          >
            精选工作流
          </button>
          <button
            onClick={() => setTab("mine")}
            className={cn(
              "rounded-lg px-3 py-2 text-xs",
              tab === "mine" ? "bg-muted font-medium" : "text-muted-foreground",
            )}
          >
            我的工作流
          </button>
          <span className="flex-1" />
          <div className="relative w-56">
            <SearchIcon className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-9 rounded-xl pl-9 text-xs"
              placeholder="搜索工作流"
            />
          </div>
        </div>
        <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          {visibleWorkflows.map((workflow, index) => (
            <div
              key={workflow.id}
              className={cn(
                "overflow-hidden rounded-[14px] border border-border-default text-left transition",
                workflow.availability !== "dependency"
                  ? "hover:-translate-y-0.5 hover:shadow-lg"
                  : "opacity-75 hover:border-amber-300",
              )}
            >
              <button
                type="button"
                onClick={() => {
                  if (workflow.availability === "dependency") {
                    toast.info("该工作流需要先安装对应的本地模型或扩展");
                    return;
                  }
                  onUse(workflow.id, workflow.title);
                }}
                className="block w-full text-left"
              >
                <div
                  className={cn(
                    "relative h-32",
                    index % 2
                      ? "bg-[radial-gradient(circle_at_30%_25%,#b7d8ff,transparent_35%),linear-gradient(135deg,#1e293b,#715ea8)]"
                      : "bg-[radial-gradient(circle_at_70%_30%,#ffd4e5,transparent_35%),linear-gradient(135deg,#3b455c,#69a5a2)]",
                  )}
                >
                  <SparklesIcon className="absolute bottom-4 right-4 size-9 text-white/70" />
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
                  <div className="mt-2 flex gap-1">
                    {workflow.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded bg-muted px-1.5 py-0.5 text-[8px] text-muted-foreground"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
              </button>
              <div className="flex gap-1 px-3 pb-3">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 flex-1 text-[9px]"
                  disabled={workflow.availability === "dependency"}
                  onClick={() => onUse(workflow.id, workflow.title)}
                >
                  加入画布
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 flex-1 text-[9px]"
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

export default function DesignPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project")?.trim() || null;
  const projectName = searchParams.get("name")?.trim() || null;
  const storageKey = projectId
    ? `${DESIGN_CANVAS_STORAGE_KEY}:project:${projectId}`
    : DESIGN_CANVAS_STORAGE_KEY;
  const stageRef = useRef<HTMLDivElement>(null);
  const [section, setSection] = useState<DesignSection>(
    projectId ? "canvas" : "home",
  );
  const [layout, setLayout] = useState<WorkspaceLayout>("split");
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
  const [canvasSyncState, setCanvasSyncState] = useState<CanvasSyncState>(
    projectId ? "loading" : "local",
  );
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

  useEffect(() => {
    activeServerProjectRef.current = projectId;
    serverReadyRef.current = false;
    serverRevisionRef.current = 0;
    lastSyncedDocumentRef.current = "";
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
        return (await response.json()) as {
          revision?: number;
          document?: Record<string, unknown> | null;
        };
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
            serverReadyRef.current = false;
            setCanvasSyncState("conflict");
            toast.warning("画布已有其他成员的新版本，请刷新后继续编辑");
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
        } catch (error) {
          console.warn("Failed to save project canvas", error);
          setCanvasSyncState("error");
        }
      });
    }, 650);
    return () => window.clearTimeout(timer);
  }, [document, projectId]);
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
    ) => {
      const rect = stageRef.current?.getBoundingClientRect();
      const node: DesignCanvasNode = {
        id: nextNodeId(kind),
        kind,
        title,
        description,
        binding,
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
    },
    [pan.x, pan.y, selectedId, zoom],
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
      ...document.nodes.map((node) => node.y + NODE_HEIGHT),
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

  const canvasSurface = (
    <main
      ref={stageRef}
      data-testid="design-infinite-canvas"
      onPointerDown={handleStagePointerDown}
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
      {assetsOpen ? (
        <div className="absolute bottom-[72px] left-4 z-30 w-64 rounded-[12px] border border-[#e6e6e6] bg-white p-3 shadow-[0_8px_32px_rgba(0,0,0,.08),0_2px_8px_rgba(0,0,0,.04)] dark:border-[#454545] dark:bg-[#1a1a1a]">
          <div className="flex items-center">
            <span className="text-xs font-semibold">项目资产</span>
            <span className="flex-1" />
            <button onClick={() => setAssetsOpen(false)}>
              <XIcon className="size-3.5" />
            </button>
          </div>
          <div className="mt-3 rounded-xl border border-dashed p-6 text-center">
            <ImageIcon className="mx-auto size-5 text-muted-foreground" />
            <p className="mt-2 text-[10px] text-muted-foreground">
              拖入图片、视频、音频或文件
            </p>
          </div>
        </div>
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
            <iframe
              title="AI 剪辑工坊"
              src={`${getBackendBaseURL()}/api/plugins/clip-studio/page?project=${encodeURIComponent(projectId || selectedNode?.id || "default")}`}
              className="min-h-0 flex-1 border-0 bg-background"
              sandbox="allow-scripts allow-same-origin allow-downloads"
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
        </div>
        <nav className="ml-5 flex h-full items-center gap-1 text-[11px]">
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
          />
        ) : null}
        {section === "skills" ? (
          <SkillsView
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
