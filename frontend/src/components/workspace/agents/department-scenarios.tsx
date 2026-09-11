import { useEffect, useState } from "react";
import { Users, ArrowRight, RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { listAgents } from "@/core/agents/api";
import type { Agent } from "@/core/agents/types";
import { writeTaskCollaboratorPreset, taskCollaboratorRouteForLeader } from "@/core/collaboration/task-collaborator-preset";
import { Button } from "@/components/ui/button";

export const DEPARTMENT_SCENARIOS = [
  { id: "ai", title: "AI 事业部 · 产品孵化", roles: [["twin_ai_product_manager", "AI 产品"], ["twin_ai_engineer", "AI 工程"], ["twin_user_researcher", "用户研究"], ["twin_test_engineer", "测试"]], flow: "用户研究 → 产品方案 → 技术验证 → 测试评估", output: "需求说明、验证计划、测试报告" },
  { id: "software", title: "软件事业部 · 版本交付", roles: [["twin_project", "项目管理"], ["coder", "软件开发"], ["twin_android_system_engineer", "Android 系统"], ["twin_test_engineer", "测试"]], flow: "需求拆解 → 开发实现 → 系统联调 → 发布验收", output: "版本计划、实现记录、验收清单" },
  { id: "hardware", title: "硬件产品 · 研发评审", roles: [["twin_hw_product", "硬件产品"], ["twin_industrial_design", "工业设计"], ["twin_structural_engineer", "结构工程"], ["twin_optical", "光学工程"], ["twin_quality", "质量"]], flow: "产品定义 → 外观与结构 → 光学评审 → 质量验证", output: "产品规格、设计评审、验证计划" },
  { id: "commerce", title: "硬件电商 · 新品上市", roles: [["ecommerce_mind", "电商运营"], ["echo_noah", "市场研究"], ["vibe_selling", "内容策划"], ["twin_supply_chain", "供应链"]], flow: "市场分析 → 商品与内容策划 → 备货协作 → 上市复盘", output: "上市方案、内容清单、备货与复盘指标" },
  { id: "overseas", title: "海外事业部 · 市场拓展", roles: [["twin_sales", "销售商务"], ["twin_product", "产品"], ["twin_operations", "运营"], ["twin_supply_chain", "供应链"], ["twin_finance", "财务"]], flow: "市场定位 → 产品本地化 → 渠道计划 → 交付与费用评估", output: "区域拓展方案、交付计划、预算草案" },
  { id: "supply", title: "供应链支持 · 质量闭环", roles: [["twin_supply_chain", "供应链"], ["twin_procurement_manager_buyer", "采购"], ["twin_supplier_quality_expert", "供应商质量"], ["twin_quality", "品质工程"]], flow: "异常归类 → 供应商分析 → 采购交付协调 → 整改验证", output: "异常台账、8D 草案、交付与整改计划" },
  { id: "support", title: "综合支持 · 经营协同", roles: [["twin_hr", "人力"], ["twin_finance", "财务"], ["twin_legal", "法务"], ["twin_operations", "运营"]], flow: "业务需求 → 人力与预算 → 合规审查 → 执行跟踪", output: "协作计划、预算草案、合规与行动清单" },
];
export function resolveDepartment(scenario: typeof DEPARTMENT_SCENARIOS[number], agents: Agent[]) {
  return { members: scenario.roles.map(([id]) => agents.find(a => a.name === id)), missing: scenario.roles.filter(([id]) => !agents.some(a => a.name === id)).map(([,name]) => name) };
}
type AdditionalScenario = { id: string; title: string; roles: string[][]; flow: string; output: string; onLaunch: () => void };
export function DepartmentScenarios({ additional = [] }: { additional?: AdditionalScenario[] }) {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(false);
    listAgents({ signal: controller.signal }).then(items => { if (!controller.signal.aborted) setAgents(items); })
      .catch(() => { if (!controller.signal.aborted) setError(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt]);
  const launch = (scenario: typeof DEPARTMENT_SCENARIOS[number]) => {
    if (loading) return;
    writeTaskCollaboratorPreset({ leaderId: "general", collaboratorIds: [], mode: "chat", label: scenario.title, openPicker: false });
    const prompt = `/project run 使用「${scenario.title}」准备立项。建议岗位：${scenario.roles.map(([,name]) => name).join("、")}。参考流程：${scenario.flow}。预期交付物：${scenario.output}。请主角先担任产品经理，确认具体目标、范围、期限和预算，按职责复用已有角色并从 HUB 匹配缺少的岗位，说明候选来源、职责、人数和参与阶段。岗位仅为建议，不要提前组队；信息齐全后提交立项与人员审批弹窗，等我批准后才添加成员并建立项目计划。模板参考部门职责，不代表当贝实际人员或内部流程；现场验证和审批由负责人完成。`;
    const route = taskCollaboratorRouteForLeader("general");
    navigate(`${route}${route.includes("?") ? "&" : "?"}prompt=${encodeURIComponent(prompt)}`);
  };
  const scenarios = [...DEPARTMENT_SCENARIOS, ...additional];
  return <section aria-label="精选场景" className="space-y-2">
    <div className="flex items-center justify-between"><h3 className="text-sm font-semibold">精选场景</h3><span className="text-xs text-muted-foreground">先立项 · 审批后组队</span></div>
    {error && <Button variant="ghost" onClick={() => setAttempt(n => n + 1)}><RefreshCw className="size-4" />角色加载失败，重试</Button>}
    <div id="featured-scenario-list" className="grid grid-cols-1 gap-x-3 gap-y-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">{(expanded ? scenarios : scenarios.slice(0, 6)).map(scenario => {
      const external = "onLaunch" in scenario;
      const { missing } = resolveDepartment(scenario, agents);
      const status = external ? `${scenario.roles.length} 人` : loading ? "加载中" : `${scenario.roles.length} 个建议岗位`;
      const details = `${scenario.title}\n${scenario.flow}\n岗位：${scenario.roles.map(([,name]) => name).join("、")}${scenario.output ? `\n交付：${scenario.output}` : ""}${missing.length && !external ? `\n待补：${missing.join("、")}` : ""}`;
      return <button key={scenario.id} title={details} aria-label={`启动部门场景：${scenario.title}`} disabled={external ? !scenario.roles.length : loading} onClick={() => external ? scenario.onLaunch() : launch(scenario)} className="group flex h-10 min-w-0 items-center gap-2 rounded-md px-2 text-left transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
        <Users className="size-4 shrink-0 text-violet-500" /><span className="min-w-0 flex-1 truncate text-xs font-medium">{scenario.title}</span><span className="shrink-0 text-xs text-muted-foreground">{status}</span><ArrowRight className="size-3 shrink-0 text-muted-foreground" />
      </button>;
    })}</div>
    {scenarios.length > 6 && <button className="rounded px-2 py-1 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-expanded={expanded} aria-controls="featured-scenario-list" onClick={() => setExpanded(value => !value)}>{expanded ? "收起场景" : `展开全部 ${scenarios.length} 个场景`}</button>}
  </section>;
}
