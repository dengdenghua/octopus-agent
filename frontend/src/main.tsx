import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";

import { AppRouter } from "./router";
import { swallow } from "./core/utils/log";
import { ThemeProvider } from "./components/theme-provider";
import { I18nProvider } from "./core/i18n/context";
import { getLocaleFromCookie } from "./core/i18n/cookies";
import { detectLocale, normalizeLocale } from "./core/i18n/locale";
import { enUS } from "./core/i18n/locales/en-US";
import { AuthProvider } from "./providers/AuthProvider";
import { AppearanceBootstrap } from "./hooks/use-appearance";
import { BackendBootstrapOverlay } from "./components/workspace/backend-bootstrap-overlay";
import { installPageAgentBridge } from "./core/page-agent-bridge";
import { installHashRouterShellUrlNormalizer } from "./core/router/hash-shell-url";
import { normalizeLoopbackOrigin } from "./core/router/loopback-origin";
import { installAuthFetchInterceptor } from "./core/auth/fetch-interceptor";
import { getToken } from "./core/auth/api";

import { loadTranslations } from "./core/i18n/translations";

// Self-hosted Inter (fontsource) — replaces the render-blocking Google
// Fonts CDN link so first paint is local-only and Electron/offline works.
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "./styles/globals.css";

// Auth-failure handling for the FE↔BE link. Two distinct cases:
//  - 401 (unauthenticated): the token is missing/expired/invalid → clear it and
//    bounce to login. This stops the request storm at its source: once the page
//    reloads to the login screen, every polling hook unmounts.
//  - 403 (forbidden): authenticated but not allowed → DO NOT log out; just don't
//    retry (retrying a forbidden call never succeeds).
const AUTH_TOKEN_KEYS = ["octopus_auth_token", "octopus_auth_ts", "octopus_user"];
let authBounced = false;

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err ?? "");
}
function isUnauthenticated(err: unknown): boolean {
  return /\b401\b|unauthorized/i.test(errMessage(err));
}
function isAuthError(err: unknown): boolean {
  return /\b401\b|\b403\b|unauthorized|forbidden/i.test(errMessage(err));
}
function handleAuthFailure(): void {
  if (authBounced) return; // fire once — avoid reload loops mid-storm
  // Only bounce a REAL failing session. If the token is absent (already logged
  // out / on the login screen) or the deliberate guest sentinel, do nothing —
  // this is what makes the reload loop-safe: after we clear the token below, any
  // further 401 sees no token and returns here.
  let tok: string | null = null;
  try {
    tok = getToken();
  } catch (e) {
    swallow(e, "storage");
    return;
  }
  if (!tok || tok === "__guest__") return;
  authBounced = true;
  try {
    // Audit S-07: clear both storages (legacy localStorage leftovers too).
    AUTH_TOKEN_KEYS.forEach((k) => {
      localStorage.removeItem(k);
      sessionStorage.removeItem(k);
    });
  } catch {
    // storage may be unavailable; the reload still re-runs auth bootstrap.
  }
  // AuthProvider's bootstrap shows the login screen when no token is present.
  window.location.reload();
}

const queryClient = new QueryClient({
  // Any query/mutation that 401s clears auth and bounces to login once — kills
  // the silent "shell rendered, panels empty, requests storming" dead-loop.
  queryCache: new QueryCache({
    onError: (err) => {
      if (isUnauthenticated(err)) handleAuthFailure();
    },
  }),
  mutationCache: new MutationCache({
    onError: (err) => {
      if (isUnauthenticated(err)) handleAuthFailure();
    },
  }),
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

  // Mount with the target locale's pack already resolved, so no copy ever
  // flashes en-US → target on refresh. en-US resolves synchronously (bundled);
  // other packs are a ~120KB gzipped chunk fetched before first paint. If the
  // chunk fails, fall back to the bundled en-US rather than blocking boot.
  let initialTranslations = enUS;
  if (initialLocale !== "en-US") {
    try {
      initialTranslations = await loadTranslations(initialLocale);
    } catch {
      initialTranslations = enUS;
    }
  }

  createRoot(document.getElementById("root")!).render(
    <HashRouter>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider defaultTheme="system" storageKey="octopus-theme">
          <I18nProvider initialLocale={initialLocale} initialTranslations={initialTranslations}>
            <AuthProvider>
              <AppearanceBootstrap />
              <AppRouter />
              <BackendBootstrapOverlay />
            </AuthProvider>
          </I18nProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </HashRouter>,
  );
}

void bootstrap();
