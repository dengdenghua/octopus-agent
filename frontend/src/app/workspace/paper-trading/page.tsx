"use client";

import { useState } from "react";
import { ExternalLinkIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  WorkspaceBody,
  WorkspaceContainer,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";

type Tab = "platform" | "watch";

/**
 * 模拟炒股(paper_trading)插件页 —— 侧边栏入口。
 *
 * 插件本身是独立 HTML(由后端路由提供),这里用同源 iframe 嵌入到工作台,
 * 复用后端路由 / 凭证,不重复实现前端。两个 tab:
 *  - 平台原版:平台完整交易界面(行情/自选/持仓/下单)
 *  - 盯盘:紧凑真实行情面板(大盘+持仓+自选,自动刷新+涨跌提醒)
 */
export default function PaperTradingPage() {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>("platform");
  const src =
    tab === "watch"
      ? "/api/plugins/paper-trading/watch"
      : "/api/plugins/paper-trading/page";
  const openUrl = tab === "watch" ? "/api/plugins/paper-trading/watch" : "/api/plugins/paper-trading/page";

  return (
    <WorkspaceContainer className="!p-0 md:!px-0">
      <WorkspaceBody className="!p-0">
        <div className="flex h-full w-full min-h-0 flex-col items-stretch">
          <div className="flex h-11 shrink-0 items-center justify-between gap-3 border-b px-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <span>🐟 模拟炒股</span>
              <div className="ml-2 flex items-center rounded-lg border bg-muted/40 p-0.5">
                <button
                  type="button"
                  onClick={() => setTab("platform")}
                  className={`rounded-md px-3 py-1 text-xs transition-colors ${
                    tab === "platform"
                      ? "bg-background font-semibold text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  平台原版
                </button>
                <button
                  type="button"
                  onClick={() => setTab("watch")}
                  className={`rounded-md px-3 py-1 text-xs transition-colors ${
                    tab === "watch"
                      ? "bg-background font-semibold text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  📡 盯盘
                </button>
              </div>
              <span className="text-xs font-normal text-muted-foreground">
                {tab === "watch"
                  ? "真实行情 · 自动刷新 · 涨跌提醒"
                  : t.sidebar.navPaperTradingDesc}
              </span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              asChild
              className="gap-1.5 text-xs text-muted-foreground"
            >
              <a href={openUrl} target="_blank" rel="noreferrer">
                <ExternalLinkIcon className="size-3.5" />
                新窗口打开
              </a>
            </Button>
          </div>
          <iframe
            key={tab}
            src={src}
            title={tab === "watch" ? "盯盘" : t.sidebar.navPaperTrading}
            className="w-full flex-1 border-0"
          />
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
