import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircleIcon,
  BotIcon,
  CheckIcon,
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
import {
  listLocalAgentPartners,
  probeLocalAgentPartner,
  registerLocalAgentPartners,
  type LocalAgentPartner,
  type LocalAgentPartnerProbeResponse,
} from "@/core/agents/api";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

const PARTNER_ICONS: Record<string, typeof BotIcon> = {
  "claude-code": TerminalSquareIcon,
  "codex-cli": Code2Icon,
  "codebuddy-cli": Code2Icon,
  openclaw: BotIcon,
};

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

  const partnerBadge = (
    partner: LocalAgentPartner,
  ): {
    label: string;
    className: string;
  } => {
    if (partner.registered) {
      return {
        label: t.localAgentConnect.statusConnected,
        className: "bg-emerald-50 text-emerald-700 ring-emerald-100",
      };
    }
    if (partner.detected && partner.ready) {
      return {
        label: "可连接",
        className: "bg-primary/10 text-primary ring-primary/15",
      };
    }
    if (partner.readiness_status === "model_unconfigured") {
      return {
        label: "模型未配置",
        className: "bg-amber-50 text-amber-700 ring-amber-100",
      };
    }
    if (
      partner.readiness_status === "launcher_only" ||
      partner.readiness_status === "headless_unsupported"
    ) {
      return {
        label: "仅可手动",
        className: "bg-amber-50 text-amber-700 ring-amber-100",
      };
    }
    if (partner.detected) {
      return {
        label: t.localAgentConnect.statusDetected,
        className: "bg-primary/10 text-primary ring-primary/15",
      };
    }
    return {
      label: t.localAgentConnect.statusNotDetected,
      className: "bg-muted text-muted-foreground ring-border",
    };
  };

  const {
    data: partners = [],
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["agents", "local-partners"],
    queryFn: ({ signal }) => listLocalAgentPartners({ signal }),
    enabled: open,
    refetchOnWindowFocus: false,
  });

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
    if (!open || partners.length === 0) return;
    setSelectedIds(
      partners
        .filter((partner) => partner.detected && partner.ready && !partner.registered)
        .map((partner) => partner.id),
    );
    setAliases((prev) => ({
      ...Object.fromEntries(
        partners.map((partner) => [partner.id, partner.default_alias]),
      ),
      ...prev,
    }));
  }, [open, partners]);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectableCount = partners.filter(
    (partner) => partner.detected && partner.ready && !partner.registered,
  ).length;

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
    registerMutation.mutate(
      selected.map((partner) => ({
        id: partner.id,
        alias: aliases[partner.id] || partner.default_alias,
      })),
    );
  };

  const copyCommand = async (command: string) => {
    try {
      await navigator.clipboard.writeText(command);
      toast.success("已复制命令");
    } catch {
      toast.error("复制失败，请手动复制");
    }
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
      <DialogContent className="gap-3 p-4 sm:max-w-2xl">
        <DialogHeader className="pr-8">
          <DialogTitle className="flex items-center gap-2 text-base">
            <BotIcon className="size-4 text-primary" />
            {t.localAgentConnect.title}
          </DialogTitle>
          <DialogDescription className="text-xs">
            {t.localAgentConnect.description}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          {isLoading ? (
            <div className="flex min-h-28 items-center justify-center rounded-lg border border-dashed text-xs text-muted-foreground">
              <Loader2Icon className="mr-2 size-4 animate-spin" />
              {t.localAgentConnect.detecting}
            </div>
          ) : isError ? (
            <div className="flex min-h-28 flex-col items-center justify-center gap-2 rounded-lg border border-dashed text-xs text-muted-foreground">
              <AlertCircleIcon className="size-4 text-destructive" />
              {t.localAgentConnect.detectFailed}
              <Button
                size="sm"
                variant="outline"
                onClick={() => void refetch()}
              >
                {t.localAgentConnect.retryDetect}
              </Button>
            </div>
          ) : (
            partners.map((partner) => {
              const Icon = PARTNER_ICONS[partner.id] ?? BotIcon;
              const avatarUrl = partner.avatar_url?.trim();
              const checked = selectedSet.has(partner.id);
              const disabled =
                !partner.detected ||
                !partner.ready ||
                partner.registered ||
                registerMutation.isPending;
              const badge = partnerBadge(partner);
              const probeResult = probeResults[partner.id];
              const isProbing = probingId === partner.id;
              const commandRows = [
                partner.install_command
                  ? { label: "安装", command: partner.install_command }
                  : null,
                partner.native_command
                  ? { label: "打开原生 CLI", command: partner.native_command }
                  : null,
                partner.native_launch_command
                  ? { label: "进入项目", command: partner.native_launch_command }
                  : null,
                partner.verify_command
                  ? { label: "验证", command: partner.verify_command }
                  : null,
              ].filter(
                (item): item is { label: string; command: string } =>
                  Boolean(item?.command),
              );
              const commandHints = partner.command_hints ?? [];
              const activate = () => togglePartner(partner);
              return (
                <div
                  key={partner.id}
                  role={disabled ? undefined : "button"}
                  tabIndex={disabled ? undefined : 0}
                  onClick={activate}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      activate();
                    }
                  }}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg border border-border-default bg-background/75 p-3 text-left transition-colors",
                    !disabled && "hover:border-primary/25 hover:bg-muted/20",
                    checked && "border-primary/30 bg-primary/5",
                    disabled && "cursor-default opacity-75",
                  )}
                >
                  <span
                    className={cn(
                      "grid size-8 shrink-0 place-items-center rounded-lg border",
                      checked || partner.registered
                        ? "border-primary/25 bg-primary/10 text-primary"
                        : "border-border-default bg-muted text-muted-foreground",
                    )}
                  >
                    {avatarUrl ? (
                      <img
                        src={avatarUrl}
                        alt=""
                        className="size-5 rounded-sm object-contain"
                      />
                    ) : checked || partner.registered ? (
                      <CheckIcon className="size-4" aria-hidden="true" />
                    ) : (
                      <Icon className="size-4" aria-hidden="true" />
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="text-sm font-semibold">
                        {partner.name}
                      </span>
                      <Badge
                        variant="secondary"
                        className={cn(
                          "h-5 rounded-md px-1.5 text-[10px] font-medium ring-1",
                          badge.className,
                        )}
                      >
                        {badge.label}
                      </Badge>
                    </span>
                    <span className="mt-1 block text-xs text-muted-foreground">
                      {partner.description}
                    </span>
                    {partner.readiness_message ? (
                      <span
                        className={cn(
                          "mt-1 block text-[11px]",
                          partner.ready
                            ? "text-emerald-700"
                            : "text-amber-700",
                        )}
                      >
                        {partner.readiness_message}
                      </span>
                    ) : null}
                    {partner.fix_hint && !partner.ready ? (
                      <span className="mt-1 block text-[11px] text-muted-foreground">
                        修复建议：{partner.fix_hint}
                      </span>
                    ) : null}
                    {partner.setup_hint ||
                    partner.interaction_hint ||
                    commandRows.length > 0 ? (
                      <span
                        className="mt-2 block space-y-1 rounded-md border border-border-default/70 bg-muted/20 p-2"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {partner.setup_hint ? (
                          <span className="block text-[11px] text-muted-foreground">
                            {partner.setup_hint}
                          </span>
                        ) : null}
                        {partner.interaction_hint ? (
                          <span className="block text-[11px] leading-relaxed text-muted-foreground">
                            {partner.interaction_hint}
                          </span>
                        ) : null}
                        {commandHints.length > 0 ? (
                          <span className="block space-y-1">
                            {commandHints.map((hint) => (
                              <span
                                key={`${partner.id}-${hint.command}`}
                                className="flex gap-2 rounded border border-border-default/60 bg-background/70 px-2 py-1 text-[10px]"
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
                        {commandRows.length > 0 ? (
                          <span className="flex flex-wrap gap-1">
                            {partner.detected ? (
                              <button
                                type="button"
                                onClick={() => void handleProbe(partner)}
                                disabled={Boolean(probingId)}
                                className="inline-flex max-w-full items-center gap-1 rounded border border-border-default/70 bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground transition hover:border-primary/50 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
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
                                <span>{isProbing ? "检查中" : "健康检查"}</span>
                              </button>
                            ) : null}
                            {commandRows.map((row) => (
                              <button
                                key={`${partner.id}-${row.label}`}
                                type="button"
                                onClick={() => void copyCommand(row.command)}
                                className="inline-flex max-w-full items-center gap-1 rounded border border-border-default/70 bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground transition hover:border-primary/50 hover:text-foreground"
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
                              "mt-1 block rounded border px-2 py-1 text-[11px]",
                              probeResult.ok
                                ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                                : "border-amber-200 bg-amber-50 text-amber-800",
                            )}
                          >
                            <span className="block font-medium">
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
                              <code className="mt-0.5 block truncate font-mono text-[10px] opacity-80">
                                {probeResult.raw_error}
                              </code>
                            ) : null}
                          </span>
                        ) : null}
                      </span>
                    ) : null}
                    {partner.executable ? (
                      <span className="mt-1 block truncate text-[11px] text-muted-foreground/80">
                        {partner.executable}
                      </span>
                    ) : null}
                    <span
                      className="mt-2 block"
                      onClick={(event) => event.stopPropagation()}
                    >
                      <Input
                        value={aliases[partner.id] ?? partner.default_alias}
                        disabled={disabled}
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
                    </span>
                  </span>
                </div>
              );
            })
          )}
        </div>

        <DialogFooter className="items-center justify-between gap-2 border-t pt-3 sm:justify-between">
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
              disabled={selectedIds.length === 0 || registerMutation.isPending}
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
