import { useSyncExternalStore } from "react";

export type WorkbenchBuiltinIcon =
  | "projects"
  | "trading"
  | "design"
  | "intelligence"
  | "community";

export interface WorkbenchBuiltinApp {
  id: string;
  moduleId: string;
  name: string;
  description: string;
  workspaceRoute: string;
  launchUrl: string;
  icon: WorkbenchBuiltinIcon;
}

/** Native EchoAI pages that can also live in the browser desktop and Dock. */
export const WORKBENCH_BUILTIN_APPS: readonly WorkbenchBuiltinApp[] = [
  {
    id: "projects",
    moduleId: "projects",
    name: "项目管理",
    description: "里程碑、风险与项目协作",
    workspaceRoute: "/workspace/projects",
    launchUrl: "octopus://workspace/projects",
    icon: "projects",
  },
  {
    id: "paper-trading",
    moduleId: "paper.trading",
    name: "模拟炒股",
    description: "策略验证与模拟交易",
    workspaceRoute: "/workspace/paper-trading",
    launchUrl: "octopus://workspace/paper-trading",
    icon: "trading",
  },
  {
    id: "design",
    moduleId: "design",
    name: "设计画布",
    description: "视觉创作、素材编排与设计工作流",
    workspaceRoute: "/workspace/design",
    launchUrl: "octopus://workspace/design",
    icon: "design",
  },
  {
    id: "intelligence",
    moduleId: "intelligence",
    name: "订阅",
    description: "持续跟踪主题与情报",
    workspaceRoute: "/workspace/intelligence?surface=chat",
    launchUrl: "octopus://workspace/intelligence",
    icon: "intelligence",
  },
  {
    id: "community",
    moduleId: "community",
    name: "发现社区",
    description: "发现并复用社区工作流",
    workspaceRoute: "/workspace/community",
    launchUrl: "octopus://workspace/community",
    icon: "community",
  },
];

export interface WorkspaceWebShortcut {
  id: string;
  name: string;
  url: string;
  logoUrl?: string;
}

export function workspaceWebAppRoute(shortcut: {
  url: string;
  name?: string;
}): string {
  const params = new URLSearchParams({ url: shortcut.url });
  if (shortcut.name) params.set("title", shortcut.name);
  return `/workspace/web-app?${params.toString()}`;
}

const STORAGE_KEY = "octopus:workbench:workspace-web-shortcuts.v1";
const CHANGE_EVENT = "octopus:workbench-web-shortcuts-changed";
const EMPTY_SHORTCUTS: readonly WorkspaceWebShortcut[] = [];
let cache: readonly WorkspaceWebShortcut[] | null = null;

function isWebUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function shortcutId(url: string): string {
  return `web:${url}`;
}

function sanitizeShortcut(value: unknown): WorkspaceWebShortcut | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<WorkspaceWebShortcut>;
  const name = typeof candidate.name === "string" ? candidate.name.trim() : "";
  const url = typeof candidate.url === "string" ? candidate.url.trim() : "";
  if (!name || !isWebUrl(url)) return null;
  const logoUrl =
    typeof candidate.logoUrl === "string" && isWebUrl(candidate.logoUrl)
      ? candidate.logoUrl
      : undefined;
  return {
    id: shortcutId(url),
    name: name.slice(0, 80),
    url,
    ...(logoUrl ? { logoUrl } : {}),
  };
}

function readShortcuts(): readonly WorkspaceWebShortcut[] {
  if (cache) return cache;
  if (typeof window === "undefined") return EMPTY_SHORTCUTS;
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "[]");
    const items = Array.isArray(parsed)
      ? parsed
          .map(sanitizeShortcut)
          .filter((item): item is WorkspaceWebShortcut => Boolean(item))
      : [];
    cache = Array.from(new Map(items.map((item) => [item.url, item])).values());
  } catch {
    cache = [];
  }
  return cache;
}

function emitChange(): void {
  cache = null;
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function writeShortcuts(items: readonly WorkspaceWebShortcut[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    emitChange();
  } catch {
    // Private browsing or a full storage quota should not break navigation.
  }
}

export function setWorkspaceWebShortcut(
  shortcut: Omit<WorkspaceWebShortcut, "id">,
  pinned: boolean,
): void {
  if (typeof window === "undefined") return;
  const clean = sanitizeShortcut(shortcut);
  if (!clean) return;
  const current = readShortcuts();
  const next = pinned
    ? [...current.filter((item) => item.url !== clean.url), clean]
    : current.filter((item) => item.url !== clean.url);
  writeShortcuts(next);
}

function subscribe(listener: () => void): () => void {
  const onChange = () => {
    cache = null;
    listener();
  };
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) onChange();
  };
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

export function useWorkspaceWebShortcuts(): readonly WorkspaceWebShortcut[] {
  return useSyncExternalStore(subscribe, readShortcuts, () => EMPTY_SHORTCUTS);
}

export function resetWorkspaceWebShortcutCache(): void {
  cache = null;
}
