/**
 * 宠物全局设置。
 *
 * 宠物 = 助手（octopus）的人格化形象，设置入口放在助手对话页 header。
 * 配置经 localStorage 持久化，跨标签页 + 同页多组件（header 开关面板 /
 * ChatComposer 渲染处）经 useSyncExternalStore 实时同步。
 */
import { useSyncExternalStore } from "react";

export interface PetSettings {
  /** 是否在输入框角落显示宠物。 */
  visible: boolean;
}

const STORAGE_KEY = "octopus.pet.settings";
const DEFAULT_SETTINGS: PetSettings = { visible: true };

let cache: PetSettings | null = null;
const listeners = new Set<() => void>();

function readStored(): PetSettings {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<PetSettings>;
    return { ...DEFAULT_SETTINGS, ...parsed };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function getSnapshot(): PetSettings {
  if (cache) return cache;
  if (typeof window === "undefined") return DEFAULT_SETTINGS;
  cache = readStored();
  return cache;
}

function notify(): void {
  for (const listener of listeners) listener();
}

/** 合并式更新并通知所有订阅者（含跨标签页）。 */
export function setPetSettings(patch: Partial<PetSettings>): void {
  const next = { ...getSnapshot(), ...patch };
  cache = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* localStorage 不可用（隐私模式等）——仅本次会话生效 */
  }
  notify();
}

function handleStorage(event: StorageEvent): void {
  if (event.key === STORAGE_KEY) {
    cache = null; // 强制重读，保证跨标签页一致
    notify();
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", handleStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", handleStorage);
  };
}

/** 订阅宠物设置；SSR 下返回默认值。 */
export function usePetSettings(): PetSettings {
  return useSyncExternalStore(subscribe, getSnapshot, () => DEFAULT_SETTINGS);
}

/** 读取当前宠物设置（非 hook，供事件回调等场景）。 */
export function getPetSettings(): PetSettings {
  return getSnapshot();
}
