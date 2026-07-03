import { MenuIcon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

/**
 * Hamburger button rendered at the top-left of the chat page header.
 * Used to open the left-side chats drawer (新建对话 / 历史对话).
 */
export function ChatHeaderMenuButton({
  onClick,
  className,
}: {
  onClick: () => void;
  className?: string;
}) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={t.common.openSidebarMenu}
      title={t.common.openSidebarMenu}
      className={cn(
        "flex size-[42px] shrink-0 items-center justify-center rounded-md text-muted-foreground sm:size-8",
        "transition-colors hover:bg-muted hover:text-foreground active:scale-95",
        "outline-none focus-visible:ring-2 focus-visible:ring-ring/30",
        className,
      )}
    >
      <MenuIcon className="size-4" strokeWidth={2.2} />
    </button>
  );
}
