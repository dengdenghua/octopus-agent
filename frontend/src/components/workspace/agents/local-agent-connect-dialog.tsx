import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircleIcon,
  BotIcon,
  CheckIcon,
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
  registerLocalAgentPartners,
  type LocalAgentPartner,
} from "@/core/agents/api";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

const PARTNER_ICONS: Record<string, typeof BotIcon> = {
  "claude-code": TerminalSquareIcon,
  "codex-cli": Code2Icon,
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
        .filter((partner) => partner.detected && !partner.registered)
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
    (partner) => partner.detected && !partner.registered,
  ).length;

  const togglePartner = (partner: LocalAgentPartner) => {
    if (!partner.detected || partner.registered || registerMutation.isPending) {
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
              const checked = selectedSet.has(partner.id);
              const disabled =
                !partner.detected ||
                partner.registered ||
                registerMutation.isPending;
              const badge = partnerBadge(partner);
              return (
                <button
                  key={partner.id}
                  type="button"
                  onClick={() => togglePartner(partner)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg border border-border/60 bg-background/75 p-3 text-left transition-colors",
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
                        : "border-border/60 bg-muted text-muted-foreground",
                    )}
                  >
                    {checked || partner.registered ? (
                      <CheckIcon className="size-4" />
                    ) : (
                      <Icon className="size-4" />
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
                </button>
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
