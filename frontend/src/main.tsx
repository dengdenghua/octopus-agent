import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { AppRouter } from "./router";
import { ThemeProvider } from "./components/theme-provider";
import { MaterialThemeEffects } from "./components/material-theme-effects";
import { I18nProvider } from "./core/i18n/context";
import { getLocaleFromCookie } from "./core/i18n/cookies";
import { detectLocale, normalizeLocale } from "./core/i18n/locale";
import { loadTranslations } from "./core/i18n/translations";
import { AuthProvider } from "./providers/AuthProvider";
import { AppearanceBootstrap } from "./hooks/use-appearance";
import { installPageAgentBridge } from "./core/page-agent-bridge";
import { installHashRouterShellUrlNormalizer } from "./core/router/hash-shell-url";

import "./styles/globals.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

async function bootstrap() {
  installHashRouterShellUrlNormalizer();
  installPageAgentBridge();

  const savedLocale = getLocaleFromCookie();
  const initialLocale = savedLocale
    ? normalizeLocale(savedLocale)
    : detectLocale();
  const initialTranslations = await loadTranslations(initialLocale);

  // Sync HTML lang attribute with the detected locale
  document.documentElement.lang = initialLocale.split("-")[0] ?? initialLocale;

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
              <MaterialThemeEffects />
              <AppRouter />
            </AuthProvider>
          </I18nProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </HashRouter>,
  );
}

void bootstrap();
