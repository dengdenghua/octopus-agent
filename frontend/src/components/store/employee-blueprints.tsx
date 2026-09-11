import { agentCreationRoute } from "@/core/agents/creation-route";
import { EmployeeGrowthRoadmap } from "./employee-growth-roadmap";
import { useState } from "react";
import { Plus } from "lucide-react";
import { PixelAgentAvatar } from "./pixel-agent-avatar";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { blueprints, useProfessionCatalog, type Profession } from "@/core/agents/profession-catalog";

export { blueprints };
export function employeeSetupRoute(role: Profession) {
  return agentCreationRoute({ template: "exec-assistant", roleId: role.id, role: role.name, focus: `${role.boundary}。适用岗位：${role.original_jobs.join("、")}。场景配置：${role.configuration_dimensions}`, capability: `根据职责配置实际可用的技能与工具。参考智能体：${role.candidates.map(c => c.role_id).join("、")}。参考智能体不代表已安装，先核实可用性。` });
}
export function EmployeeBlueprints({ searchQuery = "", showCategories = true }: { searchQuery?: string; showCategories?: boolean }) {
  const { roles, loading, error, retry } = useProfessionCatalog();
  const [category, setCategory] = useState("全部岗位");
  const [detail, setDetail] = useState<Profession | null>(null);
  const filtered = roles.filter(role => (!showCategories || category === "全部岗位" || role.category === category) && `${role.name} ${role.original_jobs.join(" ")} ${role.configuration_dimensions}`.toLowerCase().includes(searchQuery.trim().toLowerCase()));
  return <section aria-label="数字员工岗位" className="space-y-3">
    <div className="flex items-center justify-between gap-3"><span className="text-xs text-muted-foreground">数字员工</span><span className="shrink-0 text-xs text-muted-foreground">{filtered.length} 个岗位</span></div>
    {showCategories && <div className="flex gap-1 overflow-x-auto pb-1" aria-label="数字员工分类">{["全部岗位", ...new Set(roles.map(role => role.category))].map(name => <Button key={name} size="sm" variant={category === name ? "secondary" : "ghost"} aria-pressed={category === name} className="shrink-0" onClick={() => setCategory(name)}>{name}</Button>)}</div>}
    {loading && <p className="text-xs text-muted-foreground">正在同步本地职业…</p>}
    {error && <Button variant="ghost" onClick={retry}>本地职业加载失败，重试</Button>}
    <div className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2 xl:grid-cols-3">{filtered.map(role => <article key={role.id} className="flex min-w-0 items-center gap-3 rounded-md px-2 py-3 hover:bg-muted/50">
      <PixelAgentAvatar id={role.id} name={role.name} />
      <button className="min-w-0 flex-1 rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={role.name} onClick={() => setDetail(role)}><span className="block truncate text-sm font-medium">{role.name}</span><span className="mt-1 block truncate text-xs text-muted-foreground" title={role.original_jobs.join(" · ")}>{role.original_jobs.join(" · ")}</span></button>
      <Button size="icon" variant="ghost" className="size-8 shrink-0" aria-label={`配置${role.name}`} title="创建智能体" asChild><a href={`#${employeeSetupRoute(role)}`}><Plus className="size-4" /></a></Button>
    </article>)}</div>
    {!filtered.length && <p className="py-8 text-center text-sm text-muted-foreground">没有匹配的岗位，请调整分类或搜索词。</p>}
    <Dialog open={!!detail} onOpenChange={open => { if (!open) setDetail(null); }}><DialogContent className="max-h-[85vh] overflow-y-auto"><DialogHeader><DialogTitle>{detail?.name}</DialogTitle><DialogDescription>岗位模板 · 可配置为智能体草稿；数字员工绑定与成长仍在预览阶段</DialogDescription></DialogHeader>{detail && <div className="space-y-4 text-sm"><p>{detail.boundary}</p><p><strong>场景配置：</strong>{detail.configuration_dimensions}</p><p><strong>覆盖岗位：</strong>{detail.original_jobs.join("、")}</p><div><p className="font-medium">可复用基础与来源</p>{detail.candidates.map(candidate => <p key={candidate.role_id} className="mt-2 text-xs text-muted-foreground">{candidate.role_name} · {candidate.source}<br />作者：{candidate.author}</p>)}<p className="mt-2 text-xs text-muted-foreground">基础智能体仅供适配参考，未自动安装或合并其权限。</p></div><EmployeeGrowthRoadmap /><Button asChild><a href={`#${employeeSetupRoute(detail)}`}>配置角色草稿</a></Button></div>}</DialogContent></Dialog>
  </section>;
}
