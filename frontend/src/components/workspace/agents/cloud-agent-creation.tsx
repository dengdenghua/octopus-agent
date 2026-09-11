import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { PixelAgentAvatar } from "@/components/store/pixel-agent-avatar";
import { installCloudExpert, listCloudStoreExperts, type CloudExpertAgent } from "@/core/agents/agent-world-api";

export function CloudAgentCreation({ sourceId }: { sourceId: string }) {
  const navigate = useNavigate();
  const [source, setSource] = useState<CloudExpertAgent | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const submitting = useRef(false);
  useEffect(() => {
    let active = true;
    setSource(null); setError("");
    listCloudStoreExperts().then(result => {
      if (!active) return;
      const match = result.agents.find(item => item.id === sourceId);
      if (!match) throw new Error("未找到来源模板，请返回目录重新选择。");
      setSource(match);
    }).catch(err => { if (active) setError(err instanceof Error ? err.message : "模板加载失败"); });
    return () => { active = false; };
  }, [sourceId, attempt]);
  async function create() {
    if (!source || submitting.current) return;
    submitting.current = true; setBusy(true); setError("");
    try {
      const result = await installCloudExpert(source.id);
      const id = result.agent_id || result.agent_name;
      if (!(result.installed || result.already_exists) || !id) throw new Error(result.message || "未确认创建结果，请返回目录核实后重试。");
      navigate(`/workspace/agents?surface=chat&hud=1&agent=${encodeURIComponent(id)}`);
    } catch (err) { setError(err instanceof Error ? err.message : "创建失败"); }
    finally { submitting.current = false; setBusy(false); }
  }
  return <section className="mx-auto w-full max-w-xl space-y-5 p-6" aria-label="从模板创建智能体">
    <h2 className="text-lg font-semibold">从模板创建智能体</h2>
    {source ? <><div className="flex items-center gap-3"><PixelAgentAvatar id={source.id} name={source.display_name} team={source.is_team} className="size-12" /><div><h3 className="font-medium">{source.display_name}</h3><p className="text-xs text-muted-foreground">{source.is_team ? "专家团" : "专家"} · {source.source || "云端模板"}</p></div></div><p className="text-sm text-muted-foreground">{source.description}</p><p className="text-xs text-muted-foreground">保留来源模板的技能和配置。创建后进入统一详情页，可继续配置形象、能力与 HUD。</p><Button onClick={() => void create()} disabled={busy}>{busy ? "正在创建…" : "创建智能体"}</Button></> : !error ? <p className="text-sm text-muted-foreground">正在加载模板…</p> : null}
    {error && <div role="alert" className="space-y-2 text-sm text-destructive"><p>{error}</p>{!source && <Button variant="outline" onClick={() => setAttempt(n => n + 1)}>重新加载</Button>}</div>}
  </section>;
}
