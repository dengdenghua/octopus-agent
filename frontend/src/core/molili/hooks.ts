/** React Query hooks for the Molili bridge. */
import { swallow } from "@/core/utils/log";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { useAuth } from "@/providers/AuthProvider";

import {
  MoliliApiError,
  extractGoods,
  moliliApi,
  type MoliliDailyClaimInfo,
  type MoliliDailyClaimResult,
  type MoliliGoods,
  type MoliliLink,
  type MoliliOrderConfirmResponse,
  type MoliliOrderResponse,
  type MoliliPaymentLinkResponse,
} from "./api";

const moliliKey = ["account", "molili"] as const;
const dailyClaimKey = ["account", "molili", "daily-claim"] as const;
const goodsKey = ["account", "molili", "goods"] as const;

function moliliLinkKey(userId: string | null) {
  return [...moliliKey, userId ?? "anonymous"] as const;
}

function normalizeCredits(link: MoliliLink): MoliliLink {
  const raw = link.credits?.surplusCredits as unknown;
  if (typeof raw === "number") return link;
  if (typeof raw !== "string") return link;

  const parsed = Number(raw.replace(/,/g, ""));
  if (!Number.isFinite(parsed)) return link;
  return {
    ...link,
    credits: {
      ...link.credits,
      surplusCredits: parsed,
    },
  };
}

/**
 * Read the cached Molili link. We poll cheaply (every 60s) so the
 * credits badge stays roughly fresh without hammering Molili.
 *
 * - 404 (no link) is treated as "user has not connected Molili" — the
 *   query data resolves to ``null`` rather than throwing, so callers can
 *   render an empty / connect prompt instead of an error toast.
 */
export function useMoliliLink() {
  const { user, isGuest } = useAuth();
  const qc = useQueryClient();

  // Invalidate the cached query the moment the logged-in user changes
  // — otherwise SMS login would leave the guest-era `null` result in
  // the cache for up to 60s, so the sidebar credits line stayed blank
  // right after successful login.
  const userId = user?.user_id ?? user?.actor_id ?? null;
  useEffect(() => {
    void qc.invalidateQueries({ queryKey: moliliKey });
  }, [userId, isGuest, qc]);

  return useQuery<MoliliLink | null>({
    queryKey: moliliLinkKey(userId),
    queryFn: async () => {
      const fallbackCredits = user?.molili_credits ?? null;
      try {
        const link = await moliliApi.get();
        // /api/account/molili returns the cached record — right after
        // SMS login it still has `credits: {}` because the upstream
        // userInfo call is deferred. Force a refresh so the sidebar
        // shows the real surplusCredits on first visit instead of "—".
        if (link && typeof link.credits?.surplusCredits !== "number") {
          try {
            return normalizeCredits(await moliliApi.refresh());
          } catch (e) {
            swallow(e);
            // Refresh failure (e.g. upstream hiccup) — return the
            // empty-credits record rather than erroring the query.
            return normalizeCredits(
              fallbackCredits ? { ...link, credits: fallbackCredits } : link,
            );
          }
        }
        return normalizeCredits(link);
      } catch (err) {
        swallow(err);
        // 404 = no link; 503 = bridge disabled. Both render as "no
        // credits to show" rather than a noisy error toast.
        if (
          err instanceof MoliliApiError &&
          (err.status === 404 || err.status === 503)
        ) {
          if (fallbackCredits) {
            return normalizeCredits({
              molili_user_id: String(user?.actor_id ?? user?.user_id ?? ""),
              mobile: user?.mobile ?? null,
              linked_at: Date.now() / 1000,
              last_synced_at: null,
              credits: fallbackCredits,
            });
          }
          return null;
        }
        throw err;
      }
    },
    enabled: !isGuest,
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
}

/** Manual force-refresh — fires both userInfo + credits page on the backend. */
export function useRefreshMoliliCredits() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => moliliApi.refresh(),
    onSuccess: (data) => {
      qc.setQueriesData({ queryKey: moliliKey }, data);
    },
  });
}

/**
 * Today's daily-claim status from Molili. Only enabled when the user
 * actually has a Molili link (otherwise we'd 404 every mount).
 */
export function useDailyClaimInfo(enabled: boolean = true) {
  return useQuery<MoliliDailyClaimInfo | null>({
    queryKey: dailyClaimKey,
    enabled,
    queryFn: async () => {
      try {
        return await moliliApi.dailyClaim.info();
      } catch (err) {
        swallow(err);
        // 404 → no link; 503 → bridge disabled. Both resolve to null so
        // the caller renders nothing rather than an error toast.
        if (
          err instanceof MoliliApiError &&
          (err.status === 404 || err.status === 503)
        ) {
          return null;
        }
        throw err;
      }
    },
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

/**
 * Claim today's daily credits. ``draw: true`` spins for the randomized
 * amount up to the daily max; ``draw: false`` takes the fixed amount.
 * On success both the daily-claim info and the main credits snapshot
 * are invalidated so the balance badge updates.
 */
export function useClaimDailyCredits() {
  const qc = useQueryClient();
  return useMutation<MoliliDailyClaimResult, Error, boolean>({
    mutationFn: (draw: boolean) => moliliApi.dailyClaim.claim(draw),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: dailyClaimKey });
      qc.invalidateQueries({ queryKey: moliliKey });
    },
  });
}

/**
 * Fetch the Molili goods catalog. Only enabled when the user is
 * actually linked to Molili — otherwise we'd 404 every mount and
 * pollute query devtools with errors for non-linked users.
 */
export function useMoliliGoods(enabled: boolean = true) {
  return useQuery<MoliliGoods[]>({
    queryKey: goodsKey,
    enabled,
    queryFn: async () => {
      try {
        return extractGoods(await moliliApi.goods.detail());
      } catch (err) {
        swallow(err);
        if (
          err instanceof MoliliApiError &&
          (err.status === 404 || err.status === 503)
        ) {
          return [];
        }
        throw err;
      }
    },
    // Catalog changes rarely; cache aggressively.
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
  });
}

/**
 * Kick off a WeChat Pay order for a given goodsId. The response
 * contains the paymentLink (used as the QR payload) and the orderNo
 * the UI polls to detect payment completion.
 */
export function useCreatePaymentLink() {
  return useMutation<MoliliPaymentLinkResponse, Error, number>({
    mutationFn: (goodsId: number) => moliliApi.orders.createPaymentLink(goodsId),
  });
}

/**
 * Manual "I've completed payment" confirmation — called from the pay
 * dialog when the user clicks the finalize button. Invalidates the
 * credits query on successful paid state so the sidebar badge reflects
 * the new balance without an explicit refresh click.
 */
export function useConfirmOrder() {
  const qc = useQueryClient();
  return useMutation<MoliliOrderConfirmResponse, Error, string>({
    mutationFn: (orderNo: string) => moliliApi.orders.confirm(orderNo),
    onSuccess: (data) => {
      if (data.paid) {
        qc.invalidateQueries({ queryKey: moliliKey });
      }
    },
  });
}

/**
 * Look up a single order (e.g. to recover state on remount). Not used
 * for polling — the dialog drives polling manually via ``useConfirmOrder``
 * on a timer to keep the UX visible + cancellable. Kept here because
 * some callers may want to check state without triggering a refresh.
 */
export function useFindOrder(orderNo: string | null) {
  return useQuery<MoliliOrderResponse>({
    queryKey: [...goodsKey, "order", orderNo],
    enabled: Boolean(orderNo),
    queryFn: () => moliliApi.orders.findByOrderNo(orderNo as string),
    staleTime: 10_000,
  });
}
