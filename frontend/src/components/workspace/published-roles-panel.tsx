import { useState } from "react";
import { jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";

type Role = { role_id: string; name: string; url?: string };

export function PublishedRolesPanel() {
  const [open, setOpen] = useState(false);
  const [roles, setRoles] = useState<Role[]>([]);
  const [published, setPublished] = useState<Role[]>([]);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const request = async (role?: string) => {
    const response = await fetch(`${getBackendBaseURL()}/api/a2a/published-roles`, {
      method: role ? "POST" : "GET", headers: jsonAuthHeaders(),
      body: role ? JSON.stringify({ role_id: role }) : undefined,
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail ?? "无法发布角色");
    return body;
  };
  const refresh = async () => {
    const body = await request() as { roles: Role[]; published: Role[] };
    setRoles(body.roles); setPublished(body.published);
  };
  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await action(); } catch (err) { setError(err instanceof Error ? err.message : "操作失败"); }
    finally { setBusy(false); }
  };
  return <section className="border-b px-4 py-3 text-xs">
    <button type="button" aria-expanded={open} onClick={() => { setOpen(!open); if (!open) void run(refresh); }}>邀请我的角色参与协作</button>
    {open && <div className="mt-3 space-y-2">
      <p className="text-muted-foreground">对方邀请的是你的角色。角色在本机接收任务，并按自己的配置选择执行方式；更换引擎不改变群成员身份。</p>
      <label>对外协作角色<select aria-label="对外协作角色" value={selected} onChange={(e) => setSelected(e.target.value)} className="ml-2 rounded border bg-background p-1">
        <option value="">请选择角色</option>{roles.map((role) => <option key={role.role_id} value={role.role_id}>{role.name}</option>)}
      </select></label>
      <button type="button" disabled={busy || !selected} className="ml-2 rounded border px-2 py-1" onClick={() => void run(async () => { await request(selected); await refresh(); })}>生成角色连接地址</button>
      {published.map((role) => <div key={role.role_id} className="rounded border p-2">
        <p>{role.name}</p><p className="break-all">{role.url}</p>
        <button type="button" onClick={() => void run(async () => { await navigator.clipboard.writeText(role.url ?? ""); })}>复制角色地址</button>
      </div>)}
      <p className="text-muted-foreground">将角色地址交给同事，在「添加远程角色」连接后加入群聊。地址使用本机已配置的协作网络与登录认证；默认本机地址需通过隧道连接。模型额度共享可单独设置。</p>
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>}
  </section>;
}
