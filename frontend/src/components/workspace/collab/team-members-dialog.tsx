import { useMemo, useState } from "react";
import {
  CrownIcon,
  EyeIcon,
  Loader2Icon,
  ShieldCheckIcon,
  Trash2Icon,
  UserCogIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  removeTeamParticipant,
  updateTeamParticipant,
  type Team,
  type TeamParticipant,
  type TeamParticipantRole,
} from "@/core/teams";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

interface TeamMembersDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  team: Team | null;
  currentParticipantId: string;
  onTeamChange: (team: Team) => void;
}

const ROLE_META: Record<TeamParticipantRole, {
  label: string;
  descriptionKey: "ownerDesc" | "memberDesc" | "viewerDesc";
  icon: typeof CrownIcon;
}> = {
  owner: {
    label: "Owner",
    descriptionKey: "ownerDesc",
    icon: CrownIcon,
  },
  member: {
    label: "Member",
    descriptionKey: "memberDesc",
    icon: ShieldCheckIcon,
  },
  viewer: {
    label: "Viewer",
    descriptionKey: "viewerDesc",
    icon: EyeIcon,
  },
};

export function TeamMembersDialog({
  open,
  onOpenChange,
  team,
  currentParticipantId,
  onTeamChange,
}: TeamMembersDialogProps) {
  const { t } = useI18n();
  const [busyId, setBusyId] = useState<string | null>(null);
  const participants = useMemo(
    () => (team?.participants ?? []).filter((p) => p.status !== "removed"),
    [team?.participants],
  );
  const ownerCount = participants.filter((p) => p.role === "owner").length;

  const handleRoleChange = async (
    participant: TeamParticipant,
    role: TeamParticipantRole,
  ) => {
    if (!team || role === participant.role) return;
    setBusyId(participant.id);
    try {
      const result = await updateTeamParticipant(team.id, participant.id, { role });
      onTeamChange(result.team);
      toast.success(t.teamMembers.permissionsUpdated);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t.teamMembers.updatePermissionsFailed);
    } finally {
      setBusyId(null);
    }
  };

  const handleRemove = async (participant: TeamParticipant) => {
    if (!team) return;
    setBusyId(participant.id);
    try {
      const result = await removeTeamParticipant(team.id, participant.id);
      onTeamChange(result.team);
      toast.success(t.teamMembers.memberRemoved);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t.teamMembers.removeMemberFailed);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <UserCogIcon className="size-5" />
            {t.teamMembers.title}
          </DialogTitle>
          <DialogDescription>
            {t.teamMembers.description}
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[58vh] overflow-y-auto pr-1">
          <div className="space-y-2">
            {participants.map((participant) => {
              const meta = ROLE_META[participant.role] ?? ROLE_META.viewer;
              const Icon = meta.icon;
              const isSelf = participant.id === currentParticipantId;
              const isLastOwner = participant.role === "owner" && ownerCount <= 1;
              const isBusy = busyId === participant.id;
              return (
                <div
                  key={participant.id}
                  className="flex items-center gap-3 rounded-lg border border-border/70 bg-muted/15 px-3 py-2"
                >
                  <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                    <Icon className="size-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-center gap-2">
                      <span className="truncate text-sm font-medium">
                        {participant.display_name}
                      </span>
                      {isSelf && <Badge variant="outline">You</Badge>}
                      <span
                        className={cn(
                          "size-2 rounded-full",
                          participant.status === "active"
                            ? "bg-emerald-500"
                            : "bg-muted-foreground/35",
                        )}
                      />
                    </div>
                    <div className="truncate text-xs text-muted-foreground">
                      {t.teamMembers[meta.descriptionKey]}
                    </div>
                  </div>

                  <Select
                    value={participant.role}
                    disabled={isBusy || isLastOwner}
                    onValueChange={(value) =>
                      void handleRoleChange(
                        participant,
                        value as TeamParticipantRole,
                      )
                    }
                  >
                    <SelectTrigger size="sm" className="w-32">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(ROLE_META).map(([role, item]) => (
                        <SelectItem key={role} value={role}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-8 rounded-lg text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    disabled={isBusy || isSelf || isLastOwner}
                    onClick={() => void handleRemove(participant)}
                    title={t.teamMembers.removeMember}
                  >
                    {isBusy ? (
                      <Loader2Icon className="size-4 animate-spin" />
                    ) : (
                      <Trash2Icon className="size-4" />
                    )}
                  </Button>
                </div>
              );
            })}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
