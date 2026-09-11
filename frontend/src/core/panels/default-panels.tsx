import { Link } from "react-router-dom";
/**
 * Default panel registrations — the "register + done" demonstration.
 *
 * Registers one self-contained reference panel (`workbench.system-status`)
 * through the PanelManifest contract. A host renders it by looking up
 * `getPanel("workbench.system-status")` — no page import needed.
 */
import type { PanelProps } from "./panel-manifest";
import { definePanel, getPanel, registerPanel } from "./panel-manifest";

function SystemStatusPanel({ panel }: PanelProps) {
  return (
    <div
      data-testid="system-status-panel"
      className="rounded-md border p-3 text-sm"
    >
      <div className="font-medium">{panel.title}</div>
      <p className="mt-2 text-muted-foreground">
        查看当前部署的运行状态、服务连接与诊断记录。
      </p>
      <Link
        to="/workspace/observability"
        className="mt-3 inline-flex rounded-md border px-3 py-2 text-sm hover:bg-muted"
      >
        打开运行诊断
      </Link>
    </div>
  );
}

export function ensureDefaultPanels(): void {
  if (getPanel("workbench.system-status")) return;
  registerPanel(
    definePanel({
      id: "workbench.system-status",
      title: "运行诊断",
      zone: "workspace",
      description: "查看服务状态与诊断记录。",
      subscribes: ["turn.started", "turn.completed"],
      dataSources: ["thread", "agent"],
      permission: "everyone",
      order: 0,
      component: SystemStatusPanel,
    }),
  );
}
