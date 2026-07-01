import type { ReactNode } from "react";
import { CloudIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { cn } from "@/lib/utils";

// 商城资产(角色/插件/技能)卡片——视觉语言对齐本地角色库的 AgentCard /
// AgentWorldCard(同尺寸图标框、同 Card/Badge 排版),差异只在没有真实
// avatar_url/rating/downloads(registry 信封不带这些字段),用渐变图标
// 占位替代头像。三个商城面板(角色/插件/技能)共用本组件,保证观感统一。

const CATEGORY_STYLE_MAP: Record<
  string,
  { bg: string; text: string; icon: string }
> = {
  assistant: {
    bg: "bg-blue-500/10",
    text: "text-blue-600 dark:text-blue-400",
    icon: "🤖",
  },
  coder: {
    bg: "bg-emerald-500/10",
    text: "text-emerald-600 dark:text-emerald-400",
    icon: "💻",
  },
  researcher: {
    bg: "bg-violet-500/10",
    text: "text-violet-600 dark:text-violet-400",
    icon: "🔬",
  },
  creative: {
    bg: "bg-amber-500/10",
    text: "text-amber-600 dark:text-amber-400",
    icon: "🎨",
  },
  automation: {
    bg: "bg-rose-500/10",
    text: "text-rose-600 dark:text-rose-400",
    icon: "⚡",
  },
  specialist: {
    bg: "bg-cyan-500/10",
    text: "text-cyan-600 dark:text-cyan-400",
    icon: "🎯",
  },
  financial: {
    bg: "bg-teal-500/10",
    text: "text-teal-600 dark:text-teal-400",
    icon: "💼",
  },
  "digital-twin": {
    bg: "bg-fuchsia-500/10",
    text: "text-fuchsia-600 dark:text-fuchsia-400",
    icon: "🫂",
  },
};
const DEFAULT_CATEGORY_STYLE = {
  bg: "bg-muted",
  text: "text-muted-foreground",
  icon: "☁️",
};

export function categoryStyleFor(category?: string | null) {
  if (!category) return DEFAULT_CATEGORY_STYLE;
  return CATEGORY_STYLE_MAP[category] ?? DEFAULT_CATEGORY_STYLE;
}

interface RegistryAssetCardProps {
  name: string;
  description: string;
  category?: string | null;
  categoryLabel?: string;
  typeLabel: string;
  featured?: boolean;
  actionSlot: ReactNode;
}

export function RegistryAssetCard({
  name,
  description,
  category,
  categoryLabel,
  typeLabel,
  featured,
  actionSlot,
}: RegistryAssetCardProps) {
  const style = categoryStyleFor(category);

  return (
    <Card
      className={cn(
        "group relative flex flex-col overflow-hidden rounded-lg border-border/70 bg-card/86 py-0 transition-all duration-200 ease-out",
        "hover:-translate-y-0.5 hover:border-primary/35 hover:shadow-[0_0_24px_hsl(var(--primary)/0.10)]",
      )}
    >
      {featured && (
        <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-amber-500/60 via-primary/40 to-violet-500/60" />
      )}
      <CardHeader className="flex flex-1 flex-col px-3 pb-2 pt-3">
        <div className="flex items-start gap-2">
          <div
            className={cn(
              "relative flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border/60 text-lg leading-none",
              style.bg,
            )}
          >
            <span className={style.text}>{style.icon}</span>
            <div className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-sky-500 shadow-sm">
              <CloudIcon className="h-2.5 w-2.5 text-white" />
            </div>
          </div>
          <div className="min-w-0 flex-1">
            <CardTitle className="truncate text-sm font-semibold leading-5">
              {name}
            </CardTitle>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {typeLabel}
            </p>
          </div>
        </div>

        <CardDescription className="mt-2 line-clamp-2 min-h-8 text-xs leading-4 text-muted-foreground/90">
          {description}
        </CardDescription>

        {categoryLabel && (
          <div className="mt-2">
            <Badge
              variant="secondary"
              className={cn("text-[10px] font-medium", style.bg, style.text)}
            >
              {categoryLabel}
            </Badge>
          </div>
        )}
      </CardHeader>

      <CardFooter className="mt-auto flex items-center justify-end gap-2 border-t border-border/65 bg-background/54 px-3 py-2">
        {actionSlot}
      </CardFooter>
    </Card>
  );
}
