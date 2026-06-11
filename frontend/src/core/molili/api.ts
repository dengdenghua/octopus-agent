/**
 * Molili bridge — read the current user's linked Molili account, including
 * the credits snapshot aggregated from /userApi/v1/userInfo and
 * /creditsApi/v1/page (see backend/app/gateway/routers/molili.py).
 */
import { authHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";

export interface MoliliCreditsSummary {
  by_type: Record<string, { granted: number; remaining: number }>;
  total_granted: number;
  total_remaining: number;
}

export interface MoliliCredits {
  // Convenience: the aggregated remaining balance across all credit
  // buckets (overrides the misleading userInfo.surplusCredits which
  // only reflects the `pay` bucket).
  surplusCredits?: number;
  plan?: string;
  isMember?: boolean;
  modelDisplayName?: string;
  modelId?: string;
  packageType?: string;
  expiryTime?: string | null;
  upgrade?: boolean;
  creditsPack?: boolean;
  hasPcLoginRecord?: boolean;
  // Detailed breakdown by credit bucket (invite / pay / excess / ...).
  creditsSummary?: MoliliCreditsSummary;
  // Anything else Molili decides to add — pass-through.
  [key: string]: unknown;
}

export interface MoliliLink {
  molili_user_id: string;
  mobile?: string | null;
  linked_at: number;
  last_synced_at?: number | null;
  credits: MoliliCredits;
  /**
   * True when the backend's last refresh saw Molili reject the stored
   * token (BE_REPLACED / TOKEN_EXPIRED). Displayed credits are from
   * cache; the user must re-login via SMS to restore a fresh session.
   */
  token_invalid?: boolean;
  token_invalid_reason?: string | null;
}

/**
 * Thrown by the API helpers when the upstream returns a non-2xx. We
 * keep the status separately so callers can branch (404 → "not linked",
 * 503 → "Molili bridge disabled" etc.) without parsing strings.
 */
export class MoliliApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "MoliliApiError";
  }
}

async function _request<T>(
  path: string,
  init?: RequestInit & { signal?: AbortSignal },
): Promise<T> {
  const res = await fetch(`${getBackendBaseURL()}${path}`, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers || {}) },
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new MoliliApiError(
      res.status,
      body?.detail ?? `${init?.method ?? "GET"} ${path} → ${res.status}`,
    );
  }
  return (await res.json()) as T;
}

/**
 * Response from Molili's /dailyCreditsClaimApi/v1/info. The actual
 * payload shape is undocumented; we keep the typed fields as "best
 * known" and let the rest flow through via the index signature so the
 * component can render whatever Molili returns.
 */
export interface MoliliDailyClaimInfo {
  success?: boolean;
  errCode?: string;
  errMessage?: string;
  data?: MoliliDailyClaimData | null;
  [key: string]: unknown;
}

export interface MoliliDailyClaimData {
  /* Implementation note. */
  claimed?: boolean;
  claimedToday?: boolean;
  /** Fixed amount given when declining the draw (2500 in the reference UX). */
  fixedCredits?: number;
  directCredits?: number;
  /** Upper bound of the randomized draw (4000 in the reference UX). */
  maxCredits?: number;
  maxDrawCredits?: number;
  /** Whether a draw is still available today. */
  canDraw?: boolean;
  [key: string]: unknown;
}

export interface MoliliDailyClaimResult {
  success?: boolean;
  errCode?: string;
  errMessage?: string;
  data?: {
    /** Credits awarded in this claim. */
    credits?: number;
    addedCredits?: number;
    [key: string]: unknown;
  } | null;
  [key: string]: unknown;
}

/**
 * Molili GoodsCo — a single purchasable package. Fields below mirror
 * the upstream Swagger schema verbatim; we intentionally keep keys in
 * Molili's camelCase and type `price` as fen (1/100 yuan) since that's
 * how the upstream represents money.
 */
export interface MoliliGoods {
  id: number;
  name: string;
  /* Implementation note. */
  type: 0 | 1 | 2;
  packageType?: string;
  /* Implementation note. */
  price: number;
  originalPrice?: number;
  /** JSON string describing what credits the pack awards. */
  creditsInfo?: string;
  isRecommend?: 0 | 1;
  sort?: number;
  /* Implementation note. */
  buyType?: 1 | 2;
  outerGoodsId?: string;
  [key: string]: unknown;
}

export interface MoliliGoodsListResponse {
  success?: boolean;
  errCode?: string;
  errMessage?: string;
  // Some Molili endpoints wrap records under data.records, others put
  // the array directly in data — we accept either.
  data?: MoliliGoods[] | { records?: MoliliGoods[] } | null;
  [key: string]: unknown;
}

export interface MoliliPaymentLink {
  /** WeChat Native Pay URL (starts with ``weixin://wxpay/bizpayurl``). */
  paymentLink: string;
  /** Order number used for polling payment state. */
  orderNo: string;
}

export interface MoliliPaymentLinkResponse {
  success?: boolean;
  errCode?: string;
  errMessage?: string;
  data?: MoliliPaymentLink | null;
  [key: string]: unknown;
}

/* Implementation note. */
export interface MoliliOrder {
  orderNo: string;
  orderStatus: 0 | 100 | 200 | 300 | 400 | 500;
  goodsId?: number;
  goodsName?: string;
  amountTotal?: number;
  amountOrigin?: number;
  payTime?: string | null;
  paymentMethod?: string;
  [key: string]: unknown;
}

export interface MoliliOrderResponse {
  success?: boolean;
  errCode?: string;
  errMessage?: string;
  data?: MoliliOrder | null;
  [key: string]: unknown;
}

export interface MoliliOrderConfirmResponse {
  order_status: number | null;
  paid: boolean;
  upstream?: MoliliOrderResponse;
}

export const moliliApi = {
  /** Cached view — never hits Molili upstream. Throws 404 if not linked. */
  get: () => _request<MoliliLink>("/api/account/molili"),

  /** Force a refresh against Molili (userInfo + creditsApi/page). */
  refresh: () =>
    _request<MoliliLink>("/api/account/molili/refresh", { method: "POST" }),

  /** Drop the link — used after explicit "unlink" or token expiry. */
  unlink: () =>
    _request<{ unlinked: boolean }>("/api/account/molili/link", {
      method: "DELETE",
    }),

  dailyClaim: {
    info: () =>
      _request<MoliliDailyClaimInfo>("/api/account/molili/daily-claim/info"),

    claim: (draw: boolean) =>
      _request<MoliliDailyClaimResult>(
        "/api/account/molili/daily-claim/claim",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ draw }),
        },
      ),
  },

  goods: {
    /** Full purchasable-goods catalog, proxied from /goodsApi/v1/goodsDetailList. */
    detail: () =>
      _request<MoliliGoodsListResponse>("/api/account/molili/goods/detail"),
  },

  orders: {
    /** Create a WeChat-Pay QR link for the given goodsId. */
    createPaymentLink: (goodsId: number) =>
      _request<MoliliPaymentLinkResponse>(
        "/api/account/molili/orders/payment-link",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ goods_id: goodsId }),
        },
      ),

    /** Look up one order by Molili orderNo (pass-through proxy). */
    findByOrderNo: (orderNo: string) =>
      _request<MoliliOrderResponse>(
        `/api/account/molili/orders/${encodeURIComponent(orderNo)}`,
      ),

    /**
     * Poll-friendly variant: checks order status and, if paid, triggers
     * a backend-side credits refresh so the UI sees updated balance in
     * the same round-trip.
     */
    confirm: (orderNo: string) =>
      _request<MoliliOrderConfirmResponse>(
        `/api/account/molili/orders/${encodeURIComponent(orderNo)}/confirm`,
        { method: "POST" },
      ),
  },
};

/**
 * Flatten Molili's dual-shaped goods response (either ``data: Goods[]`` or
 * ``data: { records: Goods[] }``) into a single array. Returns ``[]`` for
 * any missing/null payload so callers don't have to branch.
 */
export function extractGoods(
  resp: MoliliGoodsListResponse | null | undefined,
): MoliliGoods[] {
  const data = resp?.data;
  if (Array.isArray(data)) return data;
  if (data && Array.isArray(data.records)) return data.records;
  return [];
}
