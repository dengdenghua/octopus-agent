import type {
  LocalAgentPartner,
  LocalAgentPartnerDoctorResponse,
} from "@/core/agents/api";

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
      className:
        "bg-emerald-50 text-emerald-700 ring-emerald-100 dark:bg-emerald-950/45 dark:text-emerald-300 dark:ring-emerald-900/70",
    };
  }
  if (partner.registered && effectiveStatus !== "registered") {
    return {
      label: "已连接 · 需修复",
      className:
        "bg-amber-50 text-amber-700 ring-amber-100 dark:bg-amber-950/45 dark:text-amber-300 dark:ring-amber-900/70",
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
      className:
        "bg-amber-50 text-amber-700 ring-amber-100 dark:bg-amber-950/45 dark:text-amber-300 dark:ring-amber-900/70",
    };
  }
  if (
    effectiveStatus === "launcher_only" ||
    effectiveStatus === "headless_unsupported"
  ) {
    return {
      label: "仅可手动",
      className:
        "bg-amber-50 text-amber-700 ring-amber-100 dark:bg-amber-950/45 dark:text-amber-300 dark:ring-amber-900/70",
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
        detail:
          partner.fix_hint ||
          "重新登录、选择模型，或恢复 PATH 中的官方 CLI 命令。",
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
        detail:
          "桌面端账号或免费权益不一定同步到 CLI，需要以 CLI 自己的状态为准。",
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
        detail:
          "如果模型列表为空，通常需要单独处理 CLI 登录、企业网络或模型授权。",
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
        detail:
          "当前入口不能稳定 prompt→stdout 自动派工，先保留为手动伙伴入口。",
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
        detail:
          "可以继续用 Octopus 派工；账号、模型和原生快捷指令仍由该 CLI 自己管理。",
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

const DOCTOR_STATUS_LABELS: Record<string, string> = {
  registered: "已连接",
  ready: "可自动派工",
  model_unconfigured: "模型未配置",
  launcher_only: "仅发现启动器",
  headless_unsupported: "暂不支持 headless",
  missing: "未安装",
  detected: "已检测到",
};

function localPartnerDoctorNextAction(status: string): string {
  if (status === "registered" || status === "ready") {
    return "可直接派工；建议健康检查后再跑重要任务。";
  }
  if (status === "model_unconfigured") {
    return "打开原生 CLI 登录/选模型，并确认 CLI 账号或企业授权可用。";
  }
  if (status === "launcher_only") {
    return "安装官方 headless CLI；桌面/IDE 启动器只能手动使用。";
  }
  if (status === "headless_unsupported") {
    return "回原生 CLI 使用，或等待厂商稳定 prompt-to-stdout 参数。";
  }
  if (status === "missing") {
    return "安装对应官方 CLI，并确认命令进入 PATH。";
  }
  return "打开原生 CLI 复查登录、模型、权限和网络状态。";
}

export function localPartnerDoctorFromPartners(
  partners: LocalAgentPartner[],
): LocalAgentPartnerDoctorResponse | null {
  if (partners.length === 0) return null;
  const groupsByStatus = new Map<
    string,
    {
      status: string;
      label: string;
      count: number;
      partner_ids: string[];
      next_action: string;
    }
  >();
  for (const partner of partners) {
    const status =
      partner.effective_status ||
      partner.readiness_status ||
      partner.status ||
      "missing";
    const group = groupsByStatus.get(status) ?? {
      status,
      label: DOCTOR_STATUS_LABELS[status] ?? status,
      count: 0,
      partner_ids: [],
      next_action: localPartnerDoctorNextAction(status),
    };
    group.count += 1;
    group.partner_ids.push(partner.id);
    groupsByStatus.set(status, group);
  }
  const groups = Array.from(groupsByStatus.values()).sort((a, b) => {
    const aReady = a.status === "registered" || a.status === "ready" ? 0 : 1;
    const bReady = b.status === "registered" || b.status === "ready" ? 0 : 1;
    return aReady - bReady || a.label.localeCompare(b.label);
  });
  const ready = partners.filter((partner) => partner.ready).length;
  const registered = partners.filter((partner) => partner.registered).length;
  const needsAttention =
    partners.length -
    groups
      .filter(
        (group) => group.status === "registered" || group.status === "ready",
      )
      .reduce((total, group) => total + group.count, 0);
  const nextActions = Array.from(
    new Set(
      groups
        .filter(
          (group) => group.status !== "registered" && group.status !== "ready",
        )
        .map((group) => group.next_action)
        .filter(Boolean),
    ),
  ).slice(0, 4);
  return {
    summary: `${ready}/${partners.length} 个本地 CLI 伙伴可自动派工，${needsAttention} 个需要处理。`,
    total: partners.length,
    detected: partners.filter((partner) => partner.detected).length,
    ready,
    registered,
    needs_attention: needsAttention,
    groups,
    next_actions:
      nextActions.length > 0
        ? nextActions
        : ["全部可用伙伴建议先跑健康检查，再执行重要派工。"],
  };
}
