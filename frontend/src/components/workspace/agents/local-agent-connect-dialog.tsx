import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircleIcon,
  BotIcon,
  CheckIcon,
  ChevronDownIcon,
  ClipboardIcon,
  Code2Icon,
  Loader2Icon,
  TerminalSquareIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { copyTextToClipboard } from "@/core/clipboard";
import {
  getLocalAgentPartnersDoctor,
  listLocalAgentPartners,
  probeLocalAgentPartner,
  registerLocalAgentPartners,
  type LocalAgentPartner,
  type LocalAgentPartnerProbeResponse,
} from "@/core/agents/api";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import {
  localPartnerBadge,
  localPartnerDoctorFromPartners,
  localPartnerFailureKindLabel,
  localPartnerSetupSteps,
} from "./local-agent-status";

const PARTNER_ICONS: Record<string, typeof BotIcon> = {
  "claude-code": TerminalSquareIcon,
  "codex-cli": Code2Icon,
  "codebuddy-cli": Code2Icon,
  "opencode-cli": Code2Icon,
  openclaw: BotIcon,
  hermes: BotIcon,
};
const EMPTY_PARTNERS: LocalAgentPartner[] = [];
const PARTNER_ALIAS_PATTERN = /^[A-Za-z0-9\u4e00-\u9fa5\u3000-\u303f ._-]*$/;

export function normalizePartnerAlias(value: string, fallback: string): string {
  return value.trim() || fallback.trim();
}

export function isValidPartnerAlias(value: string): boolean {
  const normalized = value.trim();
  return normalized.length <= 64 && PARTNER_ALIAS_PATTERN.test(normalized);
}

function PartnerAvatar({
  avatarUrl,
  Icon,
}: {
  avatarUrl?: string;
  Icon: typeof BotIcon;
}) {
  const [failedUrl, setFailedUrl] = useState("");
  const showAvatar = Boolean(avatarUrl && avatarUrl !== failedUrl);

  return showAvatar ? (
    <img
      src={avatarUrl}
      alt=""
      className="size-5 rounded-sm object-contain"
      onError={() => setFailedUrl(avatarUrl ?? "")}
    />
  ) : (
    <Icon className="size-4" aria-hidden="true" />
  );
}

export function LocalAgentConnectDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const { t } = useI18n();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [aliases, setAliases] = useState<Record<string, string>>({});
  const [probeResults, setProbeResults] = useState<
    Record<string, LocalAgentPartnerProbeResponse>
  >({});
  const [probingId, setProbingId] = useState("");

  const partnerBadgeLabels = {
    connected: t.localAgentConnect.statusConnected,
    detected: t.localAgentConnect.statusDetected,
    notDetected: t.localAgentConnect.statusNotDetected,
  };

  const {
    data: partners = EMPTY_PARTNERS,
    isLoading,
    isFetching,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["agents", "local-partners"],
    queryFn: ({ signal }) => listLocalAgentPartners({ signal }),
    enabled: open,
    refetchOnWindowFocus: false,
  });
  const { data: doctor, refetch: refetchDoctor } = useQuery({
    queryKey: ["agents", "local-partners", "doctor"],
    queryFn: ({ signal }) => getLocalAgentPartnersDoctor({ signal }),
    enabled: open,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const doctorSummary = doctor ?? localPartnerDoctorFromPartners(partners);

  const registerMutation = useMutation({
    mutationFn: registerLocalAgentPartners,
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["agents"] }),
        queryClient.invalidateQueries({
          queryKey: ["agents", "local-partners"],
        }),
      ]);

      if (result.registered_count > 0) {
        toast.success(
          t.localAgentConnect.registerSuccess(result.registered_count),
        );
        onOpenChange(false);
        return;
      }
      if (result.already_exists_count > 0) {
        toast.success(t.localAgentConnect.alreadyExists);
        onOpenChange(false);
        return;
      }
      toast.error(t.localAgentConnect.noPartnersAvailable);
    },
    onError: (error) => {
      toast.error(
        error instanceof Error
          ? error.message
          : t.localAgentConnect.registerFailed,
      );
    },
  });

  useEffect(() => {
    if (!open) return;
    const nextSelectedIds = partners
      .filter(
        (partner) => partner.detected && partner.ready && !partner.registered,
      )
      .map((partner) => partner.id);
    setSelectedIds((current) =>
      current.length === nextSelectedIds.length &&
      current.every((id, index) => id === nextSelectedIds[index])
        ? current
        : nextSelectedIds,
    );
    if (partners.length > 0) {
      setAliases((prev) => ({
        ...Object.fromEntries(
          partners.map((partner) => [partner.id, partner.default_alias]),
        ),
        ...prev,
      }));
    }
  }, [open, partners]);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectableCount = partners.filter(
    (partner) => partner.detected && partner.ready && !partner.registered,
  ).length;
  const hasInvalidSelectedAlias = partners.some(
    (partner) =>
      selectedSet.has(partner.id) &&
      !isValidPartnerAlias(aliases[partner.id] ?? partner.default_alias),
  );

  const togglePartner = (partner: LocalAgentPartner) => {
    if (
      !partner.detected ||
      !partner.ready ||
      partner.registered ||
      registerMutation.isPending
    ) {
      return;
    }
    setSelectedIds((prev) =>
      prev.includes(partner.id)
        ? prev.filter((id) => id !== partner.id)
        : [...prev, partner.id],
    );
  };

  const handleConfirm = () => {
    const selected = partners.filter((partner) => selectedSet.has(partner.id));
    if (selected.length === 0) {
      toast.error(t.localAgentConnect.noPartnerSelected);
      return;
    }
    if (hasInvalidSelectedAlias) {
      toast.error("伙伴名称只能包含文字、数字、空格、点、短横线和下划线");
      return;
    }
    registerMutation.mutate(
      selected.map((partner) => ({
        id: partner.id,
        alias: normalizePartnerAlias(
          aliases[partner.id] ?? "",
          partner.default_alias,
        ),
      })),
    );
  };

  const copyCommand = async (command: string) => {
    try {
      await copyTextToClipboard(command);
      toast.success("已复制命令");
    } catch {
      toast.error("复制失败，请手动复制");
    }
  };

  const handleRefetch = async () => {
    await Promise.all([refetch(), refetchDoctor()]);
  };

  const handleProbe = async (partner: LocalAgentPartner) => {
    if (!partner.detected || probingId) return;
    setProbingId(partner.id);
    try {
      const result = await probeLocalAgentPartner(partner.id);
      setProbeResults((prev) => ({ ...prev, [partner.id]: result }));
      if (result.ok) {
        toast.success(`${partner.name} 健康检查通过`);
      } else {
        toast.error(result.failure_title || `${partner.name} 健康检查未通过`);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "健康检查失败");
    } finally {
      setProbingId("");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[calc(100dvh-1rem)] flex-col gap-0 overflow-hidden p-0 sm:max-h-[min(92dvh,56rem)] sm:max-w-3xl">
        <DialogHeader className="shrink-0 px-4 pb-3 pt-4 pr-12 text-left">
          <DialogTitle className="flex items-center gap-2 text-base">
            <BotIcon className="size-4 text-primary" />
            {t.localAgentConnect.title}
          </DialogTitle>
          <DialogDescription className="text-xs">
            {t.localAgentConnect.description}
          </DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto border-y border-border-subtle px-4 py-3 overscroll-contain">
          {isLoading ? (
            <div
              role="status"
              className="flex min-h-28 items-center justify-center rounded-lg border border-dashed text-xs text-muted-foreground"
            >
              <Loader2Icon className="mr-2 size-4 animate-spin" />
              {t.localAgentConnect.detecting}
            </div>
          ) : isError ? (
            <div
              role="alert"
              className="flex min-h-28 flex-col items-center justify-center gap-2 rounded-lg border border-dashed text-xs text-muted-foreground"
            >
              <AlertCircleIcon className="size-4 text-destructive" />
              {t.localAgentConnect.detectFailed}
              <Button
                size="sm"
                variant="outline"
                disabled={isFetching}
                onClick={() => void handleRefetch()}
              >
                {isFetching ? (
                  <Loader2Icon className="mr-1 size-3.5 animate-spin" />
                ) : null}
                {t.localAgentConnect.retryDetect}
              </Button>
            </div>
          ) : (
            <>
              {doctorSummary ? (
                <div className="rounded-lg border border-border-default bg-muted/20 p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="font-medium text-foreground">
                      本机 CLI Doctor
                    </span>
                    <span className="rounded bg-success/5 px-1.5 py-0.5 text-success dark:text-success">
                      可派工 {doctorSummary.ready}
                    </span>
                    <span className="rounded bg-warning/5 px-1.5 py-0.5 text-warning dark:text-warning">
                      需处理 {doctorSummary.needs_attention}
                    </span>
                    <span className="rounded bg-background px-1.5 py-0.5 text-muted-foreground">
                      已连接 {doctorSummary.registered}
                    </span>
                  </div>
                  <div className="mt-1 text-muted-foreground">
                    {doctorSummary.summary}
                  </div>
                  {doctorSummary.next_actions.length > 0 ? (
                    <div className="mt-1 line-clamp-2 text-warning">
                      下一步：
                      {doctorSummary.next_actions.slice(0, 2).join("；")}
                    </div>
                  ) : null}
                  {doctorSummary.groups.length > 0 ? (
                    <div className="mt-1 flex flex-wrap gap-1">
                      {doctorSummary.groups.slice(0, 4).map((group) => (
                        <span
                          key={group.status}
                          className="inline-flex max-w-full items-center gap-1 rounded border border-border-default/70 bg-background/80 px-1.5 py-0.5 text-muted-foreground"
                          title={group.next_action}
                        >
                          <span className="shrink-0 font-medium text-foreground">
                            {group.label}
                          </span>
                          <span className="min-w-0 truncate">
                            {group.partner_ids.join("、")}
                          </span>
                          <span className="shrink-0 rounded bg-muted px-1 font-mono text-xs">
                            {group.count}
                          </span>
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
              {partners.length === 0 ? (
                <div
                  role="status"
                  className="flex min-h-32 flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 text-center text-xs text-muted-foreground"
                >
                  <TerminalSquareIcon className="size-5 opacity-60" />
                  <span>{t.localAgentConnect.noPartnersAvailable}</span>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={isFetching}
                    onClick={() => void handleRefetch()}
                  >
                    {isFetching ? (
                      <Loader2Icon className="mr-1 size-3.5 animate-spin" />
                    ) : null}
                    {t.localAgentConnect.retryDetect}
                  </Button>
                </div>
              ) : null}
              {partners
                .filter(
                  (partner) => partner.detected || partner.registered,
                )
                .map((partner) => {
                const Icon = PARTNER_ICONS[partner.id] ?? BotIcon;
                const avatarUrl = `/api/agents/local-partners/${partner.id}/brand-avatar`;
                const checked = selectedSet.has(partner.id);
                const disabled =
                  !partner.detected ||
                  !partner.ready ||
                  partner.registered ||
                  registerMutation.isPending;
                const badge = localPartnerBadge(partner, partnerBadgeLabels);
                const setupSteps = localPartnerSetupSteps(partner);
                const diagnosticItems = partner.diagnostic_items ?? [];
                const probeResult = probeResults[partner.id];
                const probeFailureKindLabel = localPartnerFailureKindLabel(
                  probeResult?.failure_kind,
                );
                const isProbing = probingId === partner.id;
                const aliasValue = aliases[partner.id] ?? partner.default_alias;
                const aliasInvalid = !isValidPartnerAlias(aliasValue);
                const commandRows = [
                  partner.install_command
                    ? {
                        label: "复制安装命令",
                        command: partner.install_command,
                      }
                    : null,
                  partner.native_launch_command
                    ? {
                        label: "复制进入项目命令",
                        command: partner.native_launch_command,
                      }
                    : null,
                  partner.native_command
                    ? { label: "复制原生命令", command: partner.native_command }
                    : null,
                  partner.verify_command
                    ? { label: "复制验证命令", command: partner.verify_command }
                    : null,
                ].filter((item): item is { label: string; command: string } =>
                  Boolean(item?.command),
                );
                const commandHints = partner.command_hints ?? [];
                const activate = () => togglePartner(partner);
                const hasDetails = Boolean(
                  partner.setup_hint ||
                  partner.interaction_hint ||
                  setupSteps.length > 0 ||
                  diagnosticItems.length > 0 ||
                  commandRows.length > 0 ||
                  partner.executable,
                );
                return (
                  <div
                    key={partner.id}
                    className={cn(
                      "w-full rounded-lg border border-border-default bg-background/75 p-3 text-left transition-colors",
                      checked && "border-primary/30 bg-primary/5",
                      disabled && "bg-muted/10",
                    )}
                  >
                    <div className="flex items-start gap-3">
                      {disabled ? (
                        <span
                          aria-hidden="true"
                          className={cn(
                            "grid size-9 shrink-0 place-items-center rounded-lg border",
                            partner.registered
                              ? "border-primary/30 bg-primary/10 text-primary"
                              : "border-border-default bg-muted text-muted-foreground",
                          )}
                        >
                          <PartnerAvatar avatarUrl={avatarUrl} Icon={Icon} />
                        </span>
                      ) : (
                        <button
                          type="button"
                          aria-pressed={checked}
                          aria-label={`${checked ? "取消选择" : "选择"} ${partner.name}`}
                          onClick={activate}
                          className={cn(
                            "relative grid size-9 shrink-0 place-items-center rounded-lg border transition-colors",
                            checked
                              ? "border-primary/30 bg-primary/10 text-primary"
                              : "border-border-default bg-muted text-muted-foreground",
                            "hover:border-primary/40 hover:bg-primary/10",
                          )}
                        >
                          <PartnerAvatar avatarUrl={avatarUrl} Icon={Icon} />
                          {checked ? (
                            <span className="absolute -right-1 -top-1 grid size-4 place-items-center rounded-full bg-primary text-primary-foreground shadow-sm">
                              <CheckIcon
                                className="size-2.5"
                                aria-hidden="true"
                              />
                            </span>
                          ) : null}
                        </button>
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-semibold">
                            {partner.name}
                          </span>
                          <Badge
                            variant="secondary"
                            className={cn(
                              "h-5 rounded-md px-1.5 text-xs font-medium ring-1",
                              badge.className,
                            )}
                          >
                            {badge.label}
                          </Badge>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {partner.description}
                        </p>
                        {partner.readiness_message ? (
                          <p
                            className={cn(
                              "mt-1 text-xs",
                              partner.ready
                                ? "text-success"
                                : "text-warning",
                            )}
                          >
                            {partner.readiness_message}
                          </p>
                        ) : null}
                        {partner.fix_hint && !partner.ready ? (
                          <p
                            className="mt-1 line-clamp-2 text-xs text-muted-foreground"
                            title={partner.fix_hint}
                          >
                            修复建议：{partner.fix_hint}
                          </p>
                        ) : null}
                      </div>
                    </div>
                    {hasDetails ? (
                      <details className="group mt-2 overflow-hidden rounded-md border border-border-default/70 bg-muted/15">
                        <summary
                          aria-label={`${partner.name} 接入与诊断详情`}
                          className="flex cursor-pointer list-none items-center justify-between gap-2 px-2.5 py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted/35 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/35"
                        >
                          <span>接入与诊断详情</span>
                          <ChevronDownIcon className="size-3.5 shrink-0 transition-transform group-open:rotate-180" />
                        </summary>
                        <div className="space-y-1 border-t border-border-default/70 p-2">
                          {setupSteps.length > 0 ? (
                            <span className="block space-y-1">
                              <span className="block text-xs font-medium uppercase tracking-wide text-muted-foreground/80">
                                连接步骤
                              </span>
                              {setupSteps.map((step, index) => (
                                <span
                                  key={`${partner.id}-setup-${step.label}`}
                                  className={cn(
                                    "flex gap-2 rounded border px-2 py-1 text-xs",
                                    step.tone === "ready"
                                      ? "border-success/20 bg-success/5 text-success dark:border-success/70"
                                      : step.tone === "blocked"
                                        ? "border-warning/30 bg-warning/5 text-warning dark:border-warning/70"
                                        : "border-border-default/60 bg-background/70 text-muted-foreground",
                                  )}
                                >
                                  <span className="grid size-4 shrink-0 place-items-center rounded-full bg-background/80 font-mono text-xs">
                                    {index + 1}
                                  </span>
                                  <span className="min-w-0">
                                    <span className="block font-medium">
                                      {step.label}
                                    </span>
                                    <span className="block opacity-85">
                                      {step.detail}
                                    </span>
                                  </span>
                                </span>
                              ))}
                            </span>
                          ) : null}
                          {partner.setup_hint ? (
                            <span className="block text-xs text-muted-foreground">
                              {partner.setup_hint}
                            </span>
                          ) : null}
                          {partner.interaction_hint ? (
                            <span className="block text-xs leading-relaxed text-muted-foreground">
                              {partner.interaction_hint}
                            </span>
                          ) : null}
                          {diagnosticItems.length > 0 ? (
                            <span className="grid grid-cols-1 gap-1 sm:grid-cols-2">
                              {diagnosticItems.map((item) => (
                                <span
                                  key={`${partner.id}-diagnostic-${item.label}`}
                                  className={cn(
                                    "rounded border px-2 py-1 text-xs",
                                    item.tone === "ready"
                                      ? "border-success/20 bg-success/5 text-success dark:border-success/70"
                                      : item.tone === "blocked"
                                        ? "border-warning/30 bg-warning/5 text-warning dark:border-warning/70"
                                        : item.tone === "warning"
                                          ? "border-warning/20 bg-warning/5 text-warning dark:border-warning/60"
                                          : "border-border-default/60 bg-background/70 text-muted-foreground",
                                  )}
                                >
                                  <span className="block font-medium">
                                    {item.label}：{item.value}
                                  </span>
                                  {item.detail ? (
                                    <span className="mt-0.5 block text-xs opacity-80">
                                      {item.detail}
                                    </span>
                                  ) : null}
                                </span>
                              ))}
                            </span>
                          ) : null}
                          {commandHints.length > 0 ? (
                            <span className="block space-y-1">
                              {commandHints.map((hint) => (
                                <span
                                  key={`${partner.id}-${hint.command}`}
                                  className="flex gap-2 rounded border border-border-default/60 bg-background/70 px-2 py-1 text-xs"
                                >
                                  <code className="shrink-0 font-mono text-foreground">
                                    {hint.command}
                                  </code>
                                  <span className="shrink-0 text-muted-foreground/80">
                                    {hint.scope}
                                  </span>
                                  <span className="min-w-0 text-muted-foreground">
                                    {hint.behavior}
                                  </span>
                                </span>
                              ))}
                            </span>
                          ) : null}
                          {partner.native_launch_cwd ? (
                            <span className="block truncate rounded border border-border-default/60 bg-background/70 px-2 py-1 text-xs text-muted-foreground">
                              工作目录：
                              <code
                                className="font-mono text-foreground"
                                title={partner.native_launch_cwd}
                              >
                                {partner.native_launch_cwd}
                              </code>
                            </span>
                          ) : null}
                          {commandRows.length > 0 ? (
                            <span className="flex flex-wrap gap-1">
                              {partner.detected ? (
                                <button
                                  type="button"
                                  onClick={() => void handleProbe(partner)}
                                  disabled={Boolean(probingId)}
                                  className="inline-flex max-w-full items-center gap-1 rounded border border-border-default/70 bg-background px-1.5 py-0.5 text-xs text-muted-foreground transition hover:border-primary/50 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
                                >
                                  {isProbing ? (
                                    <Loader2Icon
                                      className="size-3 animate-spin"
                                      aria-hidden="true"
                                    />
                                  ) : (
                                    <CheckIcon
                                      className="size-3"
                                      aria-hidden="true"
                                    />
                                  )}
                                  <span>
                                    {isProbing ? "检查中" : "健康检查"}
                                  </span>
                                </button>
                              ) : null}
                              {commandRows.map((row) => (
                                <button
                                  key={`${partner.id}-${row.label}`}
                                  type="button"
                                  onClick={() => void copyCommand(row.command)}
                                  className="inline-flex max-w-full items-center gap-1 rounded border border-border-default/70 bg-background px-1.5 py-0.5 text-xs text-muted-foreground transition hover:border-primary/50 hover:text-foreground"
                                  title={row.command}
                                >
                                  <ClipboardIcon
                                    className="size-3"
                                    aria-hidden="true"
                                  />
                                  <span>{row.label}</span>
                                  <code className="max-w-[180px] truncate font-mono">
                                    {row.command}
                                  </code>
                                </button>
                              ))}
                            </span>
                          ) : null}
                          {probeResult ? (
                            <span
                              className={cn(
                                "mt-1 block rounded border px-2 py-1 text-xs",
                                probeResult.ok
                                  ? "border-success/30 bg-success/5 text-success dark:border-success/70"
                                  : "border-warning/30 bg-warning/5 text-warning dark:border-warning/70",
                              )}
                            >
                              <span className="block font-medium">
                                {!probeResult.ok && probeFailureKindLabel ? (
                                  <span className="mr-1 inline-flex rounded bg-background/80 px-1.5 py-0.5 text-xs font-medium">
                                    {probeFailureKindLabel}
                                  </span>
                                ) : null}
                                {probeResult.ok
                                  ? "健康检查通过，可真实派工"
                                  : probeResult.failure_title ||
                                    "健康检查未通过"}
                                {typeof probeResult.elapsed_ms === "number"
                                  ? `（${probeResult.elapsed_ms}ms）`
                                  : ""}
                              </span>
                              {!probeResult.ok && probeResult.fix_hint ? (
                                <span className="mt-0.5 block">
                                  建议：{probeResult.fix_hint}
                                </span>
                              ) : null}
                              {!probeResult.ok && probeResult.raw_error ? (
                                <code className="mt-0.5 block truncate font-mono text-xs opacity-80">
                                  {probeResult.raw_error}
                                </code>
                              ) : null}
                            </span>
                          ) : null}
                          {partner.executable ? (
                            <code
                              className="block truncate rounded border border-border-default/60 bg-background/70 px-2 py-1 font-mono text-xs text-muted-foreground"
                              title={partner.executable}
                            >
                              {partner.executable}
                            </code>
                          ) : null}
                        </div>
                      </details>
                    ) : null}
                    {!disabled ? (
                      <div className="mt-2">
                        <Input
                          value={aliasValue}
                          maxLength={64}
                          aria-invalid={aliasInvalid}
                          onChange={(event) =>
                            setAliases((prev) => ({
                              ...prev,
                              [partner.id]: event.target.value,
                            }))
                          }
                          className="h-8 max-w-sm rounded-lg bg-background text-xs"
                          aria-label={t.localAgentConnect.partnerNameAria(
                            partner.name,
                          )}
                        />
                        {aliasInvalid ? (
                          <p className="mt-1 text-xs text-destructive">
                            仅支持文字、数字、空格、点、短横线和下划线
                          </p>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </>
          )}
        </div>

        <DialogFooter className="shrink-0 flex-row items-center justify-between gap-2 px-4 py-3 sm:justify-between">
          <span className="text-xs text-muted-foreground">
            {t.localAgentConnect.availableCount(selectableCount)}
          </span>
          <span className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => onOpenChange(false)}
              disabled={registerMutation.isPending}
            >
              {t.localAgentConnect.cancel}
            </Button>
            <Button
              size="sm"
              disabled={
                selectedIds.length === 0 ||
                hasInvalidSelectedAlias ||
                registerMutation.isPending
              }
              onClick={handleConfirm}
            >
              {registerMutation.isPending ? (
                <Loader2Icon className="mr-1 size-3.5 animate-spin" />
              ) : null}
              {t.localAgentConnect.connectSelected(selectedIds.length)}
            </Button>
          </span>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
