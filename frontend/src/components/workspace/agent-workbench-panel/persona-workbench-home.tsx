import { ArrowUpRightIcon, Layers3Icon } from "lucide-react";
import { Link } from "react-router-dom";

import { workspacePresetForAgent } from "@/core/workspace/workspace-presets";

export function PersonaWorkbenchHome({
  personaId,
}: {
  personaId?: string | null;
}) {
  const preset = workspacePresetForAgent(personaId);

  return (
    <div className="persona-workbench-home min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
      <div className="mx-auto flex max-w-xl flex-col gap-4">
        <section className="rounded-2xl border border-[color:color-mix(in_oklch,var(--primary)_20%,var(--border))] bg-background/90 p-4 shadow-sm">
          <div className="flex items-start gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Layers3Icon className="size-4" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-foreground">
                {preset.workbenchLabel}
              </p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {preset.workbenchSummary}
              </p>
            </div>
          </div>
        </section>

        <div className="grid grid-cols-3 gap-2">
          {preset.workbenchLanes.map((lane, index) => (
            <div
              key={lane}
              className="rounded-xl border border-[color:color-mix(in_oklch,var(--primary)_14%,var(--border))] bg-background/80 px-3 py-3"
            >
              <span className="text-[10px] font-medium tabular-nums text-primary/75">
                0{index + 1}
              </span>
              <p className="mt-2 text-xs font-medium text-foreground">{lane}</p>
            </div>
          ))}
        </div>

        {preset.primaryAction ? (
          <Link
            to={preset.primaryAction.to}
            className="flex h-10 items-center justify-between rounded-xl border border-[color:color-mix(in_oklch,var(--primary)_20%,var(--border))] bg-background px-3 text-xs font-medium text-foreground transition-colors hover:border-primary/35 hover:bg-primary/5"
          >
            {preset.primaryAction.label}
            <ArrowUpRightIcon className="size-3.5 text-primary/80" />
          </Link>
        ) : null}
      </div>
    </div>
  );
}
