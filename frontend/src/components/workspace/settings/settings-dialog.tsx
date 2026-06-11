
import {
  ActivityIcon,
  BellIcon,
  InfoIcon,
  BrainIcon,
  CpuIcon,
  LogOutIcon,
  PaletteIcon,
  ShieldIcon,
  UserIcon,
  ZapIcon,
  CreditCardIcon,
  ServerIcon,
  SettingsIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Skeleton } from "@/components/ui/skeleton";
import { Suspense, lazy } from "react";

// Lazy load settings pages. Each ``import()`` is kept as a reusable factory
// so we can preload *all* chunks the moment the dialog opens — see
// ``preloadSettingsPages`` below. Without preloading, switching to a tab
// that hasn't been visited in this session triggered a fresh chunk
// download + Suspense fallback, which users correctly perceived as "every
// tab reloads".
const importAbout = () => import("@/components/workspace/settings/about-settings-page");
const importAccount = () => import("@/components/workspace/settings/account-settings-page");
const importAppearance = () => import("@/components/workspace/settings/appearance-settings-page");
const importMemory = () => import("@/components/workspace/settings/memory-settings-page");
const importNotification = () => import("@/components/workspace/settings/notification-settings-page");
const importModel = () => import("@/components/workspace/settings/model-settings-page");
const importSubscription = () => import("@/components/workspace/settings/subscription-settings-page");
const importPrivacy = () => import("@/components/workspace/settings/privacy-settings-page");
const importAutomation = () => import("@/components/workspace/settings/automation-settings-page");
const importMcp = () =>
  import("@/components/workspace/settings/mcp-settings-page").then((mod) => ({
    default: mod.McpSettingsPage,
  }));

const AboutSettingsPage = lazy(importAbout);
const AccountSettingsPage = lazy(importAccount);
const AppearanceSettingsPage = lazy(importAppearance);
const MemorySettingsPage = lazy(importMemory);
const NotificationSettingsPage = lazy(importNotification);
const ModelSettingsPage = lazy(importModel);
const SubscriptionSettingsPage = lazy(importSubscription);
const PrivacySettingsPage = lazy(importPrivacy);
const AutomationSettingsPage = lazy(importAutomation);
const McpSettingsPage = lazy(importMcp);

// Run every chunk import in parallel the first time the dialog opens.
// Browsers dedupe the ``import()`` calls against cache, so repeated opens
// are no-ops. We deliberately swallow errors — a failed preload doesn't
// break anything; the per-tab Suspense fallback will still catch it on
// actual navigation.
let preloadStarted = false;
function preloadSettingsPages(): void {
  if (preloadStarted) return;
  preloadStarted = true;
  [
    importAbout, importAccount, importAppearance,
    importMemory, importNotification, importModel, importSubscription,
    importPrivacy, importAutomation, importMcp,
  ].forEach((fn) => { fn().catch((e) => { swallow(e); }); });
}

import { swallow } from "@/core/utils/log";
import { useI18n } from "@/core/i18n/hooks";
import { useAuth } from "@/providers/AuthProvider";
import { cn } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { moliliApi } from "@/core/molili/api";

type SettingsSection =
  | "account"
  | "subscription"
  | "appearance"
  | "models"
  | "memory"
  | "automation"
  | "mcp"
  | "privacy"
  | "notification"
  | "observability"
  | "about";

type SettingsDialogProps = React.ComponentProps<typeof Dialog> & {
  defaultSection?: SettingsSection;
};

// Persist user-chosen dialog size across sessions so we don't reset on every
// open. localStorage is fine — the preference is per-browser, non-sensitive.
const DIALOG_SIZE_KEY = "octopus_settings_dialog_size";
const MIN_W = 560;
const MIN_H = 360;

function readSavedSize(): { w: number; h: number } | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(DIALOG_SIZE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { w?: unknown; h?: unknown };
    if (typeof parsed.w === "number" && typeof parsed.h === "number") {
      return { w: parsed.w, h: parsed.h };
    }
  } catch (e) { swallow(e); }
  return null;
}

function isPlaceholderUsername(username?: string | null): boolean {
  const value = username?.trim().toLowerCase();
  return !value || value === "anonymous" || value === "__anonymous__";
}

function getAccountDisplayName(user: {
  mobile?: string;
  email?: string;
  username?: string;
  actor_id?: string;
} | null): string | null {
  if (!user) return null;
  return (
    user.mobile ||
    user.email ||
    (!isPlaceholderUsername(user.username) ? user.username : "") ||
    user.actor_id ||
    null
  );
}

export function SettingsDialog(props: SettingsDialogProps) {
  const { defaultSection = "appearance", ...dialogProps } = props;
  const { t } = useI18n();
  const navigate = useNavigate();
  const { user, logout, authStatus, isLoading, isGuest } = useAuth();
  const accountName = getAccountDisplayName(user);
  const queryClient = useQueryClient();
  const [activeSection, setActiveSection] =
    useState<SettingsSection>(defaultSection);

  // Null = "let the Tailwind default sizing apply". Once the user drags the
  // corner handle we switch to an inline width/height so DialogContent grows
  // symmetrically around its translate-[-50%,-50%] center anchor.
  const [size, setSize] = useState<{ w: number; h: number } | null>(() =>
    readSavedSize(),
  );
  const resizeStartRef = useRef<{
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);

  const onResizeStart = (e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    const content = (e.currentTarget as HTMLElement).closest(
      '[data-slot="dialog-content"]',
    ) as HTMLElement | null;
    if (!content) return;
    const rect = content.getBoundingClientRect();
    resizeStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      w: rect.width,
      h: rect.height,
    };
    const onMove = (ev: MouseEvent) => {
      const start = resizeStartRef.current;
      if (!start) return;
      const dx = ev.clientX - start.x;
      const dy = ev.clientY - start.y;
      // Dialog is center-anchored, so corner drag of dx px moves the right
      // edge by dx — we need to grow width by 2*dx to keep the corner under
      // the cursor.
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const nextW = Math.max(MIN_W, Math.min(vw - 32, start.w + dx * 2));
      const nextH = Math.max(MIN_H, Math.min(vh - 32, start.h + dy * 2));
      setSize({ w: nextW, h: nextH });
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      resizeStartRef.current = null;
      // Persist the last value we pushed into state. We read via a setter
      // callback to avoid a stale closure over `size`.
      setSize((latest) => {
        if (latest) {
          try {
            window.localStorage.setItem(
              DIALOG_SIZE_KEY,
              JSON.stringify(latest),
            );
          } catch (e) { swallow(e, "storage"); }
        }
        return latest;
      });
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  useEffect(() => {
    // When opening the dialog, ensure the active section follows the caller's intent.
    // This allows triggers like "About" to open the dialog directly on that page.
    if (dialogProps.open) {
      setActiveSection(defaultSection);
      // Kick off parallel preload of every tab's JS chunk so subsequent
      // tab switches are instant instead of triggering a fresh chunk
      // download + Suspense fallback each time.
      preloadSettingsPages();

      // The generic /api/account/* routes are compatibility stubs in local
      // no-account mode. Only prefetch the real Molili bridge; individual
      // account tabs can fetch their own optional data when opened.
      queryClient.prefetchQuery({
        queryKey: ["account", "molili"],
        queryFn: () => moliliApi.get().catch(() => null),
        staleTime: 30_000,
      });
    }
  }, [defaultSection, dialogProps.open, queryClient]);

  const handleLogout = async () => {
    try {
      await logout();
      toast.success(t.auth.logoutSuccess);
      dialogProps.onOpenChange?.(false);
      navigate("/");
    } catch {
      toast.error(t.auth.logoutFailed);
    }
  };

  const sections = useMemo(
    () => {
      // Stable order across login states · account/subscription
      // are greyed out for guests instead of being reordered, so
      // users don't lose muscle memory of where each tab lives.
      type Section = {
        id: SettingsSection;
        label: string;
        icon: React.ComponentType<{ className?: string }>;
        disabled?: boolean;
        disabledReason?: string;
      };

      const all: Section[] = [
        {
          id: "account",
          label: t.settings.sections.account,
          icon: SettingsIcon,
          disabled: isGuest,
          disabledReason: t.auth.guestMode.title,
        },
        {
          id: "subscription",
          label: t.settings.sections.subscription,
          icon: CreditCardIcon,
          disabled: isGuest,
          disabledReason: t.auth.guestMode.title,
        },
        {
          id: "appearance",
          label: t.settings.sections.appearance,
          icon: PaletteIcon,
        },
        {
          id: "models",
          label: t.modelSettings.title,
          icon: CpuIcon,
        },
        {
          id: "notification",
          label: t.settings.sections.notification,
          icon: BellIcon,
        },
        {
          id: "memory",
          label: t.settings.sections.memory,
          icon: BrainIcon,
        },
        { id: "automation", label: t.settings.sections.automation, icon: ZapIcon },
        { id: "mcp", label: t.mcpSettings.title, icon: ServerIcon },
        {
          id: "privacy",
          label: t.settings.sections.privacy,
          icon: ShieldIcon,
        },
        { id: "observability", label: t.settings.sections.observability, icon: ActivityIcon },
        { id: "about", label: t.settings.sections.about, icon: InfoIcon },
      ];

      return all;
    },
    [
      isGuest,
      t.auth.guestMode.title,
      t.settings.sections.account,
      t.settings.sections.subscription,
      t.settings.sections.appearance,
      t.modelSettings.title,
      t.settings.sections.memory,
      t.settings.sections.automation,
      t.mcpSettings.title,
      t.settings.sections.notification,
      t.settings.sections.about,
    ],
  );
  return (
    <Dialog
      {...dialogProps}
      onOpenChange={(open) => props.onOpenChange?.(open)}
    >
      <DialogContent
        className="flex h-[75vh] max-h-[calc(100vh-2rem)] flex-col sm:max-w-5xl md:max-w-6xl"
        style={
          size
            ? {
                width: size.w,
                height: size.h,
                maxWidth: "calc(100vw - 2rem)",
                maxHeight: "calc(100vh - 2rem)",
              }
            : undefined
        }
        aria-describedby={undefined}
      >
        <DialogHeader className="gap-0">
          {/* Inline the title and description so the header is one row instead
              of two. The description is redundant context once the dialog is
              open — we keep a muted copy for screen readers / first-time users. */}
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <DialogTitle className="leading-none">{t.settings.title}</DialogTitle>
            <p className="text-muted-foreground text-xs leading-none">
              {t.settings.description}
            </p>
          </div>
          {!isLoading && (user || isGuest || authStatus?.enabled) ? (
            <div className="mt-2 flex items-center justify-between rounded-lg border bg-muted/30 px-2.5 py-1.5">
              <div className="flex min-w-0 items-center gap-2.5">
                <div className="relative flex size-7 items-center justify-center rounded-lg border border-border/70 bg-background text-muted-foreground shadow-sm">
                  <UserIcon className="size-3.5" />
                  <span className="absolute -right-0.5 -bottom-0.5 size-2 rounded-full border border-background bg-emerald-500" />
                </div>
                <div className="min-w-0 leading-tight">
                  <p className="text-sm font-medium">
                    {accountName ?? t.auth.notLoggedIn}
                  </p>
                  <p className="text-muted-foreground truncate text-[11px]">
                    {isGuest ? t.auth.guestMode.title : (user?.email && user.email !== accountName ? user.email : t.auth.currentAccount)}
                  </p>
                </div>
              </div>
              {user && !isGuest ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 px-2.5 text-xs"
                  onClick={handleLogout}
                >
                  <LogOutIcon className="mr-1 size-3.5" />
                  {t.auth.logout}
                </Button>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 px-2.5 text-xs"
                  onClick={() => {
                    dialogProps.onOpenChange?.(false);
                    navigate("/login");
                  }}
                >
                  <LogOutIcon className="mr-1 size-3.5" />
                  {t.auth.loginAccount}
                </Button>
              )}
            </div>
          ) : null}
        </DialogHeader>
        <div className="grid min-h-0 flex-1 gap-3 md:grid-cols-[220px_1fr]">
          <nav className="bg-sidebar min-h-0 overflow-y-auto rounded-lg border p-2">
            <ul className="space-y-1 pr-1">
              {sections.map(({ id, label, icon: Icon, disabled, disabledReason }) => {
                const active = activeSection === id;
                return (
                  <li key={id}>
                    <button
                      type="button"
                      onClick={() => {
                        if (disabled) return;
                        setActiveSection(id as SettingsSection);
                      }}
                      disabled={disabled}
                      title={disabled ? disabledReason : undefined}
                      aria-disabled={disabled || undefined}
                      className={cn(
                        // Match sidebar NavRow: opacity + leading 2px
                        // accent bar instead of a full primary fill.
                        "group/sec relative flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-[opacity,background-color] duration-150",
                        disabled
                          ? "cursor-not-allowed opacity-40"
                          : "opacity-75 hover:opacity-100 hover:bg-muted/50",
                        active &&
                          "opacity-100 bg-[color:color-mix(in_oklch,var(--sidebar-accent)_70%,transparent)] before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-[2px] before:rounded-r before:bg-primary/70",
                      )}
                    >
                      <Icon className="size-4" />
                      <span className="flex-1 truncate text-left">{label}</span>
                      {disabled && (
                        <span className="rounded border border-border/60 px-1 py-0.5 text-[9px] font-medium leading-none text-muted-foreground">
                          {t.common.guest}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
          <ScrollArea className="h-full min-h-0 rounded-lg border">
            <div className="space-y-8 p-6">
              {/* Each tab gets its own Suspense boundary so switching
                  to an uncached tab doesn't blank out the currently
                  mounted one. Combined with preloadSettingsPages() this
                  effectively removes the "every tab reloads" flicker
                  users were seeing. */}
              {activeSection === "account" && (
                <Suspense fallback={<SettingsPageSkeleton />}><AccountSettingsPage /></Suspense>
              )}
              {activeSection === "subscription" && (
                <Suspense fallback={<SettingsPageSkeleton />}><SubscriptionSettingsPage /></Suspense>
              )}
              {activeSection === "appearance" && (
                <Suspense fallback={<SettingsPageSkeleton />}><AppearanceSettingsPage /></Suspense>
              )}
              {activeSection === "models" && (
                <Suspense fallback={<SettingsPageSkeleton />}><ModelSettingsPage /></Suspense>
              )}
              {activeSection === "memory" && (
                <Suspense fallback={<SettingsPageSkeleton />}><MemorySettingsPage /></Suspense>
              )}
              {activeSection === "automation" && (
                <Suspense fallback={<SettingsPageSkeleton />}><AutomationSettingsPage /></Suspense>
              )}
              {activeSection === "mcp" && (
                <Suspense fallback={<SettingsPageSkeleton />}><McpSettingsPage /></Suspense>
              )}
              {activeSection === "privacy" && (
                <Suspense fallback={<SettingsPageSkeleton />}><PrivacySettingsPage /></Suspense>
              )}
              {activeSection === "notification" && (
                <Suspense fallback={<SettingsPageSkeleton />}><NotificationSettingsPage /></Suspense>
              )}
              {activeSection === "observability" && (
                <div className="flex flex-col items-center gap-4 py-12 text-center">
                  <ActivityIcon className="size-10 text-muted-foreground/50" />
                  <p className="text-sm text-muted-foreground">{t.settings.sections.observability}</p>
                  <Button onClick={() => { dialogProps.onOpenChange?.(false); navigate("/workspace/observability"); }}>
                    {t.settings.sections.observability}
                  </Button>
                </div>
              )}
              {activeSection === "about" && (
                <Suspense fallback={<SettingsPageSkeleton />}><AboutSettingsPage /></Suspense>
              )}
            </div>
          </ScrollArea>
        </div>
        {/* Resize handle — sits in the bottom-right corner. We keep the
            clickable area a bit bigger than the visual glyph so it's easy
            to grab without overlapping close-button or scrollbars. */}
        <div
          onMouseDown={onResizeStart}
          // Keyboard fallback: arrow keys grow/shrink the dialog so
          // keyboard-only and screen-reader users can resize too.
          // Shift = 4× step. Home/End snaps to min/default.
          onKeyDown={(e) => {
            const step = e.shiftKey ? 64 : 16;
            const current = size ?? {
              w: MIN_W + 200,
              h: MIN_H + 200,
            };
            const vw = window.innerWidth;
            const vh = window.innerHeight;
            const maxW = vw - 32;
            const maxH = vh - 32;
            let nextW = current.w;
            let nextH = current.h;
            switch (e.key) {
              case "ArrowRight":
              case "ArrowDown":
                nextW = Math.min(maxW, current.w + step);
                nextH = Math.min(maxH, current.h + step);
                break;
              case "ArrowLeft":
              case "ArrowUp":
                nextW = Math.max(MIN_W, current.w - step);
                nextH = Math.max(MIN_H, current.h - step);
                break;
              case "Home":
                nextW = MIN_W;
                nextH = MIN_H;
                break;
              case "End":
                nextW = Math.min(maxW, 1280);
                nextH = Math.min(maxH, 800);
                break;
              default:
                return;
            }
            e.preventDefault();
            const next = { w: nextW, h: nextH };
            setSize(next);
            try {
              window.localStorage.setItem(
                DIALOG_SIZE_KEY,
                JSON.stringify(next),
              );
            } catch (err) { swallow(err, "storage"); }
          }}
          role="separator"
          aria-orientation="vertical"
          aria-label={t.settingsDialog.dragToResize}
          aria-valuenow={size ? Math.round(size.w) : undefined}
          aria-valuemin={MIN_W}
          aria-valuemax={typeof window !== "undefined" ? window.innerWidth - 32 : undefined}
          title={t.settingsDialog.dragToResize}
          tabIndex={0}
          className="absolute bottom-0 right-0 z-50 flex size-5 cursor-nwse-resize items-end justify-end rounded-sm p-1 text-muted-foreground/40 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60"
        >
          <svg viewBox="0 0 10 10" className="size-2.5" aria-hidden="true">
            <path
              d="M0 10 L10 0 M4 10 L10 4 M8 10 L10 8"
              stroke="currentColor"
              strokeWidth="1.2"
              strokeLinecap="round"
              fill="none"
            />
          </svg>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// Skeleton loader for settings pages
function SettingsPageSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-4 w-96" />
      <div className="space-y-4">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    </div>
  );
}
