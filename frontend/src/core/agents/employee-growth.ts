/** Eligibility milestones; these never grant execution permissions. */
export const EMPLOYEE_GROWTH_STAGES = [
  { level: 1, name: "基础员工", appearance: "像素头像、岗位名牌", capability: "岗位对话、按需加载已授权技能" },
  { level: 5, name: "熟练员工", appearance: "头像框、配色、工牌装饰", capability: "开放申请个人知识库与记忆配置" },
  { level: 10, name: "专业员工", appearance: "高清头像、自定义形象", capability: "开放申请项目工具与团队协作" },
  { level: 20, name: "资深员工", appearance: "立绘、场景背景", capability: "开放申请工作流与自动化配置" },
  { level: 30, name: "高级分身", appearance: "完整 HUD、互动装饰", capability: "开放高级人格与协作配置" },
] as const;

export function employeeGrowthStage(level: number) {
  const normalized = Number.isFinite(level) ? Math.max(1, Math.floor(level)) : 1;
  return [...EMPLOYEE_GROWTH_STAGES].reverse().find(stage => normalized >= stage.level)!;
}
