import { useState } from "react";
import {
  Loader2Icon,
  SparklesIcon,
  TrendingUpIcon,
  CalendarIcon,
  UserIcon,
  CoinsIcon,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useSubscription,
  useCancelSubscription,
  useProfile,
} from "@/core/account";
import { swallow } from "@/core/utils/log";
import { formatDate } from "@/core/utils/datetime";
import { useI18n } from "@/core/i18n/hooks";
import {
  useCreatePaymentLink,
  useMoliliGoods,
  useMoliliLink,
  type MoliliGoods,
} from "@/core/molili";
import { PayOrderDialog } from "@/components/workspace/pay-order-dialog";

export default function SubscriptionSettingsPage() {
  const { t } = useI18n();
  const { data: subscription, isLoading: subscriptionLoading } =
    useSubscription();
  const cancelSubscription = useCancelSubscription();

  const isInitialLoading = subscriptionLoading && !subscription;

  // Current-plan label is sourced from the local subscription record;
  // we no longer cross-reference octopus's `plans` JSON since the
  // purchase flow itself is now driven by the official account service.
  const effectiveTier = subscription?.tier ?? "free";
  const currentPlan = subscription
    ? {
        name: effectiveTier
          ? String(effectiveTier).toUpperCase()
          : t.settings.subscription.free,
      }
    : { name: t.settings.subscription.free };

  if (isInitialLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-96" />
        <div className="space-y-4">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Current Plan Card */}
      <div className="rounded-xl border bg-card p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div
              className={cn(
                "flex size-10 items-center justify-center rounded-lg",
                subscription?.tier && ["pro", "max"].includes(subscription.tier)
                  ? "bg-gradient-to-br from-violet-500 to-blue-500 text-white"
                  : "bg-muted text-muted-foreground",
              )}
            >
              <SparklesIcon className="size-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold">
                  {currentPlan?.name || t.settings.subscription.free}
                </span>
                <Badge
                  variant={effectiveTier === "free" ? "secondary" : "default"}
                  className="text-[10px]"
                >
                  {effectiveTier.toUpperCase()}
                </Badge>
              </div>
              <p className="text-muted-foreground text-xs mt-0.5">
                {effectiveTier === "free"
                  ? t.settings.subscription.freeTierDesc
                  : t.settings.subscription.paidTierDesc}
              </p>
            </div>
          </div>

          {effectiveTier !== "free" ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => cancelSubscription.mutate()}
              disabled={cancelSubscription.isPending}
              className="h-8 text-xs"
            >
              {cancelSubscription.isPending && (
                <Loader2Icon className="mr-1 size-3 animate-spin" />
              )}
              {t.settings.subscription.cancel}
            </Button>
          ) : (
            <Button
              size="sm"
              variant="default"
              className="h-8 text-xs"
              onClick={() => {
                const el = document.querySelector(
                  '[data-slot="dialog-content"] [data-subscription-pricing]',
                );
                el?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
            >
              <TrendingUpIcon className="mr-1 size-3.5" />
              {t.subscriptionSettings.upgradeNow}
            </Button>
          )}
        </div>

        {subscription?.expires_at && (
          <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
            <CalendarIcon className="size-3.5" />
            <span>
              {t.settings.subscription.expiresOn(
                formatDate(subscription.expires_at),
              )}
            </span>
            {subscription?.auto_renew && (
              <Badge variant="outline" className="text-[10px] ml-2">
                {t.settings.subscription.autoRenewal}
              </Badge>
            )}
          </div>
        )}
      </div>

      {/* Pricing plans sourced live from the account service. */}
      <OfficialPricingSection />
    </div>
  );
}

/* Implementation note. */
function formatCreditsSummary(
  creditsInfo: string | undefined,
  t: ReturnType<typeof useI18n>["t"],
): string {
  if (!creditsInfo) return "";
  try {
    const parsed = JSON.parse(creditsInfo) as Record<string, unknown>;
    const total = typeof parsed.total === "number" ? parsed.total : undefined;
    if (typeof total === "number") {
      return t.subscriptionSettings.totalCredits(total.toLocaleString());
    }
  } catch (e) {
    swallow(e);
  }
  return creditsInfo;
}

function goodsUnit(
  goods: MoliliGoods,
  t: ReturnType<typeof useI18n>["t"],
): string {
  if (goods.type === 1) return t.payOrder.perMonth;
  if (goods.type === 2) return t.payOrder.perYear;
  return t.payOrder.oneTime;
}

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

interface PayState {
  open: boolean;
  paymentLink: string | null;
  orderNo: string | null;
  goodsName?: string;
  amountYuan?: string;
}

function OfficialPricingSection() {
  const { t } = useI18n();
  const link = useMoliliLink();
  const linked = Boolean(link.data);
  const goodsQuery = useMoliliGoods(linked);
  const createLink = useCreatePaymentLink();
  const { data: profile } = useProfile();
  const isLoggedIn = Boolean(profile?.username);
  const [pay, setPay] = useState<PayState>({
    open: false,
    paymentLink: null,
    orderNo: null,
  });
  const [pendingId, setPendingId] = useState<number | null>(null);

  const onBuy = async (g: MoliliGoods) => {
    setPendingId(g.id);
    try {
      const resp = await createLink.mutateAsync(g.id);
      const data = resp?.data;
      if (!data?.paymentLink || !data?.orderNo) {
        const msg = resp?.errMessage || resp?.errCode || t.payOrder.goodsFailed;
        toast.error(msg);
        return;
      }
      setPay({
        open: true,
        paymentLink: data.paymentLink,
        orderNo: data.orderNo,
        goodsName: g.name,
        amountYuan: (g.price / 100).toFixed(g.price % 100 === 0 ? 0 : 2),
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.payOrder.goodsFailed);
    } finally {
      setPendingId(null);
    }
  };

  // Not linked yet: show login status and credits instead of the price grid.
  if (!linked && !link.isLoading) {
    const credits = link.data?.credits;
    const surplusCredits = credits?.surplusCredits;

    return (
      <div
        className="rounded-xl border border-dashed bg-muted/30 p-8 text-center space-y-4"
        data-subscription-pricing
      >
        {isLoggedIn ? (
          <>
            <div className="flex items-center justify-center gap-2 text-sm">
              <UserIcon className="size-4 text-muted-foreground" />
              <span className="font-medium">
                {profile?.display_name || profile?.username}
              </span>
              <Badge variant="secondary" className="text-[10px]">
                {t.auth.currentAccount}
              </Badge>
            </div>
            {typeof surplusCredits === "number" && (
              <div className="flex items-center justify-center gap-2 pt-3 border-t">
                <CoinsIcon className="size-4 text-amber-500" />
                <span className="text-lg font-semibold tabular-nums">
                  {formatCredits(surplusCredits, t)}
                </span>
                <span className="text-xs text-muted-foreground">
                  {t.accountSettings.available}
                </span>
              </div>
            )}
          </>
        ) : (
          <div className="text-sm text-muted-foreground">
            {t.auth.notLoggedIn}
          </div>
        )}
      </div>
    );
  }

  if (goodsQuery.isLoading || link.isLoading) {
    return (
      <div className="space-y-4" data-subscription-pricing>
        <div className="text-center">
          <h2 className="text-lg font-semibold">
            {t.subscriptionSettings.upgradeTitle}
          </h2>
          <p className="text-muted-foreground mt-1 text-sm">
            {t.payOrder.loadingGoods}
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-56 w-full rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (goodsQuery.isError || goodsQuery.data?.length === 0) {
    return (
      <div
        className="rounded-xl border border-dashed bg-muted/30 p-8 text-center"
        data-subscription-pricing
      >
        <p className="text-sm text-muted-foreground">
          {t.payOrder.goodsFailed}
        </p>
      </div>
    );
  }

  const goods = (goodsQuery.data ?? []).slice().sort((a, b) => {
    // Recommended first, then by sort order, then by price ascending.
    const ar = a.isRecommend === 1 ? 1 : 0;
    const br = b.isRecommend === 1 ? 1 : 0;
    if (ar !== br) return br - ar;
    const as = a.sort ?? 9999;
    const bs = b.sort ?? 9999;
    if (as !== bs) return as - bs;
    return a.price - b.price;
  });

  return (
    <div className="space-y-6" data-subscription-pricing>
      <div className="text-center">
        <h2 className="text-lg font-semibold">
          {t.subscriptionSettings.upgradeTitle}
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">
          {t.subscriptionSettings.upgradeDesc}
        </p>
      </div>

      <div
        className={cn(
          "grid gap-4",
          goods.length >= 3 ? "md:grid-cols-3" : "md:grid-cols-2",
        )}
      >
        {goods.map((g) => {
          const isRecommended = g.isRecommend === 1;
          const isPending = pendingId === g.id;
          const yuan = (g.price / 100).toFixed(g.price % 100 === 0 ? 0 : 2);
          const originalYuan =
            g.originalPrice && g.originalPrice > g.price
              ? (g.originalPrice / 100).toFixed(
                  g.originalPrice % 100 === 0 ? 0 : 2,
                )
              : null;
          return (
            <div
              key={g.id}
              className={cn(
                "relative flex flex-col rounded-xl border p-5 transition-all",
                isRecommended
                  ? "border-violet-300/60 bg-gradient-to-b from-violet-50/50 to-white shadow-md dark:from-violet-950/20 dark:to-transparent dark:border-violet-700/40"
                  : "bg-card border-border/60 hover:border-border hover:shadow-sm",
              )}
            >
              {isRecommended && (
                <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 inline-flex items-center gap-1 rounded-full bg-gradient-to-r from-violet-500 to-violet-600 px-2.5 py-0.5 text-[10px] font-medium text-white shadow-sm">
                  🔥 {t.payOrder.recommended}
                </span>
              )}

              <h3 className="text-sm font-bold text-center">{g.name}</h3>

              <div className="mt-3 text-center">
                <span className="text-2xl font-bold tracking-tight">
                  ¥{yuan}
                </span>
                <span className="text-muted-foreground text-xs">
                  /{goodsUnit(g, t)}
                </span>
              </div>
              {originalYuan && (
                <p className="text-muted-foreground text-[11px] text-center mt-0.5 line-through">
                  ¥{originalYuan}
                </p>
              )}
              {formatCreditsSummary(g.creditsInfo, t) && (
                <p className="text-muted-foreground text-xs text-center mt-1">
                  {formatCreditsSummary(g.creditsInfo, t)}
                </p>
              )}

              <Button
                className={cn(
                  "mt-4 h-9 w-full rounded-lg text-xs font-medium",
                  isRecommended
                    ? "bg-violet-600 text-white hover:bg-violet-700"
                    : "bg-foreground text-background hover:bg-foreground/85",
                )}
                disabled={isPending}
                onClick={() => onBuy(g)}
              >
                {isPending && (
                  <Loader2Icon className="mr-1 size-3 animate-spin" />
                )}
                {t.payOrder.subscribeNow}
              </Button>
            </div>
          );
        })}
      </div>

      <p className="text-muted-foreground text-center text-xs">
        {t.subscriptionSettings.contactUs}
        <span className="text-foreground font-medium">
          support@octopus.local
        </span>
        ，{t.subscriptionSettings.invoiceHint}
      </p>

      <PayOrderDialog
        open={pay.open}
        onOpenChange={(open) => setPay((p) => ({ ...p, open }))}
        paymentLink={pay.paymentLink}
        orderNo={pay.orderNo}
        goodsName={pay.goodsName}
        amountYuan={pay.amountYuan}
      />
    </div>
  );
}
