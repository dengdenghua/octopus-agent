import claudeCodeLogoUrl from "@/assets/cli-partners/claude-code.png";

const PARTNER_LOGO_URL: Record<string, string> = {
  // Bundle Claude's official app icon. claude.ai/favicon.ico intermittently
  // fails inside embedded Chromium, which used to expose the "CC" fallback.
  "claude-code": claudeCodeLogoUrl,
  "codex-cli": "https://chatgpt.com/favicon.ico",
  "trae-cli":
    "https://lf-static.traecdn.us/obj/trae-ai-tx/trae_website/favicon.png",
  "qoder-cli":
    "https://img.alicdn.com/imgextra/i3/O1CN01KliT1u1jEq947NlKH_!!6000000004517-55-tps-180-180.svg",
  "kimi-cli": "https://www.kimi.com/favicon.ico",
  "codebuddy-cli":
    "https://codebuddy-1328495429.cos.accelerate.myqcloud.com/web/ide/logo.svg",
};

/** Prefer a stable product-owned brand asset over an API-provided remote URL. */
export function localPartnerLogoUrl(
  partnerId: string,
  providedUrl?: string | null,
): string | null {
  if (partnerId === "claude-code") {
    return PARTNER_LOGO_URL[partnerId] ?? null;
  }
  return providedUrl?.trim() || PARTNER_LOGO_URL[partnerId] || null;
}
