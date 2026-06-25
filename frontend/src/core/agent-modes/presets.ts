import type { AgentModeName } from "@/components/workspace/mode-selector";

export type ModePresetId =
  | "develop"
  | "audit"
  | "uxui"
  | "architect";

export type SkillPackProfile = "develop" | "audit" | "uxui" | "architect";
export type VerificationPolicy = "light" | "standard" | "strict" | "visual";

export interface ModeOrchestrationPreset {
  id: ModePresetId;
  agentMode: AgentModeName;
  workflowPreset:
    | "develop.iterate"
    | "audit.review"
    | "audit.ultracode"
    | "uxui.regression"
    | "architect.design";
  skillPackProfile: SkillPackProfile;
  verificationPolicy: VerificationPolicy;
  defaultSkillPacks: string[];
  defaultPlugins: string[];
  promptContract: string;
}

const MODE_PRESETS: Record<ModePresetId, ModeOrchestrationPreset> = {
  develop: {
    id: "develop",
    agentMode: "develop",
    workflowPreset: "develop.iterate",
    skillPackProfile: "develop",
    verificationPolicy: "standard",
    defaultSkillPacks: ["code", "files", "browser"],
    defaultPlugins: ["git", "terminal"],
    promptContract:
      "小步实现、就近测试、保留现有风格；每轮交付说明修改面、验证命令和残余风险。",
  },
  audit: {
    id: "audit",
    agentMode: "audit",
    workflowPreset: "audit.review",
    skillPackProfile: "audit",
    verificationPolicy: "strict",
    defaultSkillPacks: ["code", "files", "review", "tests"],
    defaultPlugins: ["git", "terminal"],
    promptContract:
      "默认先审计不改动；输出发现、证据、严重度、影响面和修复顺序，用户要求修复后再动手。",
  },
  uxui: {
    id: "uxui",
    agentMode: "uxui",
    workflowPreset: "uxui.regression",
    skillPackProfile: "uxui",
    verificationPolicy: "visual",
    defaultSkillPacks: ["browser", "visual", "code", "files"],
    defaultPlugins: ["browser", "terminal"],
    promptContract:
      "优先真实预览和交互走查；关注遮挡、跳变、密度、层级、文案、响应式和视觉质感，修改后必须做浏览器回归。",
  },
  architect: {
    id: "architect",
    agentMode: "architect",
    workflowPreset: "architect.design",
    skillPackProfile: "architect",
    verificationPolicy: "standard",
    defaultSkillPacks: ["code", "files", "review", "docs"],
    defaultPlugins: ["git", "terminal"],
    promptContract:
      "先读边界和现有约束，再给出接口、迁移、兼容性和回滚设计；避免无必要的大范围重写。",
  },
};

export function modePresetForAgentMode(
  agentMode: AgentModeName,
): ModeOrchestrationPreset {
  if (agentMode === "audit") return MODE_PRESETS.audit;
  if (agentMode === "uxui") return MODE_PRESETS.uxui;
  if (agentMode === "architect") return MODE_PRESETS.architect;
  return MODE_PRESETS.develop;
}
