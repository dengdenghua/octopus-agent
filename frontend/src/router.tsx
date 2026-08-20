import { lazy, Suspense, useEffect } from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";

import { ProtectedRoute } from "@/components/auth/protected-route";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { emitOpenSettings } from "@/core/events";
import { useI18n } from "@/core/i18n/hooks";
function StorageRedirect() {
  const search = window.location.hash.includes("?")
    ? window.location.hash.slice(window.location.hash.indexOf("?"))
    : "?surface=company";
  return <Navigate to={`/workspace/storage${search}`} replace />;
}

function HubAssetRedirect({ tab }: { tab: "plugins" | "skills" }) {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  params.set("surface", "chat");
  params.set("tab", tab);
  return <Navigate to={`/workspace/agents?${params.toString()}`} replace />;
}

function SettingsRoute() {
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const section = new URLSearchParams(location.search).get("section");
    navigate("/workspace/realtime/new", { replace: true });
    // Emit after navigation lands so the settings listener is mounted before
    // the payload arrives; dispatching first lost the tab when the sidebar
    // attached late.
    const handle = window.setTimeout(() => {
      emitOpenSettings(section ?? undefined);
    }, 0);
    return () => window.clearTimeout(handle);
  }, [location.search, navigate]);

  return <PageLoading />;
}

const LEGACY_REDIRECTS = {
  mobile: "/workspace/computer",
  store: "/workspace/agents?surface=chat",
  replay: "/workspace/observability",
  workflows: "/workspace/agents?surface=chat&tab=skills",
} as const;

const LoginPage = lazy(() => import("./app/login/page"));
const RegisterPage = lazy(() => import("./app/register/page"));
const AboutPage = lazy(() => import("./app/about/page"));
const TermsPage = lazy(() => import("./app/terms/page"));
const PrivacyPage = lazy(() => import("./app/privacy/page"));
const DesktopPage = lazy(() => import("./app/desktop/page"));
const TopBrowserPage = lazy(() => import("./app/browser/page"));

const WorkspaceLayout = lazy(() => import("./app/workspace/layout"));
const ChatPage = lazy(() => import("./app/workspace/realtime/[thread_id]/page"));
const TeamJoinPage = lazy(() => import("./app/workspace/team/join/page"));
const ComputerPage = lazy(() => import("./app/workspace/computer/page"));
const DesktopOrganizerPage = lazy(
  () => import("./app/workspace/desktop-organizer/page"),
);
const AgentsPage = lazy(() => import("./app/workspace/agents/page"));
const AgentsNewPage = lazy(() => import("./app/workspace/agents/new/page"));
const CommunityPage = lazy(() => import("./app/workspace/community/page"));
const ChannelsPage = lazy(() => import("./app/workspace/channels/page"));
const ArchitecturePage = lazy(
  () => import("./app/workspace/architecture/page"),
);
// Workspace-scoped observability surface: focused tabs for swarm
// sub-agent tracing, blackboard snapshot, journal stream, 6-producer
// regeneration summary, hemolymph compose-budget meter, and per-task
// cost.
const ObservabilityPage = lazy(
  () => import("./app/workspace/observability/page"),
);
// Previously orphaned: implemented under ``src/app/workspace/`` and
// linked from the sidebar (``workspace-sidebar.tsx``) but never
// wired into this router. Clicks fell through to the ``*`` catch-all
// and bounced the user to landing. Fixed by registering them here.
const IntelligencePage = lazy(
  () => import("./app/workspace/intelligence/page"),
);
const KnowledgePage = lazy(() => import("./app/workspace/knowledge/page"));
const StoragePage = lazy(() => import("./app/workspace/storage/page"));
const EvolutionPage = lazy(() => import("./app/workspace/evolution/page"));
const ProjectsPage = lazy(
  () => import("./app/workspace/projects/page"),
);
const PaperTradingPage = lazy(
  () => import("./app/workspace/paper-trading/page"),
);
// Reflex monitor + YAML editor. See app/workspace/reflex/page.tsx.
const ReflexMonitorPage = lazy(() => import("./app/workspace/reflex/page"));
const ReflexEditorPage = lazy(() => import("./app/workspace/reflex/edit/page"));
function PageLoading() {
  const { t } = useI18n();
  return (
    <div className="flex h-screen items-center justify-center">
      <div className="text-muted-foreground text-sm">{t.common.loading}</div>
    </div>
  );
}

export function AppRouter() {
  // Warm the chunks a user almost always reaches next, during browser idle
  // time, so the first navigation into the workspace and the first code block
  // render without a visible lazy-load delay. Purely opportunistic: every
  // fetch is fire-and-forget and failures are swallowed.
  useEffect(() => {
    let cancelled = false;
    const warm = () => {
      if (cancelled) return;
      void import("./app/workspace/layout").catch(() => {});
      void import("./app/workspace/realtime/[thread_id]/page").catch(() => {});
      void import("shiki")
        .then(({ codeToHtml }) =>
          Promise.all(
            ["javascript", "typescript", "python"].map((lang) =>
              codeToHtml("", { lang, theme: "one-dark-pro" }),
            ),
          ),
        )
        .catch(() => {});
    };
    const ric = (
      window as unknown as {
        requestIdleCallback?: (cb: () => void) => number;
      }
    ).requestIdleCallback;
    const cic = (
      window as unknown as {
        cancelIdleCallback?: (handle: number) => void;
      }
    ).cancelIdleCallback;
    let idleHandle: number | undefined;
    let timeoutHandle: number | undefined;
    if (typeof ric === "function") {
      idleHandle = ric(warm);
    } else {
      timeoutHandle = window.setTimeout(warm, 1500);
    }
    return () => {
      cancelled = true;
      if (idleHandle !== undefined && typeof cic === "function") {
        cic(idleHandle);
      }
      if (timeoutHandle !== undefined) {
        window.clearTimeout(timeoutHandle);
      }
    };
  }, []);

  return (
    <ErrorBoundary>
      <Suspense fallback={<PageLoading />}>
        <Routes>
          <Route path="/" element={<LoginPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/terms" element={<TermsPage />} />
          <Route path="/privacy" element={<PrivacyPage />} />

          <Route element={<ProtectedRoute />}>
            <Route
              path="/settings"
              element={<Navigate to="/workspace/settings" replace />}
            />
            <Route path="/desktop" element={<DesktopPage />} />
            <Route path="/browser" element={<TopBrowserPage />} />
            <Route
              path="/plugins"
              element={<HubAssetRedirect tab="plugins" />}
            />

            <Route path="/workspace" element={<WorkspaceLayout />}>
              <Route index element={<Navigate to="realtime/new" replace />} />
              <Route
                path="realtime"
                element={<Navigate to="/workspace/realtime/new" replace />}
              />
              <Route path="realtime/:threadId" element={<ChatPage />} />
              <Route path="team/join" element={<TeamJoinPage />} />
              {/* The task preview is owned by the Agent Workbench now. Keep
                  the old deep link alive, but do not expose a second browser
                  surface. */}
              <Route
                path="browser"
                element={<Navigate to="/workspace/realtime/new" replace />}
              />
              <Route path="computer" element={<ComputerPage />} />
              <Route
                path="desktop-organizer"
                element={<DesktopOrganizerPage />}
              />
              <Route
                path="mobile"
                element={<Navigate to={LEGACY_REDIRECTS.mobile} replace />}
              />
              <Route
                path="settings"
                element={<SettingsRoute />}
              />
              <Route
                path="mcp"
                element={
                  <Navigate to="/workspace/settings?section=tools" replace />
                }
              />
              <Route path="agents" element={<AgentsPage />} />
              <Route path="agents/new" element={<AgentsNewPage />} />
              <Route
                path="skills"
                element={<HubAssetRedirect tab="skills" />}
              />
              <Route path="community" element={<CommunityPage />} />
              <Route
                path="plugins"
                element={<HubAssetRedirect tab="plugins" />}
              />
              <Route
                path="store"
                element={<Navigate to={LEGACY_REDIRECTS.store} replace />}
              />
              <Route path="channels" element={<ChannelsPage />} />
              <Route path="architecture" element={<ArchitecturePage />} />
              <Route path="observability" element={<ObservabilityPage />} />
              <Route path="intelligence" element={<IntelligencePage />} />
              <Route path="knowledge" element={<KnowledgePage />} />
              <Route path="storage" element={<StoragePage />} />
              <Route path="nas" element={<StorageRedirect />} />
              <Route path="database" element={<StorageRedirect />} />
              <Route path="evolution" element={<EvolutionPage />} />
              <Route path="projects" element={<ProjectsPage />} />
              <Route path="paper-trading" element={<PaperTradingPage />} />
              <Route
                path="replay"
                element={<Navigate to={LEGACY_REDIRECTS.replay} replace />}
              />
              <Route
                path="workflows"
                element={
                  <Navigate
                    to={LEGACY_REDIRECTS.workflows}
                    replace
                  />
                }
              />
              <Route path="reflex" element={<ReflexMonitorPage />} />
              <Route path="reflex/edit" element={<ReflexEditorPage />} />
              <Route
                path="diagnostics"
                element={<ObservabilityPage initialTab="diagnostics" />}
              />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
}
