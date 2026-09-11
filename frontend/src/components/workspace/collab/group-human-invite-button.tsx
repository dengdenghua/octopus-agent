import { useEffect, useState, type ComponentProps } from "react";
import { Loader2Icon, UserPlusIcon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";

import { InviteDialog } from "./invite-dialog";

export interface GroupHumanInviteButtonProps extends Omit<
  ComponentProps<typeof Button>,
  "children" | "onClick"
> {
  roomId?: string | null;
  threadId?: string | null;
  onEnsureRoom?: () => Promise<string | null | undefined>;
  onRoomResolved?: (roomId: string) => void;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  iconOnly?: boolean;
  /** Use a persistent parent dialog when this trigger lives in a popover. */
  renderDialog?: boolean;
}

/** A reusable, non-floating trigger for headers and project sidebars. */
export function GroupHumanInviteButton({
  roomId,
  threadId,
  onEnsureRoom,
  onRoomResolved,
  open: controlledOpen,
  onOpenChange,
  iconOnly = false,
  renderDialog = true,
  disabled,
  variant = "ghost",
  size = "sm",
  ...buttonProps
}: GroupHumanInviteButtonProps) {
  const { t } = useI18n();
  const [internalOpen, setInternalOpen] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [prepareError, setPrepareError] = useState<string | null>(null);
  const [resolvedRoomId, setResolvedRoomId] = useState(roomId?.trim() ?? "");

  useEffect(() => {
    setResolvedRoomId(roomId?.trim() ?? "");
  }, [roomId]);

  const open = controlledOpen ?? internalOpen;
  const setOpen = (nextOpen: boolean) => {
    if (controlledOpen === undefined) setInternalOpen(nextOpen);
    onOpenChange?.(nextOpen);
  };

  const handleOpen = async () => {
    if (!onEnsureRoom && resolvedRoomId) {
      setOpen(true);
      return;
    }
    if (!onEnsureRoom) return;

    setResolving(true);
    setPrepareError(null);
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      const prepared = await Promise.race([
        onEnsureRoom(),
        new Promise<never>((_, reject) => {
          timeout = setTimeout(
            () => reject(new Error("邀请准备超时，请重试。")),
            15_000,
          );
        }),
      ]);
      const ensuredRoomId = prepared?.trim() ?? "";
      if (!ensuredRoomId) {
        setPrepareError(t.collab.humanInvite.roomRequired);
        toast.error(t.collab.humanInvite.roomRequired);
        return;
      }
      setResolvedRoomId(ensuredRoomId);
      onRoomResolved?.(ensuredRoomId);
      setOpen(true);
    } catch (error) {
      setPrepareError(
        error instanceof Error
          ? error.message
          : t.collab.humanInvite.roomRequired,
      );
      toast.error(
        error instanceof Error
          ? error.message
          : t.collab.humanInvite.roomRequired,
      );
    } finally {
      clearTimeout(timeout);
      setResolving(false);
    }
  };

  return (
    <>
      <Button
        type="button"
        variant={variant}
        size={size}
        aria-label={t.collab.humanInvite.trigger}
        disabled={disabled || resolving || (!resolvedRoomId && !onEnsureRoom)}
        onClick={() => void handleOpen()}
        {...buttonProps}
      >
        {resolving ? (
          <Loader2Icon className="size-4 animate-spin" />
        ) : (
          <UserPlusIcon className="size-4" />
        )}
        <span className={iconOnly ? "sr-only" : undefined}>
          {t.collab.humanInvite.trigger}
        </span>
      </Button>
      {prepareError && (
        <p role="alert" className="px-2 text-xs text-destructive">
          {prepareError}
        </p>
      )}

      {renderDialog && resolvedRoomId ? (
        <InviteDialog
          open={open}
          onOpenChange={setOpen}
          roomId={resolvedRoomId}
          threadId={threadId}
        />
      ) : null}
    </>
  );
}
