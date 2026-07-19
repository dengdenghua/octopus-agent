import { describe, expect, it } from "vitest";

import type { LocalAgentPartner } from "@/core/agents/api";

import { localPartnerBadge } from "./local-agent-status";

const LABELS = {
  connected: "已连接",
  detected: "已检测到",
  notDetected: "未检测到",
};

function partner(overrides: Partial<LocalAgentPartner>): LocalAgentPartner {
  return {
    id: "codex-cli",
    agent_id: "local_codex_cli",
    name: "Codex CLI",
    default_alias: "Codex CLI 伙伴",
    description: "本地 Codex CLI",
    detected: false,
    registered: false,
    status: "missing",
    ready: false,
    ...overrides,
  };
}

describe("local-agent-status localPartnerBadge", () => {
  it("uses effective_status as the source of truth for registered partners", () => {
    expect(
      localPartnerBadge(
        partner({
          registered: true,
          ready: false,
          status: "registered",
          readiness_status: "missing",
          effective_status: "missing",
        }),
        LABELS,
      ).label,
    ).toBe("已连接 · 需修复");

    expect(
      localPartnerBadge(
        partner({
          registered: true,
          ready: true,
          status: "registered",
          readiness_status: "ready",
          effective_status: "registered",
        }),
        LABELS,
      ).label,
    ).toBe("已连接");
  });

  it("keeps ready-but-unregistered partners connectable", () => {
    expect(
      localPartnerBadge(
        partner({
          detected: true,
          ready: true,
          status: "detected",
          effective_status: "ready",
        }),
        LABELS,
      ).label,
    ).toBe("可连接");
  });

  it("surfaces not-ready setup states from effective_status", () => {
    expect(
      localPartnerBadge(
        partner({
          detected: true,
          status: "detected",
          effective_status: "model_unconfigured",
        }),
        LABELS,
      ).label,
    ).toBe("模型未配置");

    expect(
      localPartnerBadge(
        partner({
          detected: true,
          status: "detected",
          effective_status: "launcher_only",
        }),
        LABELS,
      ).label,
    ).toBe("仅可手动");
  });

  it("falls back to detected and missing labels for legacy payloads", () => {
    expect(localPartnerBadge(partner({ detected: true, status: "detected" }), LABELS).label).toBe(
      "已检测到",
    );
    expect(localPartnerBadge(partner({}), LABELS).label).toBe("未检测到");
  });
});
