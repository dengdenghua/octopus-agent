export const SKILL_CATEGORIES = [
  "开发工具",
  "设计创意",
  "影视音频",
  "营销电商",
  "教育学习",
  "其他技能",
] as const;

const aliases: Record<string, (typeof SKILL_CATEGORIES)[number]> = {
  frontend: "开发工具",
  "full-stack": "开发工具",
  octopus: "开发工具",
  平台工具: "开发工具",
  "ui-动效": "设计创意",
  创意实验: "设计创意",
  专业影视: "影视音频",
  动画: "影视音频",
  短剧漫剧: "影视音频",
  音频音乐: "影视音频",
  marketing: "营销电商",
  商业广告: "营销电商",
  电商: "营销电商",
  education: "教育学习",
  教育: "教育学习",
};

export function skillCategories(tags: string[] = []): string[] {
  const categories = tags.flatMap((tag) => {
    const category = aliases[tag.trim().toLowerCase()];
    return category ? [category] : [];
  });
  return categories.length ? [...new Set(categories)] : ["其他技能"];
}
