export type EngineCapabilityChecks = Partial<Record<"chat" | "web_search" | "tools", {
  state: "untested" | "verified" | "failed";
  model?: string | null;
  checked_at?: number;
}>>;

export function engineVerificationLabel(checks: EngineCapabilityChecks | undefined, zh: boolean, now = Date.now()) {
  const check = checks?.chat;
  const fresh = check?.checked_at && now / 1000 - check.checked_at >= 0 && now / 1000 - check.checked_at < 300;
  if (fresh && check.state === "verified") return zh ? "最近会话调用通过" : "Recent session call verified";
  if (fresh && check.state === "failed") return zh ? "最近会话调用失败，可重试" : "Recent session call failed; retry available";
  return zh ? "配置就绪，尚无近期调用验证" : "Configured; no recent call verification";
}
