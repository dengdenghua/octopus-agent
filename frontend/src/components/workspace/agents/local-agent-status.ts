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
