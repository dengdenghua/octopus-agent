import { ArrowRightIcon, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/* Implementation note. */

export interface SuggestionPillProps {
  label?: ReactNode;
  icon?: LucideIcon | ReactNode;
  onClick?: () => void;
  className?: string;
}

export function SuggestionPill({
  label = "Continue",
  icon,
  onClick,
  className,
}: SuggestionPillProps) {
  const iconNode =
    icon === undefined ? (
      <ArrowRightIcon className="size-3" />
    ) : typeof icon === "function" ? (
      (() => {
        const Ic = icon as LucideIcon;
        return <Ic className="size-3" />;
      })()
    ) : (
      icon
    );

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-full border border-border/60 bg-background/85 px-3 text-[12px] font-medium",
        "shadow-[0_2px_8px_-2px_rgba(0,0,0,0.08)] backdrop-blur-[6px]",
        "transition-[box-shadow,background-color,transform] duration-150",
        "hover:bg-background hover:shadow-[0_4px_12px_-2px_rgba(0,0,0,0.12)]",
        "active:scale-[0.97]",
        className,
      )}
    >
      <span>{label}</span>
      {iconNode}
    </button>
  );
}
