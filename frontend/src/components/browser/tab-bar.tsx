/* Implementation note. */

import { PlusIcon, XIcon, Loader2Icon, GlobeIcon } from "lucide-react";
import { useState, type DragEvent, type MouseEvent } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { useBrowserStore } from "./browser-store";

export function TabBar() {
  const { t } = useI18n();
  const tb = t.browser.tabBar;
  const { state, openTab, closeTab, activateTab, reorderTab } =
    useBrowserStore();
  const [dragId, setDragId] = useState<string | null>(null);
  const [dragOverIdx, setDragOverIdx] = useState<number | null>(null);

  const handleAuxClick = (e: MouseEvent, id: string) => {
    if (e.button === 1) {
      e.preventDefault();
      closeTab(id);
    }
  };

  const handleDragStart = (e: DragEvent, id: string) => {
    setDragId(id);
    e.dataTransfer.effectAllowed = "move";
    // Implementation note.
    e.dataTransfer.setData("text/plain", id);
  };

  const handleDragOver = (e: DragEvent, idx: number) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOverIdx(idx);
  };

  const handleDrop = (e: DragEvent, toIdx: number) => {
    e.preventDefault();
    if (!dragId) return;
    const fromIdx = state.tabs.findIndex((t) => t.id === dragId);
    if (fromIdx >= 0 && fromIdx !== toIdx) {
      reorderTab(fromIdx, toIdx);
    }
    setDragId(null);
    setDragOverIdx(null);
  };

  const handleDragEnd = () => {
    setDragId(null);
    setDragOverIdx(null);
  };

  return (
    <div
      className="flex h-8 min-w-0 flex-1 items-center gap-1 overflow-x-auto bg-transparent px-0"
      // Implementation note.
      // Implementation note.
      style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
      // Implementation note.
      onWheel={(e) => {
        if (e.deltaY === 0) return;
        e.currentTarget.scrollLeft += e.deltaY;
      }}
    >
      {state.tabs.map((tab, idx) => {
        const active = state.activeId === tab.id;
        const dragOver = dragOverIdx === idx && dragId !== tab.id;
        return (
          <div
            key={tab.id}
            draggable
            onDragStart={(e) => handleDragStart(e, tab.id)}
            onDragOver={(e) => handleDragOver(e, idx)}
            onDrop={(e) => handleDrop(e, idx)}
            onDragEnd={handleDragEnd}
            onClick={() => activateTab(tab.id)}
            onAuxClick={(e) => handleAuxClick(e, tab.id)}
            className={cn(
              "group relative flex h-8 min-w-[132px] max-w-[220px] cursor-pointer items-center gap-2 rounded-[14px] border px-2.5 text-[12px] transition-[background-color,border-color,box-shadow,color]",
              active
                ? "border-white/65 bg-white/72 text-foreground shadow-[inset_0_1px_1px_rgba(255,255,255,0.72),0_8px_20px_rgba(15,23,42,0.08)] ring-1 ring-black/5"
                : "border-transparent bg-white/20 text-muted-foreground hover:border-white/45 hover:bg-white/46 hover:text-foreground",
              dragOver && "ring-2 ring-primary ring-offset-0",
            )}
            // Implementation note.
            // Implementation note.
            style={
              {
                flex: "0 1 220px",
                WebkitAppRegion: "no-drag",
              } as React.CSSProperties
            }
            title={tab.title || tab.url}
          >
            {tab.isLoading ? (
              <Loader2Icon className="size-3.5 shrink-0 animate-spin" />
            ) : tab.favicon ? (
              <img
                src={tab.favicon}
                alt=""
                className="size-3.5 shrink-0"
                onError={(e) => (e.currentTarget.style.display = "none")}
              />
            ) : (
              <GlobeIcon className="size-3.5 shrink-0 opacity-60" />
            )}
            <span className="min-w-0 flex-1 truncate">
              {tab.title || tab.url}
            </span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                closeTab(tab.id);
              }}
              className="grid size-4 shrink-0 place-items-center rounded text-muted-foreground/60 opacity-0 transition-opacity hover:bg-foreground/10 hover:text-foreground group-hover:opacity-100 data-[active=true]:opacity-100"
              data-active={active}
              title={tb.close}
            >
              <XIcon className="size-3" />
            </button>
          </div>
        );
      })}
      <button
        type="button"
        onClick={() => openTab()}
        className="ml-0.5 grid size-8 shrink-0 place-items-center rounded-[14px] border border-transparent text-muted-foreground transition-colors hover:border-white/45 hover:bg-white/46 hover:text-foreground"
        style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
        title={tb.newTab}
      >
        <PlusIcon className="size-4" />
      </button>
    </div>
  );
}
