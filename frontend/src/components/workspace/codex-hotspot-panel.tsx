import { useCallback, useEffect, useState } from "react";

import { jsonAuthHeaders } from "@/core/auth/api";
import { hotspotModelConfig, hotspotOpenCodeConfig } from "@/core/agents/hotspot-config";
import { getBackendBaseURL } from "@/core/config";

type Member = {
  id: string;
  label: string;
  expires: number;
  used: number;
  max_requests: number;
  revoked: number;
};
type Status = { enabled: boolean; members: Member[] };
type Invitation = {
  id: string;
  token: string;
  task_url: string;
  base_url: string;
};

async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/a2a/hotspot/${path}`,
    {
      method,
      headers: jsonAuthHeaders(),
      body: body === undefined ? undefined : JSON.stringify(body),
    },
  );
  const value = (await response.json()) as T & { detail?: string };
  if (!response.ok) throw new Error(value.detail ?? "热点操作失败");
  return value;
}

export function CodexHotspotPanel({
  onRoleRegistered,
}: {
  onRoleRegistered?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [label, setLabel] = useState("");
  const [hours, setHours] = useState(8);
  const [limit, setLimit] = useState(100);
  const [invitation, setInvitation] = useState<Invitation | null>(null);
  const [taskEngine, setTaskEngine] = useState("codex");
  const [model, setModel] = useState("gpt-5.5");
  const [guestPort, setGuestPort] = useState(18322);
  const refresh = useCallback(async () => {
    try {
      setStatus(await request<Status>("status"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法读取热点状态");
    }
  }, []);
  useEffect(() => {
    if (!open) return;
    void refresh();
    const timer = setInterval(() => {
      void refresh();
    }, 5000);
    return () => clearInterval(timer);
  }, [open, refresh]);
  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError("");
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "热点操作失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="border-b px-4 py-3 text-xs">
      <button
        type="button"
        className="font-medium"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        共享我的模型 {open ? "收起" : "管理"}
      </button>
      {open && (
        <div className="mt-3 space-y-3">
          <p className="text-muted-foreground">
            当前共享来源为本机 Codex 套餐。同事可在自己的 Echo 模型设置中连接，也支持其他 Responses 客户端。
            远程角色可选择 Codex 或 OpenCode。
          </p>
          <button
            type="button"
            disabled={busy || !status}
            className="rounded border px-3 py-1.5 disabled:opacity-50"
            onClick={() =>
              void run(async () => {
                await request("enabled", "POST", { enabled: !status?.enabled, task_engine: taskEngine });
              })
            }
          >
            {busy ? "处理中…" : status?.enabled ? "关闭热点" : "开启热点"}
          </button>
          {error && (
            <p role="alert" className="text-destructive">
              {error}
            </p>
          )}
          <label className="block">
            远程角色引擎
            <select value={taskEngine} onChange={(e) => setTaskEngine(e.target.value)} className="ml-2 rounded border bg-background p-1">
              <option value="codex">Codex</option>
              <option value="opencode">OpenCode</option>
            </select>
          </label>
          {taskEngine === "opencode" && <p className="text-muted-foreground">OpenCode 角色当前使用经实时校验的 Zen 免费模型，仅支持对话任务。</p>}
          {status?.enabled && (
            <button
              type="button"
              disabled={busy}
              className="ml-2 rounded border px-3 py-1.5"
              onClick={() =>
                void run(async () => {
                  await request("local-role", "POST", { task_engine: taskEngine });
                  onRoleRegistered?.();
                })
              }
            >
              添加本机 {taskEngine === "opencode" ? "OpenCode" : "Codex"} 为远程角色
            </button>
          )}
          {status?.enabled && (
            <form
              className="space-y-2"
              onSubmit={(e) => {
                e.preventDefault();
                void run(async () => {
                  setInvitation(
                    await request<Invitation>("members", "POST", {
                      label,
                      hours,
                      max_requests: limit,
                      task_engine: taskEngine,
                    }),
                  );
                });
              }}
            >
              <label className="block">
                同事名称
                <input
                  required
                  maxLength={80}
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  className="mt-1 block w-full rounded border bg-background p-2"
                />
              </label>
              <div className="flex gap-2">
                <label>
                  有效小时
                  <input
                    type="number"
                    min={1}
                    max={168}
                    value={hours}
                    onChange={(e) => setHours(Number(e.target.value))}
                    className="mt-1 block w-24 rounded border bg-background p-2"
                  />
                </label>
                <label>
                  调用次数上限
                  <input
                    type="number"
                    min={1}
                    max={10000}
                    value={limit}
                    onChange={(e) => setLimit(Number(e.target.value))}
                    className="mt-1 block w-28 rounded border bg-background p-2"
                  />
                </label>
              </div>
              <p className="text-muted-foreground">
                每个任务或模型请求计一次；这不是套餐积分。模型执行一个任务可能需要多次请求。
              </p>
              <button
                disabled={busy || !label.trim()}
                type="submit"
                className="rounded border px-3 py-1.5 disabled:opacity-50"
              >
                创建邀请
              </button>
            </form>
          )}
          {invitation && (
            <div className="space-y-2 rounded border p-2">
              <p>连接资料（凭证仅显示本次，请私下交给受邀同事）</p>
              <label className="block">
                访问凭证
                <input
                  readOnly
                  type="password"
                  value={invitation.token}
                  className="block w-full rounded border bg-background p-1"
                />
              </label>
              <button
                type="button"
                className="rounded border px-2 py-1"
                onClick={() =>
                  void run(async () => {
                    await navigator.clipboard.writeText(
                      JSON.stringify(invitation, null, 2),
                    );
                  })
                }
              >
                复制连接资料
              </button>
              <p className="break-all">任务角色地址：{invitation.task_url}</p>
              <p className="break-all">
                模型地址：{invitation.base_url}（Responses）
              </p>
              <p className="text-muted-foreground">
                同事先建立到本机的 SSH 8322
                端口隧道。任务模式在「添加远程角色」填写地址和凭证；模型模式配置自定义
                Responses 服务。
              </p>
              <label className="block">
                同事端模型隧道端口
                <input
                  type="number"
                  min={1}
                  max={65535}
                  value={guestPort}
                  onChange={(event) => setGuestPort(Number(event.target.value))}
                  className="mt-1 block w-28 rounded border bg-background p-1"
                />
              </label>
              <button
                type="button"
                className="rounded border px-2 py-1"
                onClick={() =>
                  void run(async () => {
                    await navigator.clipboard.writeText(
                      hotspotModelConfig(guestPort),
                    );
                  })
                }
              >
                复制 Codex 模型配置
              </button>
              <label className="block">模型 ID<input value={model} onChange={(e) => setModel(e.target.value)} className="ml-2 rounded border bg-background p-1" /></label>
              <button type="button" className="rounded border px-2 py-1" onClick={() => void run(async () => { await navigator.clipboard.writeText(hotspotOpenCodeConfig(guestPort, model)); })}>复制 OpenCode 模型配置</button>
              <p className="text-muted-foreground">
                配置不含凭证。将邀请凭证放入同事端 ECHO_HOTSPOT_TOKEN 环境变量，
                合并配置时保留原有模型选择。Codex 配置关闭自动重试；OpenCode 的重试由其客户端控制。
                这里只修改模型隧道端口，任务角色仍使用 8322 端口。
              </p>
            </div>
          )}
          {status?.members.map((member) => (
            <div
              key={member.id}
              className="flex items-center justify-between gap-2 rounded border p-2"
            >
              <span>
                {member.label} · {member.used}/{member.max_requests} 次 ·{" "}
                {member.revoked
                  ? "已撤销"
                  : member.expires * 1000 <= Date.now()
                    ? "已过期"
                    : "有效"}
              </span>
              <button
                type="button"
                disabled={busy || Boolean(member.revoked)}
                onClick={() =>
                  void run(async () => {
                    await request(`members/${member.id}`, "DELETE");
                    if (invitation?.id === member.id) setInvitation(null);
                  })
                }
              >
                撤销
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
