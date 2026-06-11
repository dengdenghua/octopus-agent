/**
 * Mobile App Shell — Octopus 移动端 Agent UI（参考 Manus/Marvis 风格）.
 *
 * 底部 4 Tab + 顶部应用栏 + 设备切换 + 设备预览 Modal + 左侧抽屉:
 *   1. 对话 (default) - AI 对话 + 快捷任务
 *   2. 任务 - 自动任务列表
 *   3. 技能 - 30 个 Skill 展示
 *   4. 我的 - 个人中心 + 设备管理
 *
 * 设备交互设计:
 *   - 顶部"我的手机"点击 → 弹出设备切换下拉（我的手机/我的电脑/其他设备）
 *   - 右上设备图标 → 弹出设备预览 ActionSheet
 *   - 左上汉堡菜单 → 弹出左侧抽屉（新建对话 + 历史对话）
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AppWindowIcon,
  ArrowRightIcon,
  BookOpenIcon,
  BriefcaseIcon,
  CalendarIcon,
  CheckCircle2Icon,
  ChevronDownIcon,
  ChevronRightIcon,
  ClockIcon,
  CodeIcon,
  FileTextIcon,
  FolderIcon,
  GamepadIcon,
  GlobeIcon,
  HelpCircleIcon,
  ImageIcon,
  InfoIcon,
  LightbulbIcon,
  LoaderIcon,
  MailIcon,
  MenuIcon,
  MessageCircleIcon,
  MessageSquarePlusIcon,
  MicIcon,
  MonitorIcon,
  MonitorSmartphoneIcon,
  MusicIcon,
  NewspaperIcon,
  PlaneIcon,
  PlayIcon,
  PlusIcon,
  SettingsIcon,
  ShoppingCartIcon,
  SmartphoneIcon,
  SparklesIcon,
  SquareIcon,
  Trash2Icon,
  UserIcon,
  WifiIcon,
  WrenchIcon,
  XCircleIcon,
  XIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

import {
  listDevices,
  submitTask,
  listTasks,
  getStats,
  startPcScreenCapture,
  stopPcScreenCapture,
  getPcScreenStats,
  listSkills,
  type TentacleDevice,
  type TaskRecord,
  type TentacleStats,
  type PcScreenStats,
  type SkillInfo,
} from "@/core/tentacle/api";
import { useScreenStream } from "@/core/tentacle/use-screen-stream";
import { usePcScreenStream } from "@/core/tentacle/use-pc-screen-stream";

// ── Types ──────────────────────────────────────────────

type Tab = "chat" | "tasks" | "skills" | "me";
type DeviceKind = "phone" | "pc" | "auto";

interface ActiveDevice {
  id: string;
  name: string;
  kind: DeviceKind;
  isLocal: boolean;
  online: boolean;
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

/** 会话：按 conversationId 区分一次完整对话 */
interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: ChatMessage[];
}

// ── Constants ──────────────────────────────────────────

const QUICK_TASKS: Array<{ icon: typeof GamepadIcon; label: string }> = [
  { icon: GlobeIcon, label: "GitHub热门项目收集" },
  { icon: GamepadIcon, label: "今天NBA的比赛情况" },
  { icon: GamepadIcon, label: "王者新版本皮肤推荐" },
  { icon: PlaneIcon, label: "曼谷旅行路书网页" },
];

const DEVICE_SUBTITLE_DEFAULT = "我的手机";

const SUGGESTED_SKILLS: Array<{
  icon: typeof SparklesIcon;
  label: string;
  tag: string;
}> = [
  { icon: SparklesIcon, label: "今日科技要闻速览", tag: "非定时" },
  { icon: BookOpenIcon, label: "快速学一个商务英语词汇", tag: "非定时" },
  { icon: LightbulbIcon, label: "冷知识盲盒", tag: "非定时" },
];

type IconType = typeof SparklesIcon;
const SKILL_ICONS: Record<string, IconType> = {
  calendar: CalendarIcon,
  mail: MailIcon,
  browser: GlobeIcon,
  settings: SettingsIcon,
  code: CodeIcon,
  app: AppWindowIcon,
  image: ImageIcon,
  music: MusicIcon,
  shopping: ShoppingCartIcon,
  news: NewspaperIcon,
  message: MessageCircleIcon,
  game: GamepadIcon,
  default: WrenchIcon,
};

const APP_NAME = "Octopus";
const APP_VERSION = "V1.0.8";

const PC_DEVICE: ActiveDevice = {
  id: "pc-host",
  name: "我的电脑",
  kind: "pc",
  isLocal: true,
  online: true,
};

// ── Helpers ────────────────────────────────────────────

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function deviceKindIcon(kind: DeviceKind) {
  return kind === "pc" ? MonitorIcon : SmartphoneIcon;
}

function pickSkillIcon(name: string): IconType {
  const lower = name.toLowerCase();
  for (const [k, icon] of Object.entries(SKILL_ICONS)) {
    if (lower.includes(k)) return icon;
  }
  return WrenchIcon;
}

function newConversationId() {
  return `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function deriveTitle(messages: ChatMessage[]): string {
  // 找第一条用户消息作为标题
  const firstUser = messages.find((m) => m.role === "user");
  if (firstUser) {
    return firstUser.content.length > 18
      ? firstUser.content.slice(0, 18) + "…"
      : firstUser.content;
  }
  return "新对话";
}

// ── Main Page ──────────────────────────────────────────

export default function MobilePage() {
  const [tab, setTab] = useState<Tab>("chat");

  // Active device (shared across tabs)
  const [activeDevice, setActiveDevice] = useState<ActiveDevice>({
    id: "",
    name: DEVICE_SUBTITLE_DEFAULT,
    kind: "phone",
    isLocal: false,
    online: true,
  });

  // Devices
  const [devices, setDevices] = useState<TentacleDevice[]>([]);
  const [pcScreenStats, setPcScreenStats] = useState<PcScreenStats | null>(null);

  // UI state
  const [deviceSwitcherOpen, setDeviceSwitcherOpen] = useState(false);
  const [devicePreviewOpen, setDevicePreviewOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Conversations (multiple chat sessions)
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string>(
    newConversationId(),
  );

  // 派生当前对话
  const activeConversation = useMemo(
    () =>
      conversations.find((c) => c.id === activeConversationId) ?? {
        id: activeConversationId,
        title: "新对话",
        createdAt: Date.now() / 1000,
        updatedAt: Date.now() / 1000,
        messages: [],
      },
    [conversations, activeConversationId],
  );

  // 提交任务记录（用于历史对话回显）
  const [taskHistory, setTaskHistory] = useState<TaskRecord[]>([]);
  const [stats, setStats] = useState<TentacleStats | null>(null);

  // Refresh
  const refresh = useCallback(async () => {
    try {
      const [d, t, s, ps] = await Promise.all([
        listDevices(),
        listTasks(),
        getStats().catch(() => null),
        getPcScreenStats().catch(() => null),
      ]);
      setDevices(d);
      setTaskHistory(t);
      setStats(s);
      setPcScreenStats(ps);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  // Switch device handler
  const handleSelectDevice = useCallback(
    (device: ActiveDevice) => {
      setActiveDevice(device);
      setDeviceSwitcherOpen(false);
      setTab("chat");
    },
    [],
  );

  // ── Conversation actions ────────────────────────────

  const createNewConversation = useCallback(() => {
    setConversations((prev) => {
      // 如果当前有内容则保存
      if (activeConversation.messages.length > 0) {
        const saved: Conversation = {
          ...activeConversation,
          title: deriveTitle(activeConversation.messages),
          updatedAt: Date.now() / 1000,
        };
        const next = [saved, ...prev.filter((c) => c.id !== saved.id)];
        return next;
      }
      return prev;
    });
    setActiveConversationId(newConversationId());
    setDrawerOpen(false);
  }, [activeConversation]);

  const selectConversation = useCallback(
    (id: string) => {
      // 先保存当前
      setConversations((prev) => {
        if (activeConversation.messages.length > 0) {
          const saved: Conversation = {
            ...activeConversation,
            title: deriveTitle(activeConversation.messages),
            updatedAt: Date.now() / 1000,
          };
          return [saved, ...prev.filter((c) => c.id !== saved.id)];
        }
        return prev;
      });
      setActiveConversationId(id);
      setDrawerOpen(false);
      setTab("chat");
    },
    [activeConversation],
  );

  const deleteConversation = useCallback((id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (id === activeConversationId) {
      setActiveConversationId(newConversationId());
    }
  }, [activeConversationId]);

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim()) return;
      const userMsg: ChatMessage = {
        id: `user-${Date.now()}`,
        role: "user",
        content: text,
        timestamp: Date.now() / 1000,
      };
      // 更新当前对话
      setConversations((prev) => {
        const existing = prev.find((c) => c.id === activeConversationId);
        if (existing) {
          return prev.map((c) =>
            c.id === activeConversationId
              ? {
                  ...c,
                  messages: [...c.messages, userMsg],
                  updatedAt: Date.now() / 1000,
                }
              : c,
          );
        }
        return prev; // activeConversation 由渲染时 fallback
      });
      // 如果当前是空对话（未在 conversations 中），需要创建
      setActiveConversationId((currId) => {
        if (currId === activeConversationId) {
          // 直接在 conversations 里建
          const newConv: Conversation = {
            id: currId,
            title: text.length > 18 ? text.slice(0, 18) + "…" : text,
            createdAt: Date.now() / 1000,
            updatedAt: Date.now() / 1000,
            messages: [userMsg],
          };
          setConversations((p) => {
            if (p.some((c) => c.id === currId)) {
              return p.map((c) =>
                c.id === currId
                  ? { ...c, messages: [...c.messages, userMsg] }
                  : c,
              );
            }
            return [newConv, ...p];
          });
        }
        return currId;
      });

      try {
        const result = await submitTask(text, activeDevice.id || undefined);
        const asstMsg: ChatMessage = {
          id: `asst-${result.task_id}`,
          role: "assistant",
          content: result.success
            ? `已执行 "${text}"，共 ${result.steps} 步，耗时 ${result.duration_ms}ms。`
            : `执行失败：${result.error || "未知错误"}`,
          timestamp: result.timestamp,
        };
        setConversations((prev) =>
          prev.map((c) =>
            c.id === activeConversationId
              ? { ...c, messages: [...c.messages, asstMsg] }
              : c,
          ),
        );
        await refresh();
      } catch (e) {
        const errMsg: ChatMessage = {
          id: `err-${Date.now()}`,
          role: "assistant",
          content: `请求失败：${e instanceof Error ? e.message : "未知错误"}`,
          timestamp: Date.now() / 1000,
        };
        setConversations((prev) =>
          prev.map((c) =>
            c.id === activeConversationId
              ? { ...c, messages: [...c.messages, errMsg] }
              : c,
          ),
        );
      }
    },
    [activeConversationId, activeDevice.id, refresh],
  );

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-gradient-to-br from-slate-200 via-slate-100 to-slate-200 p-0 sm:p-4 dark:from-slate-950 via-slate-900 to-slate-950">
      <div className="relative flex h-screen w-full max-w-[480px] flex-col overflow-hidden bg-white shadow-2xl dark:bg-slate-950 sm:h-[min(900px,calc(100vh-2rem))] sm:rounded-[2.5rem]">
        <StatusBar />

        <div className="relative flex-1 overflow-hidden">
          {tab === "chat" && (
            <ChatTab
              conversation={activeConversation}
              activeDevice={activeDevice}
              onOpenDrawer={() => setDrawerOpen(true)}
              onOpenDeviceSwitcher={() => setDeviceSwitcherOpen(true)}
              onOpenDevicePreview={() => setDevicePreviewOpen(true)}
              onSendMessage={sendMessage}
            />
          )}
          {tab === "tasks" && (
            <TasksTab
              activeDevice={activeDevice}
              tasks={taskHistory}
              stats={stats}
              onOpenDrawer={() => setDrawerOpen(true)}
              onOpenDeviceSwitcher={() => setDeviceSwitcherOpen(true)}
              onOpenDevicePreview={() => setDevicePreviewOpen(true)}
            />
          )}
          {tab === "skills" && (
            <SkillsTab
              onOpenDrawer={() => setDrawerOpen(true)}
              onOpenDeviceSwitcher={() => setDeviceSwitcherOpen(true)}
              onOpenDevicePreview={() => setDevicePreviewOpen(true)}
            />
          )}
          {tab === "me" && (
            <MeTab
              activeDevice={activeDevice}
              devices={devices}
              totalDevices={devices.length + 1}
              pcScreenStats={pcScreenStats}
              onOpenDrawer={() => setDrawerOpen(true)}
              onOpenDevicePreview={() => setDevicePreviewOpen(true)}
              onRefresh={refresh}
            />
          )}
        </div>

        <BottomTabBar tab={tab} setTab={setTab} />

        {/* Drawer (left side) */}
        <Drawer
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          conversations={conversations}
          taskHistory={taskHistory}
          activeConversationId={activeConversationId}
          onNewConversation={createNewConversation}
          onSelectConversation={selectConversation}
          onDeleteConversation={deleteConversation}
        />

        {/* Device Switcher Dropdown */}
        <DeviceSwitcher
          open={deviceSwitcherOpen}
          onClose={() => setDeviceSwitcherOpen(false)}
          devices={devices}
          activeDevice={activeDevice}
          onSelect={handleSelectDevice}
          pcScreenStats={pcScreenStats}
        />

        {/* Device Preview Bottom Sheet */}
        <DevicePreviewModal
          open={devicePreviewOpen}
          onClose={() => setDevicePreviewOpen(false)}
          devices={devices}
          activeDevice={activeDevice}
          onSelect={handleSelectDevice}
        />
      </div>
    </div>
  );
}

// ── useMemo fallback ───────────────────────────────────

import { useMemo } from "react";

// ── Status Bar (mockup) ────────────────────────────────

function StatusBar() {
  return (
    <div className="flex h-8 items-center justify-between bg-white px-4 text-xs text-slate-900 dark:bg-slate-950 dark:text-white">
      <span className="font-mono">{fmtTime(Date.now() / 1000)}</span>
      <div className="flex items-center gap-1">
        <WifiIcon className="size-3" />
        <span className="font-mono text-[10px]">5G</span>
        <div className="ml-1 flex items-center">
          <div className="h-2 w-5 rounded-sm border border-slate-900 dark:border-white">
            <div className="h-full w-4/5 rounded-sm bg-slate-900 dark:bg-white" />
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Top Bar (per-tab) ──────────────────────────────────

function TopBar({
  title,
  activeDevice,
  onOpenDrawer,
  onOpenDeviceSwitcher,
  onOpenDevicePreview,
}: {
  title?: string;
  activeDevice: ActiveDevice;
  onOpenDrawer: () => void;
  onOpenDeviceSwitcher: () => void;
  onOpenDevicePreview: () => void;
}) {
  const DeviceIcon = deviceKindIcon(activeDevice.kind);

  return (
    <div className="flex items-center justify-between border-b border-slate-100 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-950">
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenDrawer}
          className="rounded-lg p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800"
          aria-label="打开侧边栏"
        >
          <MenuIcon className="size-5" />
        </button>
        <div>
          <h1 className="text-lg font-bold leading-tight">
            {title ?? APP_NAME}
          </h1>
          <button
            onClick={onOpenDeviceSwitcher}
            className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
          >
            <span
              className={cn(
                "size-1.5 rounded-full",
                activeDevice.online ? "bg-green-500" : "bg-slate-300",
              )}
            />
            <DeviceIcon className="size-3" />
            {activeDevice.name}
            <ChevronDownIcon className="size-3" />
          </button>
        </div>
      </div>

      <button
        onClick={onOpenDevicePreview}
        className="relative rounded-lg p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800"
        title="设备预览"
      >
        <MonitorSmartphoneIcon className="size-5" />
        {activeDevice.kind === "pc" && (
          <span className="absolute right-0.5 top-0.5 size-2 animate-pulse rounded-full bg-green-500" />
        )}
      </button>
    </div>
  );
}

// ── Drawer (left sidebar) ──────────────────────────────

function Drawer({
  open,
  onClose,
  conversations,
  taskHistory,
  activeConversationId,
  onNewConversation,
  onSelectConversation,
  onDeleteConversation,
}: {
  open: boolean;
  onClose: () => void;
  conversations: Conversation[];
  taskHistory: TaskRecord[];
  activeConversationId: string;
  onNewConversation: () => void;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string, e: React.MouseEvent) => void;
}) {
  if (!open) return null;

  // 历史对话列表：合并本地会话 + 已完成任务
  const recentList: Array<{
    id: string;
    title: string;
    updatedAt: number;
    source: "local" | "task";
    isActive: boolean;
  }> = [
    ...conversations.map((c) => ({
      id: c.id,
      title: c.title,
      updatedAt: c.updatedAt,
      source: "local" as const,
      isActive: c.id === activeConversationId,
    })),
    ...taskHistory.slice(0, 8).map((t) => ({
      id: t.task_id,
      title: t.task.length > 18 ? t.task.slice(0, 18) + "…" : t.task,
      updatedAt: t.timestamp,
      source: "task" as const,
      isActive: false,
    })),
  ]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, 12);

  return (
    <>
      {/* Backdrop */}
      <div
        className="absolute inset-0 z-40 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />
      {/* Drawer panel */}
      <div className="absolute left-0 top-0 z-50 flex h-full w-[78%] max-w-[360px] flex-col overflow-hidden bg-white shadow-2xl dark:bg-slate-900 animate-in slide-in-from-left duration-200">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-bold">{APP_NAME}</h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1 hover:bg-slate-100 dark:hover:bg-slate-800"
            aria-label="关闭"
          >
            <XIcon className="size-4" />
          </button>
        </div>

        <ScrollArea className="flex-1">
          <div className="space-y-1 px-2 py-3">
            {/* 新建对话 */}
            <button
              onClick={onNewConversation}
              className="flex w-full items-center gap-3 rounded-xl bg-slate-50 px-3 py-3 text-left transition-colors hover:bg-slate-100 dark:bg-slate-800 dark:hover:bg-slate-700"
            >
              <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-slate-900 text-white dark:bg-white dark:text-slate-900">
                <MessageSquarePlusIcon className="size-3.5" />
              </div>
              <span className="flex-1 text-sm font-medium">新建对话</span>
            </button>

            {/* 快捷入口（参照 Marvis 截图） */}
            <DrawerEntry
              icon={BriefcaseIcon}
              label="办公室"
              onClick={onClose}
            />
            <DrawerEntry
              icon={FileTextIcon}
              label="产出物"
              onClick={onClose}
            />

            {/* 最近对话 */}
            {recentList.length > 0 && (
              <>
                <div className="px-2 pb-1 pt-4 text-[10px] font-medium uppercase tracking-wider text-slate-400">
                  最近对话
                </div>
                {recentList.map((c) => (
                  <button
                    key={`${c.source}-${c.id}`}
                    onClick={() =>
                      c.source === "local"
                        ? onSelectConversation(c.id)
                        : onNewConversation()
                    }
                    className={cn(
                      "group flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors",
                      c.isActive
                        ? "bg-blue-50 dark:bg-blue-500/10"
                        : "hover:bg-slate-50 dark:hover:bg-slate-800",
                    )}
                  >
                    <MessageCircleIcon
                      className={cn(
                        "size-3.5 shrink-0",
                        c.isActive
                          ? "text-blue-500"
                          : "text-slate-400",
                      )}
                    />
                    <span
                      className={cn(
                        "flex-1 truncate text-[13px]",
                        c.isActive
                          ? "font-medium text-blue-600 dark:text-blue-400"
                          : "text-slate-700 dark:text-slate-300",
                      )}
                    >
                      {c.title}
                    </span>
                    {c.source === "local" && (
                      <button
                        onClick={(e) => onDeleteConversation(c.id, e)}
                        className="opacity-0 transition-opacity hover:text-red-500 group-hover:opacity-100"
                        title="删除对话"
                      >
                        <Trash2Icon className="size-3 text-slate-400" />
                      </button>
                    )}
                    <ChevronRightIcon className="size-3 shrink-0 text-slate-300" />
                  </button>
                ))}
              </>
            )}
          </div>
        </ScrollArea>
      </div>
    </>
  );
}

function DrawerEntry({
  icon: Icon,
  label,
  onClick,
}: {
  icon: typeof BriefcaseIcon;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-slate-50 dark:hover:bg-slate-800"
    >
      <Icon className="size-4 text-slate-500 dark:text-slate-400" />
      <span className="flex-1 text-sm">{label}</span>
      <ChevronRightIcon className="size-3.5 text-slate-300" />
    </button>
  );
}

// ── Device Switcher Dropdown ───────────────────────────

function DeviceSwitcher({
  open,
  onClose,
  devices,
  activeDevice,
  onSelect,
  pcScreenStats,
}: {
  open: boolean;
  onClose: () => void;
  devices: TentacleDevice[];
  activeDevice: ActiveDevice;
  onSelect: (d: ActiveDevice) => void;
  pcScreenStats: PcScreenStats | null;
}) {
  if (!open) return null;

  return (
    <>
      <div
        className="absolute inset-0 z-40 bg-black/20"
        onClick={onClose}
      />
      <div className="absolute left-3 right-3 top-[72px] z-50 overflow-hidden rounded-xl border border-slate-100 bg-white shadow-xl dark:border-slate-800 dark:bg-slate-900">
        <div className="px-3 py-2 text-[10px] font-medium uppercase tracking-wide text-slate-400">
          切换设备
        </div>
        <div className="max-h-56 overflow-y-auto">
          <DeviceItem
            icon={SparklesIcon}
            label="自动选择"
            sub="根据任务自动分配设备"
            active={activeDevice.id === ""}
            online={true}
            onClick={() =>
              onSelect({
                id: "",
                name: DEVICE_SUBTITLE_DEFAULT,
                kind: "phone",
                isLocal: false,
                online: true,
              })
            }
          />
          <DeviceItem
            icon={MonitorIcon}
            label="我的电脑"
            sub={
              pcScreenStats?.running
                ? "PC屏幕流运行中"
                : "PC屏幕流未启动"
            }
            active={activeDevice.id === "pc-host"}
            online={true}
            onClick={() => onSelect(PC_DEVICE)}
          />
          {devices.length > 0 && (
            <div className="px-3 py-1.5 text-[10px] uppercase tracking-wide text-slate-300">
              其他设备
            </div>
          )}
          {devices.map((d) => (
            <DeviceItem
              key={d.tentacle_id}
              icon={SmartphoneIcon}
              label={d.tentacle_id}
              sub={`${d.platform} · ${d.total_capabilities} skills`}
              active={activeDevice.id === d.tentacle_id}
              online={d.is_online}
              onClick={() =>
                onSelect({
                  id: d.tentacle_id,
                  name: d.tentacle_id,
                  kind: "phone",
                  isLocal: false,
                  online: d.is_online,
                })
              }
            />
          ))}
        </div>
      </div>
    </>
  );
}

function DeviceItem({
  icon: Icon,
  label,
  sub,
  active,
  online,
  onClick,
}: {
  icon: typeof SparklesIcon;
  label: string;
  sub?: string;
  active: boolean;
  online: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors",
        active
          ? "bg-blue-50 dark:bg-blue-500/10"
          : "hover:bg-slate-50 dark:hover:bg-slate-800",
      )}
    >
      <div
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-lg",
          active
            ? "bg-blue-500 text-white"
            : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
        )}
      >
        <Icon className="size-3.5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-medium leading-tight">
          {label}
        </div>
        {sub && (
          <div className="truncate text-[10px] text-slate-400">{sub}</div>
        )}
      </div>
      <div className="flex items-center gap-1.5">
        <span
          className={cn(
            "size-1.5 rounded-full",
            online ? "bg-green-500" : "bg-slate-300",
          )}
        />
        {active && <CheckCircle2Icon className="size-3.5 text-blue-500" />}
      </div>
    </button>
  );
}

// ── Device Preview Modal (Bottom Sheet) ────────────────

function DevicePreviewModal({
  open,
  onClose,
  devices,
  activeDevice,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  devices: TentacleDevice[];
  activeDevice: ActiveDevice;
  onSelect: (d: ActiveDevice) => void;
}) {
  if (!open) return null;

  return (
    <>
      <div
        className="absolute inset-0 z-40 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="absolute bottom-0 left-0 right-0 z-50 max-h-[60%] overflow-hidden rounded-t-3xl bg-white shadow-2xl dark:bg-slate-900 animate-in slide-in-from-bottom duration-200">
        <div className="flex justify-center pt-2 pb-1">
          <div className="h-1 w-10 rounded-full bg-slate-300 dark:bg-slate-700" />
        </div>
        <div className="flex items-center justify-between px-4 pb-2">
          <h3 className="text-sm font-semibold">选择设备</h3>
          <button
            onClick={onClose}
            className="rounded-lg p-1 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <XIcon className="size-4" />
          </button>
        </div>

        <ScrollArea className="max-h-[40vh]">
          <div className="space-y-1.5 px-3 pb-4">
            <PreviewCard
              icon={MonitorIcon}
              label="我的电脑"
              sub="PC Agent · Octopus Brain"
              onEnter={() => {
                onSelect(PC_DEVICE);
                onClose();
              }}
            />
            {devices.length === 0 ? (
              <PreviewCard
                icon={SmartphoneIcon}
                label="未连接手机设备"
                sub="请运行 python -m runtime.tentacle.mobile.run_server"
                disabled
              />
            ) : (
              devices.map((d) => (
                <PreviewCard
                  key={d.tentacle_id}
                  icon={SmartphoneIcon}
                  label={d.tentacle_id}
                  sub={`${d.platform} · ${d.total_capabilities} skills · ${d.is_online ? "在线" : "离线"}`}
                  online={d.is_online}
                  onEnter={() => {
                    onSelect({
                      id: d.tentacle_id,
                      name: d.tentacle_id,
                      kind: "phone",
                      isLocal: false,
                      online: d.is_online,
                    });
                    onClose();
                  }}
                />
              ))
            )}
          </div>
        </ScrollArea>
      </div>
    </>
  );
}

function PreviewCard({
  icon: Icon,
  label,
  sub,
  online,
  disabled,
  onEnter,
}: {
  icon: typeof MonitorIcon;
  label: string;
  sub: string;
  online?: boolean;
  disabled?: boolean;
  onEnter?: () => void;
}) {
  return (
    <button
      onClick={disabled ? undefined : onEnter}
      disabled={disabled}
      className={cn(
        "group flex w-full items-center gap-2.5 overflow-hidden rounded-xl border p-2.5 text-left transition-colors",
        disabled
          ? "border-dashed border-slate-200 bg-slate-50 opacity-60 dark:border-slate-800 dark:bg-slate-950"
          : "border-slate-200 bg-white hover:border-blue-500 hover:bg-blue-50/50 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-blue-500/10",
      )}
    >
      <div className="relative flex size-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-700">
        <Icon className="size-4" />
        {online !== undefined && (
          <span
            className={cn(
              "absolute -right-0.5 -top-0.5 size-2.5 rounded-full border-2 border-white dark:border-slate-800",
              online ? "bg-green-500" : "bg-slate-300",
            )}
          />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-medium leading-tight">
          {label}
        </div>
        <div className="truncate text-[10px] text-slate-400">{sub}</div>
      </div>
      <div
        className={cn(
          "rounded-full px-2.5 py-0.5 text-[10px] font-medium transition-colors",
          disabled
            ? "bg-slate-100 text-slate-400 dark:bg-slate-700"
            : "bg-slate-900 text-white group-hover:bg-blue-500 dark:bg-white dark:text-slate-900",
        )}
      >
        {disabled ? "未连接" : "进入"}
      </div>
    </button>
  );
}

// ── Bottom Tab Bar ─────────────────────────────────────

function BottomTabBar({
  tab,
  setTab,
}: {
  tab: Tab;
  setTab: (t: Tab) => void;
}) {
  const tabs: Array<{ key: Tab; label: string; icon: typeof MessageCircleIcon }> = [
    { key: "chat", label: "对话", icon: MessageCircleIcon },
    { key: "tasks", label: "任务", icon: ClockIcon },
    { key: "skills", label: "技能", icon: WrenchIcon },
    { key: "me", label: "我的", icon: UserIcon },
  ];

  return (
    <div className="border-t border-slate-100 bg-white px-2 py-2 dark:border-slate-800 dark:bg-slate-950">
      <div className="flex items-center justify-around">
        {tabs.map(({ key, label, icon: Icon }) => {
          const active = tab === key;
          return (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={cn(
                "flex flex-1 flex-col items-center gap-1 rounded-lg py-1 transition-colors",
                active
                  ? "text-slate-900 dark:text-white"
                  : "text-slate-400 dark:text-slate-500",
              )}
            >
              <Icon
                className={cn(
                  "size-5",
                  active && "fill-slate-900 dark:fill-white",
                )}
              />
              <span className="text-[11px] font-medium">{label}</span>
            </button>
          );
        })}
      </div>
      <div className="mx-auto mt-1 h-1 w-32 rounded-full bg-slate-300 dark:bg-slate-700" />
    </div>
  );
}

// ════════════════════════════════════════════════════════
// Tab 1: 对话 (Chat)
// ════════════════════════════════════════════════════════

function ChatTab({
  conversation,
  activeDevice,
  onOpenDrawer,
  onOpenDeviceSwitcher,
  onOpenDevicePreview,
  onSendMessage,
}: {
  conversation: Conversation;
  activeDevice: ActiveDevice;
  onOpenDrawer: () => void;
  onOpenDeviceSwitcher: () => void;
  onOpenDevicePreview: () => void;
  onSendMessage: (text: string) => Promise<void>;
}) {
  const [input, setInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const phoneCanvasRef = useRef<HTMLCanvasElement>(null);
  const pcCanvasRef = useRef<HTMLCanvasElement>(null);
  const phoneStream = useScreenStream(
    activeDevice.kind === "phone" && activeDevice.id
      ? activeDevice.id
      : null,
    phoneCanvasRef,
  );
  const pcStream = usePcScreenStream(pcCanvasRef);

  const showWelcome = conversation.messages.length === 0;
  const isPc = activeDevice.kind === "pc";

  const send = useCallback(
    async (text: string) => {
      if (!text.trim() || submitting) return;
      setInput("");
      setSubmitting(true);
      try {
        await onSendMessage(text);
      } finally {
        setSubmitting(false);
      }
    },
    [submitting, onSendMessage],
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  return (
    <>
      <TopBar
        activeDevice={activeDevice}
        onOpenDrawer={onOpenDrawer}
        onOpenDeviceSwitcher={onOpenDeviceSwitcher}
        onOpenDevicePreview={onOpenDevicePreview}
      />

      <div className="flex h-[calc(100%-3.5rem-3.5rem-2.5rem)] flex-col overflow-hidden">
        <ScrollArea className="flex-1">
          {showWelcome ? (
            <div className="flex flex-col gap-6 px-4 py-8">
              <div className="flex justify-center">
                <div className="size-20 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                  <img
                    src="/images/octopus.svg"
                    alt="avatar"
                    className="size-full"
                  />
                </div>
              </div>

              <h2 className="text-center text-2xl font-semibold">
                你好，今天想做什么？
              </h2>

              <div className="space-y-3">
                {QUICK_TASKS.map((task, i) => {
                  const Icon = task.icon;
                  return (
                    <button
                      key={i}
                      onClick={() => send(task.label)}
                      className="flex w-full items-center gap-3 rounded-2xl border border-slate-100 bg-white px-4 py-3.5 text-left transition-colors hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:hover:bg-slate-800"
                    >
                      <Icon className="size-5 shrink-0" />
                      <span className="text-sm">{task.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="space-y-3 px-4 py-4">
              {conversation.messages.map((msg) => (
                <MessageBubble key={msg.id} message={msg} />
              ))}
              {submitting && (
                <div className="flex items-center gap-2 px-2 text-sm text-slate-500">
                  <LoaderIcon className="size-4 animate-spin" />
                  Octopus 正在思考...
                </div>
              )}
            </div>
          )}
        </ScrollArea>

        <div className="border-t border-slate-100 bg-white px-3 py-3 dark:border-slate-800 dark:bg-slate-950">
          <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 dark:border-slate-700 dark:bg-slate-900">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                isPc
                  ? "请输入任务，Octopus Brain 将调度PC Agent执行"
                  : "请在此输入任务"
              }
              disabled={submitting}
              className="flex-1 border-0 bg-transparent px-0 text-sm shadow-none focus-visible:ring-0 focus-visible:ring-offset-0"
            />
            <button className="shrink-0 text-slate-400 hover:text-slate-600">
              <MicIcon className="size-5" />
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
          isUser
            ? "bg-slate-900 text-white dark:bg-white dark:text-slate-900"
            : "bg-slate-100 text-slate-900 dark:bg-slate-800 dark:text-white",
        )}
      >
        <div className="whitespace-pre-wrap break-words">{message.content}</div>
        <div className="mt-1 text-[10px] text-slate-400">
          {fmtTime(message.timestamp)}
        </div>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════
// Tab 2: 任务 (Tasks)
// ════════════════════════════════════════════════════════

function TasksTab({
  activeDevice,
  tasks,
  onOpenDrawer,
  onOpenDeviceSwitcher,
  onOpenDevicePreview,
}: {
  activeDevice: ActiveDevice;
  tasks: TaskRecord[];
  stats: TentacleStats | null;
  onOpenDrawer: () => void;
  onOpenDeviceSwitcher: () => void;
  onOpenDevicePreview: () => void;
}) {
  const showEmpty = tasks.length === 0;

  return (
    <>
      <TopBar
        title="自动任务"
        activeDevice={activeDevice}
        onOpenDrawer={onOpenDrawer}
        onOpenDeviceSwitcher={onOpenDeviceSwitcher}
        onOpenDevicePreview={onOpenDevicePreview}
      />
      <ScrollArea className="h-[calc(100%-3.5rem-3.5rem-2.5rem)]">
        <div className="space-y-4 px-4 py-6">
          {showEmpty ? (
            <div className="flex flex-col items-center justify-center gap-6 py-16">
              <h3 className="text-lg font-medium">开启你的第一个自动任务吧</h3>
              <Button
                size="lg"
                className="h-12 rounded-full bg-slate-900 px-6 text-sm font-medium text-white hover:bg-slate-800 dark:bg-white dark:text-slate-900"
              >
                <PlusIcon className="size-4" />
                新建自动任务
              </Button>

              <div className="mt-12 w-full space-y-3">
                <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300">
                  推荐任务
                </h4>
                {SUGGESTED_SKILLS.map((task, i) => {
                  const Icon = task.icon;
                  return (
                    <div
                      key={i}
                      className="flex items-center gap-3 rounded-2xl bg-slate-50 px-4 py-3.5 dark:bg-slate-900"
                    >
                      <Icon className="size-5 shrink-0 text-slate-600 dark:text-slate-400" />
                      <span className="flex-1 text-sm">{task.label}</span>
                      <span className="text-xs text-slate-400">{task.tag}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {tasks.map((task) => (
                <div
                  key={task.task_id}
                  className="rounded-2xl border border-slate-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900"
                >
                  <div className="flex items-start gap-3">
                    {task.success ? (
                      <CheckCircle2Icon className="size-5 shrink-0 text-green-500" />
                    ) : (
                      <XCircleIcon className="size-5 shrink-0 text-red-500" />
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium">{task.task}</div>
                      <div className="mt-1 text-[11px] text-slate-500">
                        {fmtTime(task.timestamp)} · {task.steps} 步 ·{" "}
                        {task.duration_ms}ms
                      </div>
                      {task.error && (
                        <div className="mt-1 text-xs text-red-500">
                          {task.error}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </ScrollArea>
    </>
  );
}

// ════════════════════════════════════════════════════════
// Tab 3: 技能 (Skills)
// ════════════════════════════════════════════════════════

function SkillsTab({
  onOpenDrawer,
  onOpenDeviceSwitcher,
  onOpenDevicePreview,
}: {
  onOpenDrawer: () => void;
  onOpenDeviceSwitcher: () => void;
  onOpenDevicePreview: () => void;
}) {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listSkills()
      .then((s) => setSkills(s))
      .catch(() => setSkills([]))
      .finally(() => setLoading(false));
  }, []);

  const defaultDevice: ActiveDevice = {
    id: "",
    name: DEVICE_SUBTITLE_DEFAULT,
    kind: "phone",
    isLocal: false,
    online: true,
  };

  return (
    <>
      <TopBar
        title="我的技能"
        activeDevice={defaultDevice}
        onOpenDrawer={onOpenDrawer}
        onOpenDeviceSwitcher={onOpenDeviceSwitcher}
        onOpenDevicePreview={onOpenDevicePreview}
      />
      <ScrollArea className="h-[calc(100%-3.5rem-3.5rem-2.5rem)]">
        <div className="space-y-2 px-4 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <LoaderIcon className="size-6 animate-spin text-slate-400" />
            </div>
          ) : skills.length === 0 ? (
            <div className="py-12 text-center text-sm text-slate-400">
              暂无可用技能
            </div>
          ) : (
            skills.map((skill) => {
              const Icon = pickSkillIcon(skill.name);
              return (
                <div
                  key={skill.name}
                  className="flex items-center gap-3 rounded-2xl border border-slate-100 bg-white p-3.5 dark:border-slate-800 dark:bg-slate-900"
                >
                  <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 dark:bg-slate-800">
                    <Icon className="size-5 text-slate-700 dark:text-slate-300" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium">
                      {skill.name}
                    </div>
                    {skill.description && (
                      <div className="truncate text-[11px] text-slate-500">
                        {skill.description}
                      </div>
                    )}
                  </div>
                  <ChevronRightIcon className="size-4 shrink-0 text-slate-300" />
                </div>
              );
            })
          )}
        </div>
      </ScrollArea>
    </>
  );
}

// ════════════════════════════════════════════════════════
// Tab 4: 我的 (Me)
// ════════════════════════════════════════════════════════

function MeTab({
  activeDevice,
  totalDevices,
  pcScreenStats,
  onOpenDrawer,
  onOpenDevicePreview,
  onRefresh,
}: {
  activeDevice: ActiveDevice;
  devices: TentacleDevice[];
  totalDevices: number;
  pcScreenStats: PcScreenStats | null;
  onOpenDrawer: () => void;
  onOpenDevicePreview: () => void;
  onRefresh: () => Promise<void>;
}) {
  return (
    <>
      <div className="flex items-center justify-between border-b border-slate-100 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-950">
        <div className="flex items-center gap-3">
          <button
            onClick={onOpenDrawer}
            className="rounded-lg p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <MenuIcon className="size-5" />
          </button>
          <h1 className="text-lg font-bold leading-tight">我的</h1>
        </div>
      </div>

      <ScrollArea className="h-[calc(100%-3.5rem-3.5rem-2.5rem)]">
        <div className="space-y-3 px-4 py-4">
          <div className="flex items-center gap-3 px-2 py-2">
            <div className="size-10 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
              <div className="flex size-full items-center justify-center text-sm font-medium">
                登
              </div>
            </div>
            <div className="text-sm font-medium">登华</div>
          </div>

          <div className="rounded-2xl border border-slate-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="flex items-center gap-3">
              <div className="size-16 overflow-hidden rounded-xl bg-slate-100 dark:bg-slate-800">
                <img
                  src="/images/octopus.svg"
                  alt="logo"
                  className="size-full"
                />
              </div>
              <div className="flex-1">
                <div className="text-base font-bold">{APP_NAME}</div>
                <div className="text-xs text-slate-500">
                  为你24小时在线，有问题随时来找我吧。
                </div>
              </div>
            </div>

            <div className="mt-4 space-y-3">
              <MeRow
                icon={WrenchIcon}
                label="我的技能"
                onClick={() => {}}
              />
              <MeRow
                icon={MonitorSmartphoneIcon}
                label="管理我的设备"
                rightText={`已连接 ${totalDevices} 台设备`}
                onClick={onOpenDevicePreview}
              />
              <div className="flex items-center gap-3 rounded-xl bg-slate-50 px-3 py-2.5 text-xs dark:bg-slate-800">
                <span className="size-1.5 rounded-full bg-green-500" />
                <span className="text-slate-500">当前:</span>
                <span className="font-medium">{activeDevice.name}</span>
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <MonitorIcon className="size-4" />
                <span className="text-sm font-medium">PC 屏幕流</span>
              </div>
              <div
                className={cn(
                  "text-[11px]",
                  pcScreenStats?.running
                    ? "text-green-500"
                    : "text-slate-400",
                )}
              >
                {pcScreenStats?.running ? "运行中" : "未启动"}
              </div>
            </div>
            <Button
              variant={pcScreenStats?.running ? "outline" : "default"}
              className="w-full"
              onClick={async () => {
                if (pcScreenStats?.running) {
                  await stopPcScreenCapture();
                } else {
                  await startPcScreenCapture({ fps: 10 });
                }
                await onRefresh();
              }}
            >
              {pcScreenStats?.running ? (
                <>
                  <SquareIcon className="size-4" />
                  停止
                </>
              ) : (
                <>
                  <PlayIcon className="size-4" />
                  启动
                </>
              )}
            </Button>
          </div>

          <div className="rounded-2xl border border-slate-100 bg-white dark:border-slate-800 dark:bg-slate-900">
            <MeRow icon={HelpCircleIcon} label="帮助与反馈" onClick={() => {}} />
            <hr className="mx-4 border-slate-100 dark:border-slate-800" />
            <MeRow
              icon={InfoIcon}
              label="关于"
              rightText={APP_VERSION}
              onClick={() => {}}
            />
          </div>

          <button className="w-full rounded-2xl bg-white py-3.5 text-sm font-medium text-red-500 hover:bg-red-50 dark:bg-slate-900 dark:hover:bg-red-500/10">
            退出登录
          </button>
        </div>
      </ScrollArea>
    </>
  );
}

function MeRow({
  icon: Icon,
  label,
  rightText,
  onClick,
}: {
  icon: typeof WrenchIcon;
  label: string;
  rightText?: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-3 px-1 py-2 text-left"
    >
      <Icon className="size-4 shrink-0 text-slate-600 dark:text-slate-400" />
      <span className="flex-1 text-sm">{label}</span>
      {rightText && (
        <span className="text-xs text-slate-400">{rightText}</span>
      )}
      <ChevronRightIcon className="size-4 text-slate-300" />
    </button>
  );
}
