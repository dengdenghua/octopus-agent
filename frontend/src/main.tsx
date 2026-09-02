import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AppRouter } from "./router";
import { ThemeProvider } from "./components/theme-provider";
import { I18nProvider } from "./core/i18n/context";
import { getLocaleFromCookie } from "./core/i18n/cookies";
import { detectLocale, normalizeLocale } from "./core/i18n/locale";
import type { Translations } from "./core/i18n/locales";
import { AuthProvider } from "./providers/AuthProvider";
import { AppearanceBootstrap } from "./hooks/use-appearance";
import { BackendBootstrapOverlay } from "./components/workspace/backend-bootstrap-overlay";
import { Toaster } from "./components/ui/sonner";
import { installPageAgentBridge } from "./core/page-agent-bridge";
import { installHashRouterShellUrlNormalizer } from "./core/router/hash-shell-url";
import { normalizeLoopbackOrigin } from "./core/router/loopback-origin";
import { installAuthFetchInterceptor } from "./core/auth/fetch-interceptor";

import { loadTranslations } from "./core/i18n/translations";

// Self-hosted Inter (fontsource) — replaces the render-blocking Google
// Fonts CDN link so first paint is local-only and Electron/offline works.
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "./styles/globals.css";

// The fetch interceptor only expires the host session when the backend marks a
// 401 with X-Octopus-Auth-Expired. A plugin, appliance capability, or downstream
// account may return its own 401 without invalidating the EchoAI login, so query
// errors must never clear the workspace session by message matching alone.
function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err ?? "");
}
function isAuthError(err: unknown): boolean {
  return /\b401\b|\b403\b|unauthorized|forbidden/i.test(errMessage(err));
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      // Never retry auth failures (401/403) — retrying only doubles the storm.
      retry: (failureCount, err) => !isAuthError(err) && failureCount < 1,
      refetchOnWindowFocus: false,
    },
  },
});

async function bootstrap() {
  if (normalizeLoopbackOrigin()) return;

  // Attach the bearer token to backend /api requests app-wide BEFORE any fetch
  // fires, so token-less calls can't 401 and trip the auth-failure handler.
  installAuthFetchInterceptor();
  installHashRouterShellUrlNormalizer();
  installPageAgentBridge();

  const savedLocale = getLocaleFromCookie();
  const initialLocale = savedLocale
    ? normalizeLocale(savedLocale)
    : detectLocale();

  document.documentElement.lang = initialLocale.split("-")[0] ?? initialLocale;

  // Resolve exactly one locale before mounting so copy never flashes between
  // languages. Keeping en-US dynamic is important: otherwise every non-English
  // user pays for the full English pack in the entry bundle as well as their
  // selected locale. If the selected chunk fails, retry with the default pack.
  let initialTranslations: Translations;
  try {
    initialTranslations = await loadTranslations(initialLocale);
  } catch {
    initialTranslations = await loadTranslations("en-US");
  }

  createRoot(document.getElementById("root")!).render(
    <HashRouter>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider defaultTheme="system" storageKey="octopus-theme">
          <I18nProvider
            initialLocale={initialLocale}
            initialTranslations={initialTranslations}
          >
            <AuthProvider>
              <AppearanceBootstrap />
              <AppRouter />
              <BackendBootstrapOverlay />
              <Toaster position="top-center" />
            </AuthProvider>
          </I18nProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </HashRouter>,
  );
}

void bootstrap();
