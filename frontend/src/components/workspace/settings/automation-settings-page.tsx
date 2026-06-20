import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangleIcon,
  ArrowDownIcon,
  ArrowUpIcon,
  ExternalLinkIcon,
  FolderIcon,
  GlobeIcon,
  Loader2Icon,
  MonitorIcon,
  PlusIcon,
  RefreshCwIcon,
  SaveIcon,
  ShieldIcon,
  TrashIcon,
} from "lucide-react";
import { toast } from "sonner";
import { useNavigate } from "react-router-dom";

import { Alert, AlertDescription } from "@/components/ui/alert";
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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import {
  type Capabilities,
  getCapabilities,
  saveCapabilities,
  restartBackend,
} from "@/core/settings/capabilities-api";
import {
  addPermissionRule,
  type ApprovalRule,
  deletePermissionRule,
  listPermissionRules,
  movePermissionRule,
  type RuleEffect,
} from "@/core/settings/permissions-api";
import { useI18n } from "@/core/i18n/hooks";

function useCapabilities() {
  return useQuery({
    queryKey: ["automation-capabilities"],
    queryFn: () => getCapabilities(),
    staleTime: 60_000,
  });
}

function useSaveCapabilities() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Capabilities) => saveCapabilities(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["automation-capabilities"] });
    },
  });
}

export default function AutomationSettingsPage() {
  const { t } = useI18n();
  const { data, isLoading, error } = useCapabilities();
  const save = useSaveCapabilities();

  const [browserOn, setBrowserOn] = useState<boolean>(true);
  const [desktopOn, setDesktopOn] = useState<boolean>(true);
  const [showRestartDialog, setShowRestartDialog] = useState(false);
  const [isRestarting, setIsRestarting] = useState(false);

  useEffect(() => {
    if (data) {
      setBrowserOn(data.browser_automation);
      setDesktopOn(data.desktop_automation);
    }
  }, [data]);

  const dirty =
    !!data &&
    (data.browser_automation !== browserOn ||
      data.desktop_automation !== desktopOn);

  async function onSave() {
    try {
      const res = await save.mutateAsync({
        browser_automation: browserOn,
        desktop_automation: desktopOn,
      });
      toast.success(res.message, {
        description: t.settings.automation.saveDescription,
        duration: 4000,
      });
      // Implementation note.
      setShowRestartDialog(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleRestart() {
    setIsRestarting(true);
    try {
      const result = await restartBackend();
      if (result.ok) {
        toast.success(t.settings.automation.restarting);
        setShowRestartDialog(false);
      } else {
        toast.error(result.reason || t.settings.automation.restartFailed);
        setIsRestarting(false);
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
      setIsRestarting(false);
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center py-8 text-sm text-muted-foreground">
        <Loader2Icon className="mr-2 h-4 w-4 animate-spin" />
        {t.settings.automation.loading}
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6">
        <div className="py-6 text-sm text-destructive">
          {t.settings.automation.loadFailed}:{" "}
          {error instanceof Error ? error.message : String(error)}
        </div>
        <LocalToolsSection />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">{t.settings.automation.title}</h2>
        <p className="text-sm text-muted-foreground mt-1">
          {t.settings.automation.description}
        </p>
      </div>

      <Alert>
        <AlertTriangleIcon className="h-4 w-4" />
        <AlertDescription>
          <span className="font-medium">
            {t.settings.automation.restartRequiredTitle}
          </span>
          · {t.settings.automation.restartRequiredBody}
        </AlertDescription>
      </Alert>

      <div className="space-y-4">
        <CapabilityCard
          icon={<GlobeIcon className="h-5 w-5" />}
          title={t.settings.automation.browserTitle}
          groupName="browser, browser_act"
          description={t.settings.automation.browserDesc}
          checked={browserOn}
          onCheckedChange={setBrowserOn}
          disabled={save.isPending}
          groupLabel={t.settings.automation.groupLabel}
        />
        <CapabilityCard
          icon={<MonitorIcon className="h-5 w-5" />}
          title={t.settings.automation.desktopTitle}
          groupName="computer"
          description={t.settings.automation.desktopDesc}
          checked={desktopOn}
          onCheckedChange={setDesktopOn}
          disabled={save.isPending}
          groupLabel={t.settings.automation.groupLabel}
        />
      </div>

      <LocalToolsSection />

      <Separator />

      <ApprovalRulesSection />

      <Separator />

      <div className="flex items-center justify-end gap-2">
        <Button
          variant="ghost"
          onClick={() => {
            if (data) {
              setBrowserOn(data.browser_automation);
              setDesktopOn(data.desktop_automation);
            }
          }}
          disabled={!dirty || save.isPending}
        >
          {t.settings.automation.reset}
        </Button>
        <Button onClick={onSave} disabled={!dirty || save.isPending}>
          {save.isPending ? (
            <Loader2Icon className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <SaveIcon className="mr-1.5 h-3.5 w-3.5" />
          )}
          {t.settings.automation.save}
        </Button>
      </div>

      {/* Implementation note. */}
      <Dialog open={showRestartDialog} onOpenChange={setShowRestartDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <RefreshCwIcon className="h-5 w-5" />
              {t.settings.automation.restartConfirmTitle}
            </DialogTitle>
            <DialogDescription>
              {t.settings.automation.restartConfirmBody}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="outline"
              onClick={() => setShowRestartDialog(false)}
              disabled={isRestarting}
            >
              {t.settings.automation.restartLater}
            </Button>
            <Button onClick={handleRestart} disabled={isRestarting}>
              {isRestarting ? (
                <Loader2Icon className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCwIcon className="mr-1.5 h-3.5 w-3.5" />
              )}
              {t.settings.automation.restartNow}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function LocalToolsSection() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const openTool = (path: string) => {
    window.dispatchEvent(new Event("octopus:close-settings"));
    navigate(path);
  };

  return (
    <div className="rounded-lg border bg-muted/20 p-4">
      <div className="mb-3">
        <h3 className="text-sm font-semibold">
          {t.settings.automation.localToolsTitle}
        </h3>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">
          {t.settings.automation.localToolsDesc}
        </p>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <Button
          type="button"
          variant="outline"
          className="justify-start gap-2"
          onClick={() => openTool("/workspace/computer")}
        >
          <MonitorIcon className="h-4 w-4" />
          {t.sidebar.navComputer}
          <ExternalLinkIcon className="ml-auto h-3.5 w-3.5 opacity-60" />
        </Button>
        <Button
          type="button"
          variant="outline"
          className="justify-start gap-2"
          onClick={() => openTool("/workspace/desktop-organizer")}
        >
          <FolderIcon className="h-4 w-4" />
          {t.sidebar.navDesktopOrganizer}
          <ExternalLinkIcon className="ml-auto h-3.5 w-3.5 opacity-60" />
        </Button>
      </div>
    </div>
  );
}

interface CapabilityCardProps {
  icon: React.ReactNode;
  title: string;
  groupName: string;
  description: string;
  checked: boolean;
  onCheckedChange: (next: boolean) => void;
  disabled?: boolean;
  groupLabel?: string;
}

function CapabilityCard({
  icon,
  title,
  groupName,
  description,
  checked,
  onCheckedChange,
  disabled,
  groupLabel = "group:",
}: CapabilityCardProps) {
  return (
    <div className="rounded-lg border border-border/60 bg-card/30 p-4">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
          {icon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <div className="font-medium">{title}</div>
            <span className="rounded-md border border-border/60 bg-background px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">
              {groupLabel} {groupName}
            </span>
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground leading-relaxed">
            {description}
          </p>
        </div>
        <Switch
          checked={checked}
          onCheckedChange={onCheckedChange}
          disabled={disabled}
          className="mt-1 shrink-0"
        />
      </div>
    </div>
  );
}

// ── Approval rules section ────────────────────────────────────────
//
// Per-call allow / deny layered on top of the capability switches.
// Backed by /api/permissions (list + add + delete-by-index) which
// reads/writes data/permissions.json via approval_policy_store.
// The runtime hot-reloads the file each turn, so a rule added here
// affects the next tool call without restart.

function ApprovalRulesSection() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const {
    data: rules = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["approval-rules"],
    queryFn: () => listPermissionRules(),
    staleTime: 30_000,
  });

  const [effect, setEffect] = useState<RuleEffect>("allow");
  const [tool, setTool] = useState("");
  const [argsContains, setArgsContains] = useState("");
  const [reason, setReason] = useState("");

  const addMutation = useMutation({
    mutationFn: () =>
      addPermissionRule({
        effect,
        tool: tool.trim(),
        args_contains: argsContains.trim() || undefined,
        reason: reason.trim() || undefined,
      }),
    onSuccess: (next) => {
      qc.setQueryData(["approval-rules"], next);
      setTool("");
      setArgsContains("");
      setReason("");
    },
    onError: (err) => {
      toast.error(
        `${t.settings.automation.rules.addError}: ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (index: number) => deletePermissionRule(index),
    onSuccess: (next) => {
      qc.setQueryData(["approval-rules"], next);
    },
    onError: (err) => {
      toast.error(
        `${t.settings.automation.rules.deleteError}: ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
    },
  });

  const moveMutation = useMutation({
    mutationFn: ({ from, to }: { from: number; to: number }) =>
      movePermissionRule(from, to),
    onSuccess: (next) => {
      qc.setQueryData(["approval-rules"], next);
    },
    onError: (err) => {
      toast.error(
        `${t.settings.automation.rules.moveError}: ${
          err instanceof Error ? err.message : String(err)
        }`,
      );
    },
  });

  const rowBusy =
    addMutation.isPending || deleteMutation.isPending || moveMutation.isPending;
  const canAdd = tool.trim().length > 0 && !rowBusy;

  return (
    <div className="space-y-3">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground">
          <ShieldIcon className="h-5 w-5" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-medium">
            {t.settings.automation.rules.sectionTitle}
          </div>
          <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
            {t.settings.automation.rules.sectionDescription}
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center text-sm text-muted-foreground">
          <Loader2Icon className="mr-2 h-4 w-4 animate-spin" />
          {t.settings.automation.rules.loading}
        </div>
      ) : error ? (
        <div className="text-sm text-destructive">
          {t.settings.automation.rules.loadFailed}:{" "}
          {error instanceof Error ? error.message : String(error)}
        </div>
      ) : rules.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border/60 bg-muted/30 p-3 text-xs text-muted-foreground">
          {t.settings.automation.rules.emptyState}
        </div>
      ) : (
        <ul className="space-y-1.5">
          {rules.map((rule, index) => (
            <RuleRow
              key={`${rule.effect}-${rule.tool}-${rule.args_contains}-${index}`}
              index={index}
              rule={rule}
              isFirst={index === 0}
              isLast={index === rules.length - 1}
              onDelete={() => deleteMutation.mutate(index)}
              onMoveUp={() =>
                moveMutation.mutate({ from: index, to: index - 1 })
              }
              onMoveDown={() =>
                moveMutation.mutate({ from: index, to: index + 1 })
              }
              busy={rowBusy}
            />
          ))}
        </ul>
      )}

      <p className="text-[11px] text-muted-foreground">
        {t.settings.automation.rules.firstMatchHint}
      </p>

      <div className="rounded-lg border border-border/60 bg-card/30 p-3 space-y-2">
        <div className="text-sm font-medium">
          {t.settings.automation.rules.addTitle}
        </div>
        <div className="grid gap-2 sm:grid-cols-[120px,1fr,1fr]">
          <div className="space-y-1">
            <Label className="text-xs">
              {t.settings.automation.rules.effectLabel}
            </Label>
            <Select
              value={effect}
              onValueChange={(value) => setEffect(value as RuleEffect)}
              disabled={addMutation.isPending}
            >
              <SelectTrigger className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="allow">
                  {t.settings.automation.rules.effectAllow}
                </SelectItem>
                <SelectItem value="deny">
                  {t.settings.automation.rules.effectDeny}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">
              {t.settings.automation.rules.toolLabel}
            </Label>
            <Input
              value={tool}
              onChange={(e) => setTool(e.target.value)}
              placeholder={t.settings.automation.rules.toolPlaceholder}
              disabled={addMutation.isPending}
              className="h-9"
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">
              {t.settings.automation.rules.argsLabel}
            </Label>
            <Input
              value={argsContains}
              onChange={(e) => setArgsContains(e.target.value)}
              placeholder={t.settings.automation.rules.argsPlaceholder}
              disabled={addMutation.isPending}
              className="h-9"
            />
          </div>
        </div>
        <div className="space-y-1">
          <Label className="text-xs">
            {t.settings.automation.rules.reasonLabel}
          </Label>
          <Input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t.settings.automation.rules.reasonPlaceholder}
            disabled={addMutation.isPending}
            className="h-9"
          />
        </div>
        <div className="flex justify-end">
          <Button
            size="sm"
            onClick={() => addMutation.mutate()}
            disabled={!canAdd}
          >
            {addMutation.isPending ? (
              <Loader2Icon className="mr-1.5 h-3.5 w-3.5 animate-spin" />
            ) : (
              <PlusIcon className="mr-1.5 h-3.5 w-3.5" />
            )}
            {addMutation.isPending
              ? t.settings.automation.rules.adding
              : t.settings.automation.rules.addButton}
          </Button>
        </div>
      </div>
    </div>
  );
}

interface RuleRowProps {
  index: number;
  rule: ApprovalRule;
  isFirst: boolean;
  isLast: boolean;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  busy: boolean;
}

function RuleRow({
  index,
  rule,
  isFirst,
  isLast,
  onDelete,
  onMoveUp,
  onMoveDown,
  busy,
}: RuleRowProps) {
  const { t } = useI18n();
  return (
    <li className="flex items-start gap-2 rounded-md border border-border/60 bg-background px-3 py-2 text-sm">
      <span className="mt-0.5 w-6 text-right text-[11px] font-mono text-muted-foreground">
        {index}
      </span>
      <Badge
        variant={rule.effect === "allow" ? "secondary" : "destructive"}
        className="shrink-0"
      >
        {rule.effect === "allow"
          ? t.settings.automation.rules.effectAllow
          : t.settings.automation.rules.effectDeny}
      </Badge>
      <div className="min-w-0 flex-1">
        <div className="font-mono text-xs break-all">{rule.tool}</div>
        {rule.args_contains ? (
          <div className="mt-0.5 text-[11px] text-muted-foreground">
            args contains{" "}
            <span className="font-mono">{rule.args_contains}</span>
          </div>
        ) : null}
        {rule.reason ? (
          <div className="mt-0.5 text-[11px] text-muted-foreground italic">
            {rule.reason}
          </div>
        ) : null}
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        <Button
          variant="ghost"
          size="sm"
          onClick={onMoveUp}
          disabled={busy || isFirst}
          className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground disabled:opacity-30"
          aria-label={t.settings.automation.rules.moveUpButton}
          title={t.settings.automation.rules.moveUpButton}
        >
          <ArrowUpIcon className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onMoveDown}
          disabled={busy || isLast}
          className="h-7 w-7 p-0 text-muted-foreground hover:text-foreground disabled:opacity-30"
          aria-label={t.settings.automation.rules.moveDownButton}
          title={t.settings.automation.rules.moveDownButton}
        >
          <ArrowDownIcon className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onDelete}
          disabled={busy}
          className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
          aria-label={t.settings.automation.rules.deleteButton}
          title={t.settings.automation.rules.deleteButton}
        >
          <TrashIcon className="h-3.5 w-3.5" />
        </Button>
      </div>
    </li>
  );
}
