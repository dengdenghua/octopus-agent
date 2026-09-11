import { FlagIcon } from "lucide-react";
import type { ReactNode } from "react";

const PROJECT_COMMAND = /^(\s*)(\/project(?:[ \t]+(?:run|start|report|retro|recover|task|accept|budget|help))?)(?=\s|$)/i;

/** Decorate a sent command without changing its stored/copyable source. */
export function ProjectCommandContent({
  content,
  renderBody,
}: {
  content: string;
  renderBody: (body: string) => ReactNode;
}) {
  const match = PROJECT_COMMAND.exec(content);
  if (!match) return renderBody(content);
  const command = match[2]!;
  const body = content.slice(match[0].length).trimStart();
  return (
    <div className="flex max-w-full flex-wrap items-baseline gap-x-2 gap-y-1">
      <span className="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-amber-100/80 px-2 py-0.5 text-sm font-medium text-amber-900 ring-1 ring-amber-500/20 dark:bg-amber-500/15 dark:text-amber-200">
        <FlagIcon className="size-3.5 shrink-0" aria-hidden="true" />
        {command}
      </span>
      {body && <div className="min-w-0 max-w-full">{renderBody(body)}</div>}
    </div>
  );
}
