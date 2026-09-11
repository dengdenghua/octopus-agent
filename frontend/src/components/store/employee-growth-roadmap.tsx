import { EMPLOYEE_GROWTH_STAGES } from "@/core/agents/employee-growth";

export function EmployeeGrowthRoadmap() {
  return <section aria-label="员工成长路线" className="space-y-3 border-t pt-3">
    <div><h3 className="text-sm font-medium">员工成长路线</h3><p className="mt-1 text-xs text-muted-foreground">基础版从 Lv.1 开始；绑定后拥有独立身份，逐步成长为高级数字分身。</p></div>
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-xs">
      <dt className="text-muted-foreground">公司</dt><dd>使用用户昵称，随昵称更新</dd>
      <dt className="text-muted-foreground">工号</dt><dd>绑定时分配唯一工号，改名、换岗后保持不变</dd>
    </dl>
    <ol className="space-y-2">{EMPLOYEE_GROWTH_STAGES.map(stage => <li key={stage.level} className="flex gap-3 text-xs"><span className="w-9 shrink-0 font-medium text-muted-foreground">Lv.{stage.level}</span><div><p className="font-medium">{stage.name} · {stage.appearance}</p><p className="mt-0.5 text-muted-foreground">{stage.capability}</p></div></li>)}</ol>
    <p className="text-xs text-muted-foreground">成长方案预览。绑定、装饰解锁尚未接通；等级不自动授予工具权限。白幽灵等高级系统角色保留现有能力。</p>
  </section>;
}
