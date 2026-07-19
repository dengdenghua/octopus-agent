import type { LocalAgentPartner } from "@/core/agents/api";

export interface LocalPartnerBadgeLabels {
  connected: string;
  detected: string;
  notDetected: string;
}

export function localPartnerBadge(
  partner: LocalAgentPartner,
  labels: LocalPartnerBadgeLabels,
): {
  label: string;
  className: string;
} {
  const effectiveStatus =
    partner.effective_status || partner.readiness_status || partner.status;
  if (effectiveStatus === "registered") {
    return {
      label: labels.connected,
      className: "bg-emerald-50 text-emerald-700 ring-emerald-100",
    };
  }
  if (partner.registered && effectiveStatus !== "registered") {
    return {
      label: "已连接 · 需修复",
      className: "bg-amber-50 text-amber-700 ring-amber-100",
    };
  }
  if (effectiveStatus === "ready") {
    return {
      label: "可连接",
      className: "bg-primary/10 text-primary ring-primary/15",
    };
  }
  if (effectiveStatus === "model_unconfigured") {
    return {
      label: "模型未配置",
      className: "bg-amber-50 text-amber-700 ring-amber-100",
    };
  }
  if (
    effectiveStatus === "launcher_only" ||
    effectiveStatus === "headless_unsupported"
  ) {
    return {
      label: "仅可手动",
      className: "bg-amber-50 text-amber-700 ring-amber-100",
    };
  }
  if (partner.detected) {
    return {
      label: labels.detected,
      className: "bg-primary/10 text-primary ring-primary/15",
    };
  }
  return {
    label: labels.notDetected,
    className: "bg-muted text-muted-foreground ring-border",
  };
}

export interface LocalPartnerSetupStep {
  label: string;
  detail: string;
  tone: "ready" | "action" | "blocked";
}

export function localPartnerSetupSteps(
  partner: LocalAgentPartner,
): LocalPartnerSetupStep[] {
  const effectiveStatus =
    partner.effective_status || partner.readiness_status || partner.status;

  if (partner.registered && effectiveStatus !== "registered") {
    return [
      {
        label: "修复本机 CLI 状态",
        detail: partner.fix_hint || "重新登录、选择模型，或恢复 PATH 中的官方 CLI 命令。",
        tone: "blocked",
      },
      {
        label: "重新健康检查",
        detail: "检查通过后，团队派工才会恢复稳定。",
        tone: "action",
      },
    ];
  }

  if (!partner.detected) {
    return [
      {
        label: "安装官方 CLI",
        detail: partner.install_command
          ? "复制安装命令，安装后重新检测。"
          : "安装对应官方 CLI，并确认命令能在终端中运行。",
        tone: "blocked",
      },
      {
        label: "完成 CLI 登录/授权",
        detail: "桌面端账号或免费权益不一定同步到 CLI，需要以 CLI 自己的状态为准。",
        tone: "action",
      },
    ];
  }

  if (effectiveStatus === "model_unconfigured") {
    return [
      {
        label: "打开原生 CLI",
        detail: "进入项目目录后使用该 CLI 自己的登录、企业网络和模型配置流程。",
        tone: "action",
      },
      {
        label: "选择可用模型",
        detail: "如果模型列表为空，通常需要单独处理 CLI 登录、企业网络或模型授权。",
        tone: "blocked",
      },
      {
        label: "回到 Octopus 健康检查",
        detail: "健康检查通过后才能注册为可自动派工的本地伙伴。",
        tone: "action",
      },
    ];
  }

  if (
    effectiveStatus === "launcher_only" ||
    effectiveStatus === "headless_unsupported"
  ) {
    return [
      {
        label: "使用原生 CLI 手动操作",
        detail: "当前入口不能稳定 prompt→stdout 自动派工，先保留为手动伙伴入口。",
        tone: "blocked",
      },
      {
        label: "安装 headless CLI",
        detail: "如厂商提供 -p/print/headless 模式，安装官方命令后重新检测。",
        tone: "action",
      },
    ];
  }

  if (effectiveStatus === "registered") {
    return [
      {
        label: "已接入团队",
        detail: "可以继续用 Octopus 派工；账号、模型和原生快捷指令仍由该 CLI 自己管理。",
        tone: "ready",
      },
    ];
  }

  if (effectiveStatus === "ready" || partner.ready) {
    return [
      {
        label: "可连接",
        detail: "建议先跑一次健康检查，确认真实 headless 派工可用。",
        tone: "ready",
      },
      {
        label: "注册为团队伙伴",
        detail: "选中后点击连接，Octopus 会创建本地伙伴卡片。",
        tone: "action",
      },
    ];
  }

  if (partner.detected) {
    return [
      {
        label: "打开原生 CLI 排查",
        detail: partner.fix_hint || "先在原生 CLI 中完成登录、授权或模型配置。",
        tone: "action",
      },
    ];
  }

  return [];
}

export function localPartnerFailureKindLabel(kind?: string | null): string {
  switch (kind) {
    case "missing_binary":
      return "命令缺失";
    case "auth":
      return "需要登录";
    case "entitlement":
      return "账号权益";
    case "model":
      return "模型配置";
    case "permission":
      return "权限/信任";
    case "network":
      return "网络环境";
    case "quota":
      return "额度/限流";
    case "version":
      return "版本不兼容";
    case "empty_output":
      return "无输出";
    case "timeout":
      return "执行超时";
    case "unknown":
      return "未分类";
    default:
      return kind ? "检查失败" : "";
  }
}
