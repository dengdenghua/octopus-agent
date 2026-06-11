import { cn } from "@/lib/utils";
import type { SteeringUserMessageItem, UserMessageItem } from "@/core/realtime";

/**
 * Right-aligned chat bubble for the user's own turn-starting text.
 *
 * Uses `rounded-2xl` with primary-colored bg + primary-foreground text
 * so it visually echoes the accent color of the app without competing
 * with the agent's left-aligned prose. `whitespace-pre-wrap` keeps
 * newlines the user typed; `break-words` guards against one-char-per-
 * line collapse on very long unbroken CJK strings.
 */
export function UserMessageView({ item }: { item: UserMessageItem | SteeringUserMessageItem }) {
  const steering = item.type === "steeringUserMessage";
  return (
    <div
      className="flex w-full justify-end"
      data-status={item.status}
      data-steering={steering ? "true" : undefined}
    >
      <div
        className={cn(
          "max-w-[85%] rounded-2xl bg-primary px-4 py-2.5 text-sm text-primary-foreground shadow-sm",
          "whitespace-pre-wrap break-words",
          steering && "opacity-80",
        )}
      >
        {item.text}
      </div>
    </div>
  );
}
