import { useState, useRef } from "react";
import {
  CameraIcon,
  MailIcon,
  TrashIcon,
  SaveIcon,
  Link2Icon,
  CoinsIcon,
  RefreshCwIcon,
  AlertTriangleIcon,
  UserIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useProfile,
  useUpdateProfile,
  useUploadAvatar,
  usePrivacySettings,
  useUpdatePrivacySettings,
} from "@/core/account";
import { useI18n } from "@/core/i18n/hooks";
import { useMoliliLink, useRefreshMoliliCredits } from "@/core/molili";

function formatCredits(
  n: number | undefined | null,
  t: { numberFormat: { yi: string; wan: string } },
): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  if (n >= 100_000_000)
    return `${(n / 100_000_000).toFixed(1)}${t.numberFormat.yi}`;
  if (n >= 10_000)
    return `${(n / 10_000).toFixed(n >= 100_000 ? 0 : 1)}${t.numberFormat.wan}`;
  if (n >= 1_000) return n.toLocaleString();
  return String(n);
}

export default function AccountSettingsPage() {
  const { t } = useI18n();
  const { data: profile, isLoading: profileLoading } = useProfile();
  const { data: privacy, isLoading: privacyLoading } = usePrivacySettings();
  const updateProfile = useUpdateProfile();
  const uploadAvatar = useUploadAvatar();
  const updatePrivacy = useUpdatePrivacySettings();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [displayName, setDisplayName] = useState(profile?.display_name || "");
  const [bio, setBio] = useState(profile?.bio || "");
  const [unlinkAccount, setUnlinkAccount] = useState<{
    provider: string;
    email?: string;
  } | null>(null);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");

  const handleAvatarClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toast.error(t.settings.account.profile.avatar);
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error(t.accountSettings.avatarTooLarge);
      return;
    }
    uploadAvatar.mutate(file);
  };

  const handleSaveProfile = () => {
    updateProfile.mutate({
      display_name: displayName || undefined,
      bio: bio || undefined,
    });
  };

  const handleUnlink = () => {
    if (unlinkAccount) {
      toast.info(
        `${unlinkAccount.provider} ${unlinkAccount.email ?? ""} ${t.common.unlink}`,
      );
      setUnlinkAccount(null);
    }
  };

  const handleDeleteAccount = () => {
    if (deleteConfirmText !== "DELETE") {
      toast.error(t.accountSettings.typeToConfirm);
      return;
    }
    toast.info(t.settings.account.dangerZone.deleteAccount);
    setShowDeleteDialog(false);
    setDeleteConfirmText("");
  };

  const isLoading = profileLoading || privacyLoading;

  if (isLoading && !profile && !privacy) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-96" />
        <div className="space-y-4">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <OfficialCreditsCard />

      {/* Profile */}
      <section>
        <div className="mb-3">
          <h3 className="text-sm font-medium">
            {t.settings.account.profile.title}
          </h3>
          <p className="text-muted-foreground text-xs mt-0.5">
            {t.settings.account.profile.description}
          </p>
        </div>
        <div className="rounded-xl border bg-card">
          <div className="p-5">
            <div className="flex items-start gap-4">
              <div className="relative group flex-shrink-0">
                <Avatar
                  className="size-14 border border-border/70 bg-background ring-2 ring-transparent transition group-hover:ring-primary/20 cursor-pointer"
                  onClick={handleAvatarClick}
                >
                  <AvatarImage src={profile?.avatar_url} />
                  <AvatarFallback className="bg-muted/50 text-base font-medium text-foreground">
                    {profile?.display_name?.[0] || profile?.username?.[0] || (
                      <UserIcon className="size-5 text-muted-foreground" />
                    )}
                  </AvatarFallback>
                </Avatar>
                <button
                  type="button"
                  onClick={handleAvatarClick}
                  className="absolute inset-0 flex items-center justify-center rounded-full bg-black/0 text-white opacity-0 transition group-hover:bg-black/40 group-hover:opacity-100"
                >
                  <CameraIcon className="size-4" />
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={handleFileChange}
                />
                <p className="text-[10px] text-muted-foreground text-center mt-1.5">
                  {t.accountSettings.clickToChangeAvatar}
                </p>
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <p className="font-medium">
                    {profile?.display_name || profile?.username || "User"}
                  </p>
                  <span className="text-muted-foreground text-sm">
                    @{profile?.username}
                  </span>
                </div>
                <p className="text-muted-foreground text-sm flex items-center gap-1.5 mt-0.5">
                  <MailIcon className="size-3.5" />
                  {profile?.email || "—"}
                </p>
                <p className="text-[11px] text-muted-foreground mt-2">
                  {t.accountSettings.systemManaged}
                </p>
              </div>
            </div>
          </div>

          <Separator />

          <div className="p-5 space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="displayName" className="text-xs">
                {t.settings.account.profile.displayName}
              </Label>
              <Input
                id="displayName"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder={t.settings.account.profile.displayNamePlaceholder}
                className="h-9 text-sm"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="bio" className="text-xs">
                {t.settings.account.profile.bio}
              </Label>
              <textarea
                id="bio"
                value={bio}
                onChange={(e) => setBio(e.target.value)}
                placeholder={t.settings.account.profile.bioPlaceholder}
                maxLength={500}
                className="border-input bg-background ring-offset-background placeholder:text-muted-foreground focus-visible:ring-ring flex min-h-[64px] w-full rounded-lg border px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-none"
              />
              <p className="text-muted-foreground text-[11px] text-right">
                {bio.length}/500
              </p>
            </div>
          </div>

          <Separator />

          <div className="flex items-center justify-end px-5 py-3">
            <Button
              size="sm"
              onClick={handleSaveProfile}
              disabled={updateProfile.isPending}
            >
              <SaveIcon className="mr-1.5 size-3.5" />
              {updateProfile.isPending
                ? t.settings.account.profile.saving
                : t.settings.account.profile.saveChanges}
            </Button>
          </div>
        </div>
      </section>

      {/* Linked Accounts */}
      <section>
        <div className="mb-3">
          <h3 className="text-sm font-medium">
            {t.settings.account.linkedAccounts.title}
          </h3>
          <p className="text-muted-foreground text-xs mt-0.5">
            {t.settings.account.linkedAccounts.description}
          </p>
        </div>
        <div className="rounded-xl border bg-card divide-y">
          {profile?.linked_accounts?.map((account) => (
            <div
              key={account.provider}
              className="flex items-center justify-between px-5 py-3"
            >
              <div className="flex items-center gap-3">
                <div className="flex size-8 items-center justify-center rounded-lg bg-muted">
                  {account.provider === "google" && (
                    <svg className="size-4" viewBox="0 0 24 24">
                      <path
                        fill="currentColor"
                        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                      />
                      <path
                        fill="currentColor"
                        d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                      />
                      <path
                        fill="currentColor"
                        d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                      />
                      <path
                        fill="currentColor"
                        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                      />
                    </svg>
                  )}
                  {account.provider === "github" && (
                    <svg className="size-4" viewBox="0 0 24 24">
                      <path
                        fill="currentColor"
                        d="M12 1C5.92 1 1 5.92 1 12c0 4.87 3.15 8.99 7.52 10.44.55.1.75-.24.75-.53v-1.86c-3.06.66-3.7-1.47-3.7-1.47-.5-1.27-1.22-1.61-1.22-1.61-.99-.68.08-.66.08-.66 1.1.08 1.68 1.13 1.68 1.13.97 1.67 2.55 1.19 3.17.91.1-.71.38-1.19.69-1.46-2.44-.28-5.01-1.22-5.01-5.44 0-1.2.43-2.19 1.13-2.96-.11-.28-.49-1.4.11-2.92 0 0 .92-.3 3.02 1.13a10.5 10.5 0 0 1 5.51 0c2.1-1.43 3.02-1.13 3.02-1.13.6 1.52.22 2.64.11 2.92.7.77 1.13 1.76 1.13 2.96 0 4.23-2.57 5.16-5.02 5.43.39.34.74 1.01.74 2.03v3.01c0 .29.2.64.75.53C19.85 20.99 23 16.87 23 12c0-6.08-4.92-11-11-11z"
                      />
                    </svg>
                  )}
                </div>
                <div>
                  <p className="text-sm font-medium capitalize">
                    {account.provider}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {account.email}
                  </p>
                </div>
                {account.is_primary && (
                  <span className="bg-primary/10 text-primary rounded-full px-2 py-0.5 text-[10px] font-medium">
                    {t.accountSettings.primaryAccount}
                  </span>
                )}
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="size-8 text-muted-foreground hover:text-destructive"
                onClick={() =>
                  setUnlinkAccount({
                    provider: account.provider,
                    email: account.email,
                  })
                }
              >
                <TrashIcon className="size-3.5" />
              </Button>
            </div>
          ))}

          {(!profile?.linked_accounts ||
            profile.linked_accounts.length === 0) && (
            <div className="text-muted-foreground p-6 text-center">
              <Link2Icon className="mx-auto mb-2 size-5 opacity-40" />
              <p className="text-sm">
                {t.settings.account.linkedAccounts.notConnected}
              </p>
            </div>
          )}

          <div className="flex gap-2 p-4">
            <Button variant="outline" size="sm" className="flex-1 h-8 text-xs">
              <svg className="mr-1.5 size-3.5" viewBox="0 0 24 24">
                <path
                  fill="currentColor"
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                />
                <path
                  fill="currentColor"
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                />
              </svg>
              {t.accountSettings.linkGoogle}
            </Button>
            <Button variant="outline" size="sm" className="flex-1 h-8 text-xs">
              <svg className="mr-1.5 size-3.5" viewBox="0 0 24 24">
                <path
                  fill="currentColor"
                  d="M12 1C5.92 1 1 5.92 1 12c0 4.87 3.15 8.99 7.52 10.44.55.1.75-.24.75-.53v-1.86c-3.06.66-3.7-1.47-3.7-1.47-.5-1.27-1.22-1.61-1.22-1.61-.99-.68.08-.66.08-.66 1.1.08 1.68 1.13 1.68 1.13.97 1.67 2.55 1.19 3.17.91.1-.71.38-1.19.69-1.46-2.44-.28-5.01-1.22-5.01-5.44 0-1.2.43-2.19 1.13-2.96-.11-.28-.49-1.4.11-2.92 0 0 .92-.3 3.02 1.13a10.5 10.5 0 0 1 5.51 0c2.1-1.43 3.02-1.13 3.02-1.13.6 1.52.22 2.64.11 2.92.7.77 1.13 1.76 1.13 2.96 0 4.23-2.57 5.16-5.02 5.43.39.34.74 1.01.74 2.03v3.01c0 .29.2.64.75.53C19.85 20.99 23 16.87 23 12c0-6.08-4.92-11-11-11z"
                />
              </svg>
              {t.accountSettings.linkGithub}
            </Button>
          </div>
        </div>
      </section>

      {/* Privacy */}
      <section>
        <div className="mb-3">
          <h3 className="text-sm font-medium">
            {t.settings.account.privacy.title}
          </h3>
          <p className="text-muted-foreground text-xs mt-0.5">
            {t.settings.account.privacy.description}
          </p>
        </div>
        <div className="rounded-xl border bg-card divide-y">
          <div className="flex items-center justify-between px-5 py-4">
            <div className="space-y-0.5 pr-4">
              <Label className="text-sm">
                {t.settings.account.privacy.shareUsageData}
              </Label>
              <p className="text-muted-foreground text-xs">
                {t.settings.account.privacy.shareUsageDataDescription}
              </p>
            </div>
            <Switch
              checked={privacy?.privacy_mode || false}
              onCheckedChange={(checked) =>
                updatePrivacy.mutate({ privacy_mode: checked })
              }
            />
          </div>
          <div className="flex items-center justify-between px-5 py-4">
            <div className="space-y-0.5 pr-4">
              <Label className="text-sm">
                {t.settings.account.privacy.allowAnalytics}
              </Label>
              <p className="text-muted-foreground text-xs">
                {t.settings.account.privacy.allowAnalyticsDescription}
              </p>
            </div>
            <Switch
              checked={privacy?.data_collection_consent !== false}
              onCheckedChange={(checked) =>
                updatePrivacy.mutate({ data_collection_consent: checked })
              }
            />
          </div>
        </div>
      </section>

      {/* Danger Zone */}
      <section>
        <div className="mb-3">
          <h3 className="text-sm font-medium text-destructive">
            {t.settings.account.dangerZone.title}
          </h3>
          <p className="text-muted-foreground text-xs mt-0.5">
            {t.settings.account.dangerZone.description}
          </p>
        </div>
        <div className="rounded-xl border border-destructive/20 bg-destructive/5">
          <div className="flex items-center justify-between px-5 py-4">
            <div>
              <p className="text-sm font-medium">
                {t.settings.account.dangerZone.deleteAccount}
              </p>
              <p className="text-muted-foreground text-xs">
                {t.settings.account.dangerZone.deleteAccountDescription}
              </p>
            </div>
            <Button
              variant="destructive"
              size="sm"
              className="h-8 text-xs"
              onClick={() => setShowDeleteDialog(true)}
            >
              {t.settings.account.dangerZone.deleteAccount}
            </Button>
          </div>
        </div>
      </section>

      {/* Unlink Confirm Dialog */}
      <Dialog
        open={!!unlinkAccount}
        onOpenChange={() => setUnlinkAccount(null)}
      >
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle>{t.common.unlink}</DialogTitle>
            <DialogDescription>
              {t.accountSettings.unlinkConfirm}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setUnlinkAccount(null)}>
              {t.common.cancel}
            </Button>
            <Button variant="destructive" onClick={handleUnlink}>
              {t.common.confirm}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Account Dialog */}
      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent className="sm:max-w-[400px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangleIcon className="size-5" />
              {t.accountSettings.deleteAccountConfirm}
            </DialogTitle>
            <DialogDescription>
              {t.accountSettings.deleteAccountWarning}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-4">
            <Label htmlFor="delete-confirm" className="text-sm">
              {t.accountSettings.typeToConfirm}
            </Label>
            <Input
              id="delete-confirm"
              value={deleteConfirmText}
              onChange={(e) => setDeleteConfirmText(e.target.value)}
              placeholder="DELETE"
              className="h-9"
            />
          </div>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="outline"
              onClick={() => setShowDeleteDialog(false)}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={handleDeleteAccount}
              disabled={deleteConfirmText !== "DELETE"}
            >
              {t.accountSettings.confirmDelete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function OfficialCreditsCard() {
  const { t } = useI18n();
  const link = useMoliliLink();
  const refresh = useRefreshMoliliCredits();

  if (link.isLoading) {
    return (
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <Skeleton className="h-5 w-5 rounded" />
          <Skeleton className="h-5 w-24" />
        </div>
        <Skeleton className="h-20 w-full rounded-lg" />
      </div>
    );
  }

  if (!link.data) return null;

  const tokenInvalid = Boolean(link.data.token_invalid);
  const tokenInvalidReason = link.data.token_invalid_reason;

  const credits = link.data.credits ?? {};
  const remaining = credits.surplusCredits;
  const summary = credits.creditsSummary;
  const naive = Object.values(summary?.by_type ?? {}).reduce(
    (acc, b) => acc + (b?.remaining ?? 0),
    0,
  );
  const expired =
    typeof remaining === "number" ? Math.max(0, naive - remaining) : 0;

  const onRefresh = async () => {
    try {
      await refresh.mutateAsync();
      toast.success(t.accountSettings.creditsRefreshed);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t.accountSettings.refreshFailed,
      );
    }
  };

  const totalGranted = Object.values(summary?.by_type ?? {}).reduce(
    (acc, b) => acc + (b?.granted ?? 0),
    0,
  );

  return (
    <section>
      <div className="mb-3">
        <h3 className="text-sm font-medium flex items-center gap-2">
          <CoinsIcon className="size-4" />
          {t.accountSettings.creditsBalance}
        </h3>
      </div>
      <div className="rounded-xl border bg-card">
        {tokenInvalid && (
          <div className="flex items-start gap-2 border-b border-amber-200/60 bg-amber-50 px-5 py-3 text-xs text-amber-800 dark:border-amber-800/40 dark:bg-amber-950/30 dark:text-amber-200">
            <AlertTriangleIcon className="size-4 shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="font-medium">
                {t.accountSettings.moliliSessionExpired(
                  tokenInvalidReason ||
                    t.accountSettings.moliliSessionExpiredDefaultReason,
                )}
              </p>
              <p className="mt-0.5 opacity-80">
                {t.accountSettings.moliliSessionCacheHint}
              </p>
            </div>
          </div>
        )}
        <div className="p-5">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-baseline gap-2">
                <span
                  className={
                    "text-2xl font-semibold tabular-nums tracking-tight" +
                    (tokenInvalid ? " text-muted-foreground" : "")
                  }
                >
                  {formatCredits(remaining, t)}
                </span>
                {typeof remaining === "number" && remaining > 0 && (
                  <span className="text-sm text-muted-foreground">
                    {tokenInvalid
                      ? t.accountSettings.cachedSuffix
                      : t.accountSettings.available}
                  </span>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                {credits.plan ? credits.plan : t.accountSettings.moliliAccount}
                {credits.modelDisplayName
                  ? ` · ${credits.modelDisplayName}`
                  : ""}
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={onRefresh}
              disabled={refresh.isPending}
              className="size-8"
            >
              <RefreshCwIcon
                className={refresh.isPending ? "animate-spin size-4" : "size-4"}
              />
            </Button>
          </div>

          {summary?.by_type && Object.keys(summary.by_type).length > 0 && (
            <div className="mt-4 space-y-3">
              {Object.entries(summary.by_type)
                .filter(([, v]) => v.granted > 0)
                .map(([type, v]) => {
                  const percentage =
                    totalGranted > 0 ? (v.remaining / totalGranted) * 100 : 0;
                  return (
                    <div key={type} className="space-y-1">
                      <div className="flex items-center justify-between text-xs">
                        <span className="capitalize text-muted-foreground">
                          {type}
                        </span>
                        <span className="tabular-nums">
                          {v.remaining.toLocaleString()}
                          <span className="text-muted-foreground">
                            {" "}
                            / {v.granted.toLocaleString()}
                          </span>
                        </span>
                      </div>
                      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                        <div
                          className="h-full rounded-full bg-primary transition-all"
                          style={{ width: `${percentage}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              {expired > 0 && (
                <div className="flex items-center justify-between pt-2 border-t text-xs">
                  <span className="text-muted-foreground">
                    {t.accountSettings.expiredOrFrozen}
                  </span>
                  <span className="tabular-nums text-orange-500">
                    −{expired.toLocaleString()}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
        <Separator />
        <div className="px-5 py-3">
          <p className="text-xs text-muted-foreground">
            {t.accountSettings.creditsDescription}
          </p>
        </div>
      </div>
    </section>
  );
}
