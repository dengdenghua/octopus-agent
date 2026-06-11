
import { SearchIcon, SparklesIcon } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import { useEnableSkill, useSkills } from "@/core/skills/hooks";
import type { Skill } from "@/core/skills/type";
import { env } from "@/env";

// ---------------------------------------------------------------------------
// Category definitions — matching Octopus layout
// ---------------------------------------------------------------------------

interface CategoryDef {
  key: string;
  icon: string;
  pattern: RegExp;
}

const CATEGORIES: CategoryDef[] = [
  {
    key: "ecommerce",
    icon: "🛒",
    pattern:
      /ecommerce|shopify-builder|shopify-dev|shopify-developer|etsy|amazon|amz|alibaba|1688|product-select|product-supplier|sourcing|cj-drop|cross-border|tariff|market-insight|sycm|new-product|tech-pack|review-analyst|review-summ/i,
  },
  {
    key: "marketing",
    icon: "📣",
    pattern:
      /marketing|content-strategy|content-breakdown|copywriting|social-content|social-media|social-network|instagram|launch-strategy|page-cro|ab-test|sales-negot|competitive|product-description|product-marketing|remotion|image-prompt|ecommerce-marketing/i,
  },
  {
    key: "research",
    icon: "📊",
    pattern: /company-research|people-research|org-structure/i,
  },
  {
    key: "finance",
    icon: "🏦",
    pattern: /financial|dcf-valuation|creating-financial/i,
  },
  {
    key: "document",
    icon: "📄",
    pattern: /^docx$|^pdf$|^pptx$|^xlsx$/i,
  },
  {
    key: "devtools",
    icon: "💻",
    pattern: /mcp-tools|mcporter|graphql/i,
  },
  {
    key: "communication",
    icon: "✉️",
    pattern: /gmail|lark/i,
  },
  {
    key: "skill-mgmt",
    icon: "🧩",
    pattern:
      /skill-creator|skill-finder|skill-writer|skill-vetter|skillsmp|find-skills|authoring-skills|self-improvement/i,
  },
];

// Map category keys to i18n translation keys
const CATEGORY_LABEL_KEYS: Record<string, string> = {
  ecommerce: "ecommerce",
  marketing: "marketing",
  research: "research",
  finance: "finance",
  document: "documents",
  devtools: "devtools",
  communication: "communication",
  "skill-mgmt": "skillManagement",
};

function classifySkill(name: string): string {
  for (const cat of CATEGORIES) {
    if (cat.pattern.test(name)) return cat.key;
  }
  return "other";
}

// ---------------------------------------------------------------------------
// Per-skill emoji icons
// ---------------------------------------------------------------------------

const SKILL_ICONS: Record<string, string> = {
  // E-commerce
  "shopify-builder": "🏪",
  "shopify-dev-mcp": "📘",
  "shopify-developer": "👨‍💻",
  "1688-product-research": "🔎",
  "1688-sourcing": "📷",
  "alibaba-publish-skill": "📤",
  "alibaba-store-analysis": "📈",
  "amz-hot-keywords": "🔥",
  "amz-product-optimizer": "⚡",
  "cj-dropshipping-api": "📦",
  "cross-border-selection": "🌍",
  "tariff-search": "🧾",
  "tech-pack-generation": "📐",
  "sycm-analysis-skill": "📊",
  "new-product-development-design": "🎨",
  "market-insight-product-selection": "🧭",
  "product-selection": "🎯",
  "product-supplier-sourcing": "🤝",
  "etsy-pod-automation": "🖨️",
  "review-analyst-agent": "📝",
  "review-summarizer": "📋",
  // Marketing
  "ecommerce-marketing": "🛍️",
  "content-strategy": "📌",
  "content-breakdown": "🔬",
  copywriting: "✏️",
  "social-content": "📱",
  "social-media-publisher": "📣",
  "social-network-mapper": "🕸️",
  "instagram-marketing": "📸",
  "launch-strategy": "🚀",
  "page-cro": "📈",
  "ab-test-setup": "🧪",
  "sales-negotiator": "🤝",
  "competitive-landscape": "⚔️",
  "product-description-generator": "🏷️",
  "product-marketing-context": "📄",
  "marketing-ideas": "💡",
  "marketing-psychology": "🧠",
  "image-prompt-guide": "🖼️",
  remotion: "🎬",
  // Research
  "company-research": "🏢",
  "people-research": "👤",
  "org-structure-research": "🏛️",
  // Finance
  "creating-financial-models": "📊",
  "dcf-valuation": "💰",
  // Documents
  docx: "📝",
  pdf: "📕",
  pptx: "📊",
  xlsx: "📗",
  // Dev tools
  "mcp-tools": "🔧",
  mcporter: "🔌",
  "graphql-operations": "🔗",
  // Communication
  "gmail-assistant": "✉️",
  "lark-tools": "💬",
  // Skill management
  "skill-creator": "🛠️",
  "skill-finder": "🔍",
  "skill-writer": "✍️",
  "skill-vetter": "🛡️",
  skillsmp: "🏬",
  "find-skills": "🧩",
  "authoring-skills": "📚",
  "self-improvement": "🌱",
  // Other
  "create-website": "🌐",
};

function getSkillIcon(name: string): string {
  return SKILL_ICONS[name] ?? "🧩";
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function SkillSettingsPage({ onClose }: { onClose?: () => void } = {}) {
  const { t } = useI18n();
  const { skills, isLoading, error } = useSkills();
  return (
    <div className="w-full">
      {isLoading ? (
        <div className="text-muted-foreground text-sm">{t.common.loading}</div>
      ) : error ? (
        <div>Error: {error.message}</div>
      ) : (
        <SkillSettingsList skills={skills} onClose={onClose} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Grouped skill list
// ---------------------------------------------------------------------------

interface SkillGroup {
  key: string;
  label: string;
  icon: string;
  skills: Skill[];
}

function labelForGroup(
  key: string,
  t: ReturnType<typeof useI18n>["t"],
): string {
  if (key === "system") return t.skillCategories.systemTools;
  if (key === "automation") return t.skillCategories.automationTools;
  if (key === "other") return t.common.other;
  const labelKey = CATEGORY_LABEL_KEYS[key] ?? key;
  return (t.skillCategories as Record<string, string>)[labelKey] ?? labelKey;
}

function classifySettingsSkill(skill: Skill): string {
  if (skill.kind === "system") return "system";
  if (skill.kind === "automation") return "automation";
  return classifySkill(skill.name);
}

function SkillSettingsList({
  skills,
  onClose,
}: {
  skills: Skill[];
  onClose?: () => void;
}) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [searchQuery, setSearchQuery] = useState("");
  const { mutate: enableSkill } = useEnableSkill();

  const configurableSkills = useMemo(
    () =>
      skills.filter(
        (s) => Boolean(s.name) && typeof s.enabled === "boolean",
      ),
    [skills],
  );

  // Group skills by category
  const groups: SkillGroup[] = useMemo(() => {
    let filtered = configurableSkills;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          (s.description ?? "").toLowerCase().includes(q),
      );
    }

    // Build groups in defined order
    const groupMap = new Map<string, Skill[]>();
    for (const skill of filtered) {
      const key = classifySettingsSkill(skill);
      if (!groupMap.has(key)) groupMap.set(key, []);
      groupMap.get(key)!.push(skill);
    }

    // Sort within each group: enabled first, then alphabetical
    for (const [, arr] of groupMap) {
      arr.sort((a, b) => {
        if (a.enabled !== b.enabled) return a.enabled ? -1 : 1;
        return a.name.localeCompare(b.name);
      });
    }

    const result: SkillGroup[] = [];
    for (const cat of CATEGORIES) {
      const items = groupMap.get(cat.key);
      if (items && items.length > 0) {
        result.push({
          key: cat.key,
          label: labelForGroup(cat.key, t),
          icon: cat.icon,
          skills: items,
        });
        groupMap.delete(cat.key);
      }
    }
    // "Other" bucket
    const otherItems = groupMap.get("other");
    if (otherItems && otherItems.length > 0) {
      result.push({
        key: "other",
        label: labelForGroup("other", t),
        icon: "📦",
        skills: otherItems,
      });
    }
    groupMap.delete("other");

    const automationItems = groupMap.get("automation");
    if (automationItems && automationItems.length > 0) {
      result.push({
        key: "automation",
        label: labelForGroup("automation", t),
        icon: "⚙️",
        skills: automationItems,
      });
      groupMap.delete("automation");
    }

    const systemItems = groupMap.get("system");
    if (systemItems && systemItems.length > 0) {
      result.push({
        key: "system",
        label: labelForGroup("system", t),
        icon: "🔧",
        skills: systemItems,
      });
    }

    return result;
  }, [configurableSkills, searchQuery, t]);

  const handleCreateSkill = () => {
    onClose?.();
    navigate("/workspace/realtime/new?mode=skill");
  };

  return (
    <div className="flex w-full flex-col gap-4">
      {/* Search */}
      <div className="relative">
        <SearchIcon className="text-muted-foreground absolute left-2.5 top-2.5 size-4" />
        <Input
          className="pl-9"
          placeholder={t.common.search + "..."}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
      </div>
      <p className="text-muted-foreground text-xs">
        {t.settings.skills.enabledDescription}
      </p>

      {/* Grouped skills */}
      {groups.length === 0 ? (
        searchQuery.trim() ? (
          <div className="text-muted-foreground py-8 text-center text-sm">
            {t.settings.skills.noMatch(searchQuery)}
          </div>
        ) : (
          <EmptySkill onCreateSkill={handleCreateSkill} />
        )
      ) : (
        <div className="flex flex-col gap-6">
          {groups.map((group) => (
            <section key={group.key}>
              {/* Category header */}
              <div className="mb-3 flex items-center gap-2">
                <span className="text-base">{group.icon}</span>
                <span className="text-sm font-semibold">
                  {group.label}
                </span>
                <span className="text-muted-foreground text-xs">
                  {group.skills.length}
                </span>
              </div>
              {/* 3-column grid */}
              <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2 lg:grid-cols-3">
                {group.skills.map((skill) => (
                  <SkillCard
                    key={skill.name}
                    skill={skill}
                    onToggle={(checked) =>
                      enableSkill({
                        skillName: skill.name,
                        enabled: checked,
                      })
                    }
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skill card — matching Octopus style
// ---------------------------------------------------------------------------

function SkillCard({
  skill,
  onToggle,
}: {
  skill: Skill;
  onToggle: (enabled: boolean) => void;
}) {
  return (
    <div className="flex items-center gap-3 rounded-lg border px-3 py-2.5 transition-colors hover:bg-accent/30">
      <span className="shrink-0 text-lg select-none">{getSkillIcon(skill.name)}</span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{skill.name}</p>
        {skill.description && (
          <p className="text-muted-foreground mt-0.5 truncate text-xs">
            {skill.description}
          </p>
        )}
      </div>
      <Switch
        className="shrink-0 data-[state=checked]:bg-green-500"
        checked={skill.enabled}
        disabled={env.STATIC_WEBSITE_ONLY}
        onCheckedChange={onToggle}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptySkill({ onCreateSkill }: { onCreateSkill: () => void }) {
  const { t } = useI18n();
  return (
    <Empty>
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <SparklesIcon />
        </EmptyMedia>
        <EmptyTitle>{t.settings.skills.emptyTitle}</EmptyTitle>
        <EmptyDescription>
          {t.settings.skills.emptyDescription}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button onClick={onCreateSkill}>{t.settings.skills.emptyButton}</Button>
      </EmptyContent>
    </Empty>
  );
}

