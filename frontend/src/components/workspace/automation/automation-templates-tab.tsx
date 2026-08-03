import {
  BookOpenIcon,
  GithubIcon,
  NewspaperIcon,
  SparklesIcon,
  TargetIcon,
  Wand2Icon,
} from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

export type AutomationTemplate = {
  id: string;
  icon: React.ReactNode;
  title: string;
  description: string;
  tags: string[];
  topic: string;
  cadence: string;
  schedule_time: string;
  schedule_day?: string;
  instructions?: string;
};

interface AutomationTemplatesTabProps {
  onUseTemplate?: (template: AutomationTemplate) => void;
  onCreateCustom?: () => void;
}

export function AutomationTemplatesTab({
  onUseTemplate,
  onCreateCustom,
}: AutomationTemplatesTabProps) {
  const { t } = useI18n();

  const templates: AutomationTemplate[] = [
    {
      id: "daily-ai-news",
      icon: <SparklesIcon className="size-5 text-primary" />,
      title: "每日AI资讯摘要",
      description:
        "每日追踪 AI 领域最新论文、开源项目和产品动态，生成精炼摘要",
      tags: ["每日", "09:00"],
      topic: "AI大模型、机器学习、深度学习最新进展",
      cadence: "每日",
      schedule_time: "09:00",
    },
    {
      id: "github-trending",
      icon: <GithubIcon className="size-5 text-primary" />,
      title: "GitHub Trending 追踪",
      description:
        "追踪 GitHub Trending 热门项目，发现有趣的开源工具和框架",
      tags: ["每日", "10:00"],
      topic: "GitHub trending open source projects",
      cadence: "每日",
      schedule_time: "10:00",
    },
    {
      id: "competitor-monitor",
      icon: <TargetIcon className="size-5 text-primary" />,
      title: "竞品动态监控",
      description:
        "监控指定竞品的产品更新、新闻动态和用户反馈，及时掌握竞争格局",
      tags: ["每日", "14:00"],
      topic: "竞品监控",
      cadence: "每日",
      schedule_time: "14:00",
    },
    {
      id: "academic-papers",
      icon: <BookOpenIcon className="size-5 text-primary" />,
      title: "学术论文速递",
      description:
        "从 arXiv 等来源获取最新论文，提取核心方法和实验结论",
      tags: ["每周", "周一"],
      topic: "arxiv cs.AI cs.CL cs.LG latest papers",
      cadence: "每周",
      schedule_time: "09:00",
      schedule_day: "1",
    },
    {
      id: "industry-weekly",
      icon: <NewspaperIcon className="size-5 text-primary" />,
      title: "行业动态周报",
      description:
        "每周汇总行业重要新闻、政策变化和投融资动态，生成周报",
      tags: ["每周", "周五"],
      topic: "科技行业新闻、政策、投融资动态",
      cadence: "每周",
      schedule_time: "09:00",
      schedule_day: "5",
    },
    {
      id: "custom",
      icon: <Wand2Icon className="size-5 text-primary" />,
      title: "自定义任务",
      description: "从空白开始，自定义你想追踪的主题和数据来源",
      tags: ["自定义"],
      topic: "",
      cadence: "每日",
      schedule_time: "09:00",
    },
  ];

  const handleUseTemplate = (template: AutomationTemplate) => {
    if (onUseTemplate) {
      onUseTemplate(template);
    }
  };

  const handleCreateCustom = () => {
    if (onCreateCustom) {
      onCreateCustom();
    }
  };

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {templates.map((template, index) => {
        const isCustom = template.id === "custom";
        const coolTone = index % 2 === 0;
        return (
          <button
            key={template.id}
            type="button"
            onClick={isCustom ? handleCreateCustom : () => handleUseTemplate(template)}
            className={cn(
              "group flex min-h-44 flex-col items-start rounded-[10px] border p-5 text-left transition-[transform,border-color,background-color,box-shadow] hover:-translate-y-0.5",
              coolTone
                ? "border-border bg-card hover:border-primary/28 hover:bg-card hover:shadow-[var(--shadow-sm)]"
                : "border-border/90 bg-muted/18 hover:border-primary/24 hover:bg-muted/28 hover:shadow-[var(--shadow-sm)]",
            )}
          >
            <div className="mb-5 flex w-full items-start">
              <div
                className={cn(
                  "flex size-11 items-center justify-center rounded-md border",
                  coolTone
                    ? "border-border bg-muted/52"
                    : "border-primary/15 bg-primary/7",
                )}
              >
                {template.icon}
              </div>
            </div>

            <div className="flex-1 space-y-1.5">
              <h3 className="text-base font-semibold text-foreground">
                {template.title}
              </h3>
              <p className="line-clamp-2 text-sm leading-relaxed text-muted-foreground">
                {template.description}
              </p>
            </div>

            <span className="sr-only">
              {isCustom
                ? t.intelligence.createCustomTask
                : t.intelligence.useTemplate}
            </span>
          </button>
        );
      })}
    </div>
  );
}
