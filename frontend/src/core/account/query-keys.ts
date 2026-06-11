/** React Query keys for account management.
 *
 * Centralized query key definitions for cache invalidation.
 */

export const queryKeys = {
  // Profile
  profile: () => ["account", "profile"] as const,

  // Linked accounts
  linkedAccounts: () => ["account", "linked-accounts"] as const,

  // Privacy
  privacy: () => ["account", "privacy"] as const,

  // Subscription
  subscription: () => ["account", "subscription"] as const,
  plans: (includeInactive = false) =>
    ["account", "plans", { includeInactive }] as const,

  // Usage
  usage: () => ["account", "usage"] as const,
  usageEvents: (params?: { limit?: number; event_type?: string }) =>
    ["account", "usage", "events", params] as const,
  usageSummary: (period?: string) =>
    ["account", "usage", "summary", period] as const,

  // Billing
  billingSummary: () => ["account", "billing", "summary"] as const,
  billingHistory: (limit?: number) =>
    ["account", "billing", "history", { limit }] as const,

  // Overview
  overview: () => ["account", "overview"] as const,
};
