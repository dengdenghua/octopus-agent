import { describe, expect, it } from "vitest";

import type { LocalAgentPartner } from "@/core/agents/api";

import {
  localPartnerBadge,
  localPartnerDoctorFromPartners,
  localPartnerFailureKindLabel,
  localPartnerSetupSteps,
} from "./local-agent-status";

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

describe("local-agent-status localPartnerSetupSteps", () => {
  it("turns missing partners into an install and CLI-auth checklist", () => {
    const steps = localPartnerSetupSteps(
      partner({
        detected: false,
        install_command: "npm install -g vendor-cli",
      }),
    );

    expect(steps.map((step) => step.label)).toEqual([
      "安装官方 CLI",
      "完成 CLI 登录/授权",
    ]);
    expect(steps[1].detail).toContain("桌面端账号或免费权益不一定同步到 CLI");
  });

  it("turns model-unconfigured partners into a native model setup checklist", () => {
    const steps = localPartnerSetupSteps(
      partner({
        id: "trae-cli",
        detected: true,
        status: "detected",
        effective_status: "model_unconfigured",
        readiness_status: "model_unconfigured",
      }),
    );

    expect(steps.map((step) => step.label)).toEqual([
      "打开原生 CLI",
      "选择可用模型",
      "回到 Octopus 健康检查",
    ]);
    expect(steps[1].tone).toBe("blocked");
  });

  it("prioritizes repair guidance for registered partners that became unavailable", () => {
    const steps = localPartnerSetupSteps(
      partner({
        detected: false,
        registered: true,
        status: "registered",
        effective_status: "missing",
        fix_hint: "恢复 codex 命令到 PATH。",
      }),
    );

    expect(steps.map((step) => step.label)).toEqual([
      "修复本机 CLI 状态",
      "重新健康检查",
    ]);
    expect(steps[0].detail).toBe("恢复 codex 命令到 PATH。");
  });

  it("keeps ready partners on the shortest connect path", () => {
    const steps = localPartnerSetupSteps(
      partner({
        detected: true,
        ready: true,
        status: "detected",
        effective_status: "ready",
      }),
    );

    expect(steps.map((step) => step.label)).toEqual([
      "可连接",
      "注册为团队伙伴",
    ]);
    expect(steps[0].tone).toBe("ready");
  });
});

describe("local-agent-status localPartnerFailureKindLabel", () => {
  it("maps actionable probe failure kinds to short labels", () => {
    expect(localPartnerFailureKindLabel("entitlement")).toBe("账号权益");
    expect(localPartnerFailureKindLabel("version")).toBe("版本不兼容");
    expect(localPartnerFailureKindLabel("missing_binary")).toBe("命令缺失");
    expect(localPartnerFailureKindLabel("")).toBe("");
    expect(localPartnerFailureKindLabel(null)).toBe("");
    expect(localPartnerFailureKindLabel("vendor_specific")).toBe("检查失败");
  });
});

describe("local-agent-status localPartnerDoctorFromPartners", () => {
  it("groups machine readiness by effective status", () => {
    const doctor = localPartnerDoctorFromPartners([
      partner({
        id: "codex-cli",
        detected: true,
        ready: true,
        registered: true,
        status: "registered",
        effective_status: "registered",
      }),
      partner({
        id: "codebuddy-cli",
        detected: true,
        ready: true,
        status: "detected",
        effective_status: "ready",
      }),
      partner({
        id: "trae-cli",
        detected: true,
        status: "detected",
        effective_status: "model_unconfigured",
      }),
      partner({
        id: "qoder-cli",
        detected: false,
        status: "missing",
        effective_status: "missing",
      }),
    ]);

    expect(doctor?.summary).toBe("2/4 个本地 CLI 伙伴可自动派工，2 个需要处理。");
    expect(doctor?.ready).toBe(2);
    expect(doctor?.registered).toBe(1);
    expect(doctor?.needs_attention).toBe(2);
    expect(
      Object.fromEntries(
        (doctor?.groups ?? []).map((group) => [group.status, group.partner_ids]),
      ),
    ).toEqual({
      ready: ["codebuddy-cli"],
      registered: ["codex-cli"],
      missing: ["qoder-cli"],
      model_unconfigured: ["trae-cli"],
    });
    expect(doctor?.next_actions[0]).toContain("安装对应官方 CLI");
    expect(doctor?.next_actions[1]).toContain("打开原生 CLI");
  });
});
