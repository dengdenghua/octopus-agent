import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { ConnectDialog } from "@/components/store/capability-market-panel";
import {
  listCapabilities,
  getCapabilityStatus,
  type CapabilityInfo,
} from "@/core/agents/agent-world-api";

/** Reuses the provider connector, including shared-key and free-mode semantics. */
export function OpenCodeConnections({
  onConnected,
}: {
  onConnected: () => void;
}) {
  const client = useQueryClient();
  const [target, setTarget] = useState<CapabilityInfo | null>(null);
  const query = useQuery({
    queryKey: ["opencode-connections"],
    queryFn: async () => {
      const result = await listCapabilities({
        search: "OpenCode",
        includeManual: true,
      });
      const capabilities = await Promise.all(
        result.capabilities
          .filter((cap) => ["opencode-zen", "opencode-go"].includes(cap.id))
          .map(async (cap) => ({
            ...cap,
            ...(await getCapabilityStatus(cap.id)),
          })),
      );
      return { ...result, capabilities };
    },
    staleTime: 30_000,
  });
  const providers =
    query.data?.capabilities.filter((cap) =>
      ["opencode-zen", "opencode-go"].includes(cap.id),
    ) ?? [];
  return (
    <div className="space-y-3">
      <p className="text-xs leading-5 text-muted-foreground">
        Zen 免费模型无需 Key；付费模型与 Go
        在这里管理连接。使用哪个模型，在对话输入框选择。
      </p>
      {query.isPending ? (
        <p role="status" className="text-xs">
          正在读取连接…
        </p>
      ) : query.isError ? (
        <div role="alert" className="flex items-center justify-between text-xs">
          <span>无法读取 OpenCode 连接</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void query.refetch()}
          >
            重试
          </Button>
        </div>
      ) : providers.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          未发现 OpenCode 连接器，请在插件页安装后重试。
        </p>
      ) : (
        providers.map((cap) => (
          <div
            key={cap.id}
            className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2"
          >
            <div>
              <div className="text-sm font-medium">
                {cap.id === "opencode-go"
                  ? "OpenCode Go"
                  : "OpenCode · Zen / Go"}
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {cap.connected
                  ? "已连接"
                  : cap.id === "opencode-zen"
                    ? "免费模式可免 Key 连接"
                    : "需要有效 Go 套餐"}
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={() => setTarget(cap)}>
              {cap.connected ? "管理连接" : "连接"}
            </Button>
          </div>
        ))
      )}
      {target && (
        <ConnectDialog
          capability={target}
          open
          onOpenChange={(open) => {
            if (!open) setTarget(null);
          }}
          onConnected={() => {
            void client.invalidateQueries({
              queryKey: ["opencode-connections"],
            });
            void client.invalidateQueries({ queryKey: ["models"] });
            onConnected();
          }}
        />
      )}
    </div>
  );
}
