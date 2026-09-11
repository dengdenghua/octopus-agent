import { useEffect, useRef, useState } from "react";

import { jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";

type TeamModel = {
  id: string;
  name: string;
  base_url: string;
  upstream_model: string;
  wire_api: string;
  published: boolean;
};
type Member = {
  id: string;
  label: string;
  used: number;
  max_requests: number;
  revoked: number;
  redeemed: boolean;
};
type Status = {
  enabled: boolean;
  models: TeamModel[];
  members: Member[];
  usage: { id: string; member: string; mode: string; status: string }[];
};
type Joined = {
  id: string;
  base_url: string;
  connected: boolean;
  error: string;
  models: { id: string; display_name: string; wire_api: string }[];
};
const emptyModel = {
  id: "",
  name: "",
  base_url: "",
  api_key: "",
  upstream_model: "",
  wire_api: "chat_completions",
};
const inputClass = "mt-1 block w-full rounded border bg-background px-3 py-2";
const buttonClass = "rounded border px-3 py-2 text-sm disabled:opacity-50";

async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(`${getBackendBaseURL()}${path}`, {
    method,
    headers: jsonAuthHeaders(),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = (await response.json()) as T & { detail?: unknown };
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "请求失败，请检查输入和网关状态",
    );
  return result;
}
const admin = "/api/team-gateway/admin/";

export function TeamGatewaySettings({
  onConnected,
}: {
  onConnected: () => void;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [draft, setDraft] = useState(emptyModel);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [label, setLabel] = useState("");
  const [hours, setHours] = useState(24);
  const [budget, setBudget] = useState(100);
  const [concurrency, setConcurrency] = useState(2);
  const [allowed, setAllowed] = useState<string[]>([]);
  const [invite, setInvite] = useState("");
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:18333/v1");
  const [code, setCode] = useState("");
  const [connections, setConnections] = useState<Joined[]>([]);
  const onConnectedRef = useRef(onConnected);
  useEffect(() => {
    onConnectedRef.current = onConnected;
  }, [onConnected]);
  useEffect(() => {
    let alive = true;
    let previous = "";
    const load = async () => {
      try {
        const result = await api<{ connections: Joined[] }>(
          "/api/team-gateway/connections",
        );
        if (!alive) return;
        const current = JSON.stringify(
          result.connections.map((c) => [c.id, c.models, c.error]),
        );
        setConnections(result.connections);
        if (previous && previous !== current) onConnectedRef.current();
        previous = current;
      } catch {
        /* Authentication and connection failures appear on explicit operations. */
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 60000);
    const focus = () => void load();
    window.addEventListener("focus", focus);
    return () => {
      alive = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", focus);
    };
  }, []);
  const refresh = async () => setStatus(await api<Status>(admin + "status"));
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      aria-label="Echo 团队网关"
      className="space-y-4 rounded-lg border p-4"
    >
      <div>
        <h3 className="font-medium">Echo 团队网关</h3>
        <p className="text-sm text-muted-foreground">
          统一发布团队模型，成员独立授权。工具在使用者自己的 Echo 中执行。
        </p>
      </div>
      <details>
        <summary className="cursor-pointer">管理本机团队网关</summary>
        <div className="mt-3 space-y-4">
          <button
            type="button"
            className={buttonClass}
            disabled={busy}
            onClick={() => void run(refresh)}
          >
            加载 / 启动网关
          </button>
          {status && (
            <>
              <p className="text-sm">
                共享状态：{status.enabled ? "已开启" : "已关闭"} · 本机端口 8333
              </p>
              <button
                type="button"
                className={buttonClass}
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    await api(admin + "enabled", "POST", {
                      enabled: !status.enabled,
                    });
                    await refresh();
                  })
                }
              >
                {status.enabled ? "关闭团队共享" : "开启团队共享"}
              </button>
              <fieldset
                disabled={busy}
                className="space-y-3 rounded border p-3"
              >
                <legend>模型配置</legend>
                {(
                  [
                    ["id", "发布标识（字母、数字、下划线）"],
                    ["name", "显示名称"],
                    ["base_url", "上游地址（以 /v1 结尾）"],
                    ["upstream_model", "上游模型名称"],
                    ["api_key", "上游 Key / 热点凭证（编辑时留空保留）"],
                  ] as const
                ).map(([key, title]) => (
                  <label key={key} className="block text-sm">
                    {title}
                    <input
                      className={inputClass}
                      value={draft[key]}
                      type={key === "api_key" ? "password" : "text"}
                      autoComplete="off"
                      onChange={(e) =>
                        setDraft({ ...draft, [key]: e.target.value })
                      }
                    />
                  </label>
                ))}
                <label className="block text-sm">
                  上游协议
                  <select
                    className={inputClass}
                    value={draft.wire_api}
                    onChange={(e) =>
                      setDraft({ ...draft, wire_api: e.target.value })
                    }
                  >
                    <option value="chat_completions">Chat Completions</option>
                    <option value="responses">Responses（含 Echo 热点）</option>
                  </select>
                </label>
                <button
                  type="button"
                  className={buttonClass}
                  disabled={
                    !draft.id ||
                    !draft.name ||
                    !draft.base_url ||
                    !draft.upstream_model
                  }
                  onClick={() =>
                    void run(async () => {
                      await api(
                        admin + `models/${encodeURIComponent(draft.id)}`,
                        "PUT",
                        draft,
                      );
                      setDraft(emptyModel);
                      await refresh();
                      setMessage("已保存为草稿，请测试并发布。");
                    })
                  }
                >
                  保存草稿
                </button>
              </fieldset>
              <div className="space-y-2">
                {status.models.map((model) => (
                  <div
                    key={model.id}
                    className="flex flex-wrap items-center gap-2 rounded border p-2 text-sm"
                  >
                    <span>
                      {model.name} ·{" "}
                      {model.published ? "已发布" : "草稿 / 暂停"}
                    </span>
                    <button
                      type="button"
                      className={buttonClass}
                      disabled={busy}
                      onClick={() => setDraft({ ...model, api_key: "" })}
                    >
                      编辑 {model.name}
                    </button>
                    <button
                      type="button"
                      className={buttonClass}
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          await api(
                            admin +
                              `models/${model.id}/${model.published ? "pause" : "publish"}`,
                            "POST",
                            {},
                          );
                          await refresh();
                        })
                      }
                    >
                      {model.published ? "暂停" : "测试并发布"} {model.name}
                    </button>
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                测试发布会实际调用上游一次。修改配置后需要重新测试；Key
                不会下发给成员。
              </p>
              <fieldset
                disabled={busy}
                className="space-y-3 rounded border p-3"
              >
                <legend>邀请成员</legend>
                <label className="block text-sm">
                  成员名称
                  <input
                    className={inputClass}
                    value={label}
                    onChange={(e) => setLabel(e.target.value)}
                  />
                </label>
                <div className="grid gap-3 sm:grid-cols-3">
                  <label className="text-sm">
                    有效小时
                    <input
                      className={inputClass}
                      type="number"
                      min={1}
                      max={168}
                      value={hours}
                      onChange={(e) => setHours(Number(e.target.value))}
                    />
                  </label>
                  <label className="text-sm">
                    调用上限
                    <input
                      className={inputClass}
                      type="number"
                      min={1}
                      max={10000}
                      value={budget}
                      onChange={(e) => setBudget(Number(e.target.value))}
                    />
                  </label>
                  <label className="text-sm">
                    并发上限
                    <input
                      className={inputClass}
                      type="number"
                      min={1}
                      max={8}
                      value={concurrency}
                      onChange={(e) => setConcurrency(Number(e.target.value))}
                    />
                  </label>
                </div>
                {status.models
                  .filter((m) => m.published)
                  .map((m) => (
                    <label
                      key={m.id}
                      className="mr-3 inline-flex gap-2 text-sm"
                    >
                      <input
                        type="checkbox"
                        checked={allowed.includes(m.id)}
                        onChange={(e) =>
                          setAllowed(
                            e.target.checked
                              ? [...allowed, m.id]
                              : allowed.filter((id) => id !== m.id),
                          )
                        }
                      />
                      {m.name}
                    </label>
                  ))}
                <button
                  type="button"
                  className={buttonClass}
                  disabled={!label || !allowed.length}
                  onClick={() =>
                    void run(async () => {
                      const result = await api<{ code: string }>(
                        admin + "invitations",
                        "POST",
                        {
                          label,
                          hours,
                          max_requests: budget,
                          concurrency,
                          models: allowed,
                        },
                      );
                      setInvite(result.code);
                      await refresh();
                    })
                  }
                >
                  创建一次性邀请
                </button>
                {invite && (
                  <label className="block text-sm">
                    一次性兑换码（仅本次显示）
                    <input
                      className={inputClass}
                      readOnly
                      value={invite}
                      onFocus={(e) => e.target.select()}
                    />
                  </label>
                )}
              </fieldset>
              <div className="space-y-2">
                <h4 className="text-sm font-medium">成员</h4>
                {status.members.map((m) => (
                  <div
                    className="flex flex-wrap items-center gap-2 text-sm"
                    key={m.id}
                  >
                    <span>
                      {m.label} ·{" "}
                      {m.revoked ? "已撤销" : m.redeemed ? "已接入" : "待兑换"}{" "}
                      · {m.used}/{m.max_requests} 次
                    </span>
                    <button
                      type="button"
                      className={buttonClass}
                      disabled={busy || !!m.revoked}
                      onClick={() =>
                        void run(async () => {
                          await api(admin + `members/${m.id}`, "DELETE");
                          await refresh();
                        })
                      }
                    >
                      撤销 {m.label}
                    </button>
                  </div>
                ))}
              </div>
              <details>
                <summary>最近用量（最多 100 条）</summary>
                <p className="text-xs text-muted-foreground">
                  按请求计次，失败请求也可能计次；forwarded
                  表示转发结束，不代表任务完成。不保存对话正文。
                </p>
                {status.usage.map((call) => (
                  <p key={call.id} className="text-xs">
                    {status.members.find((m) => m.id === call.member)?.label ??
                      call.member}{" "}
                    · {call.mode} · {call.status}
                  </p>
                ))}
              </details>
            </>
          )}
        </div>
      </details>
      <fieldset disabled={busy} className="space-y-3 rounded border p-3">
        <legend>接入团队</legend>
        <label className="block text-sm">
          团队网关地址
          <input
            className={inputClass}
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
          />
        </label>
        <label className="block text-sm">
          团队邀请兑换码
          <input
            className={inputClass}
            type="password"
            autoComplete="off"
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </label>
        <p className="text-xs text-muted-foreground">
          使用团队提供的 HTTPS 地址，或先在接入方电脑建立 SSH 隧道：ssh -N -L
          18333:127.0.0.1:8333 用户@团队主机
        </p>
        <button
          type="button"
          className={buttonClass}
          disabled={!code || !baseUrl}
          onClick={() =>
            void run(async () => {
              const result = await api<Joined>(
                "/api/team-gateway/join",
                "POST",
                { base_url: baseUrl, code },
              );
              setConnections((previous) => [
                ...previous.filter((c) => c.id !== result.id),
                result,
              ]);
              setCode("");
              onConnected();
              if (result.error)
                throw new Error(
                  result.error + " 接入记录已保存，可直接重试同步。",
                );
              setMessage(
                "团队凭证已保存在本机，模型已添加；关闭页面后仍可使用。",
              );
            })
          }
        >
          兑换并接入团队
        </button>
        <p className="text-xs text-muted-foreground">
          授权模型会自动加入列表，后台每分钟同步发布、暂停和授权状态。
        </p>
        {connections.map((connection) => (
          <div
            key={connection.id}
            className="space-y-2 rounded border p-3 text-sm"
          >
            <p>
              {connection.base_url} ·{" "}
              {connection.connected ? "已保存连接" : "待恢复兑换"}
            </p>
            {connection.error && (
              <p role="alert" className="text-destructive">
                {connection.error}
              </p>
            )}
            <p>
              {connection.models.length
                ? connection.models.map((m) => m.display_name).join("、")
                : "暂无可用团队模型"}
            </p>
            <button
              type="button"
              className={buttonClass}
              onClick={() =>
                void run(async () => {
                  const result = await api<Joined>(
                    `/api/team-gateway/connections/${connection.id}/sync`,
                    "POST",
                    {},
                  );
                  setConnections((previous) =>
                    previous.map((c) => (c.id === result.id ? result : c)),
                  );
                  onConnected();
                  if (result.error) throw new Error(result.error);
                  setMessage("团队模型目录已同步。");
                })
              }
            >
              立即同步
            </button>
            <button
              type="button"
              className={buttonClass}
              onClick={() =>
                void run(async () => {
                  await api(
                    `/api/team-gateway/connections/${connection.id}`,
                    "DELETE",
                  );
                  setConnections((previous) =>
                    previous.filter((c) => c.id !== connection.id),
                  );
                  onConnected();
                })
              }
            >
              断开团队连接
            </button>
          </div>
        ))}
      </fieldset>
      {message && (
        <p role="status" className="text-sm">
          {message}
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </section>
  );
}
