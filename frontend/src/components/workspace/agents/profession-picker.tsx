import { useMemo, useState } from "react";
import { BriefcaseBusiness, ChevronDown } from "lucide-react";
import { useProfessionCatalog } from "@/core/agents/profession-catalog";
export { professionName } from "@/core/agents/profession-catalog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Root as Popover, Content as PopoverContent, Trigger as PopoverTrigger } from "@radix-ui/react-collapsible";

export function ProfessionPicker({ onSelect }: { onSelect: (profession: { name: string; id: string; description: string }) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("");
  const { roles, loading, error, retry } = useProfessionCatalog();
  const matches = useMemo(() => roles.filter(a => `${a.name} ${a.category} ${a.original_jobs.join(" ")} ${a.boundary}`.toLowerCase().includes(query.trim().toLowerCase())), [roles, query]);
  const choose = (name: string, id: string, description: string) => {
    setSelected(name); setOpen(false); onSelect({ name, id, description });
  };
  return <div className="mt-5 space-y-2">
    <label className="text-sm font-medium">职业模板</label>
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" className="w-full justify-start gap-2" aria-label="选择职业模板">
          <BriefcaseBusiness className="size-4 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate text-left">{selected || "选择职业，或自定义岗位"}</span><ChevronDown className="size-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="mt-2 w-full rounded-md border bg-background p-2">
        <Input aria-label="搜索职业" placeholder="搜索职业，如结构、嵌入式、财务…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <div className="mt-2 max-h-60 overflow-y-auto">
          {loading && <p className="p-2 text-xs text-muted-foreground">正在同步本地职业…</p>}
          {error && <Button variant="ghost" onClick={retry}>本地职业加载失败，重试</Button>}
          {matches.map(a => <button type="button" key={a.id} aria-label={a.name} className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm hover:bg-muted focus-visible:bg-muted" onClick={() => choose(a.name, a.id, a.boundary)}><BriefcaseBusiness className="size-4 shrink-0 text-muted-foreground" />{a.name}<span className="ml-auto text-xs text-muted-foreground">{a.category}</span></button>)}
          {!loading && matches.length === 0 && <p className="p-2 text-xs text-muted-foreground">没有匹配职业，可以自定义添加。</p>}

        </div>
        {query.trim() && <Button variant="ghost" className="mt-1 w-full justify-start border-t" onClick={() => choose(query.trim(), "", "")}>使用自定义职业：{query.trim()}</Button>}
      </PopoverContent>
    </Popover>
    <p className="text-xs text-muted-foreground">与 HUB 数字员工共用职业目录，选择后带入职责，可继续编辑。</p>
  </div>;
}
