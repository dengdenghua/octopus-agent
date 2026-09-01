import { lazy, Suspense, useEffect, useState } from "react";
import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";

import { ProtectedRoute } from "@/components/auth/protected-route";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import {
  ElectronTitleBar,
  ElectronTitleBarProvider,
} from "@/components/electron-title-bar";
import { emitOpenSettings } from "@/core/events";
import { useI18n } from "@/core/i18n/hooks";
import {
  loadAgentsPage,
  loadProjectsPage,
} from "@/core/navigation/workspace-route-preload";
import {
  WORKBENCH_BUILTIN_APPS,
  type WorkbenchBuiltinApp,
} from "@/core/workbench/apps";
import { RemoteWorkbenchSurface } from "@/core/workbench/remote-surface";

function remoteWorkbenchApp(id: string): WorkbenchBuiltinApp {
  const app = WORKBENCH_BUILTIN_APPS.find(
    (candidate) => candidate.id === id && candidate.delivery === "remote",
  );
  if (!app) throw new Error(`Unknown remote workbench app: ${id}`);
  return app;
}

const COMMUNITY_APP = remoteWorkbenchApp("community");
const INTELLIGENCE_APP = remoteWorkbenchApp("intelligence");
const DESIGN_APP = remoteWorkbenchApp("design");
const NARRATIVE_APP = remoteWorkbenchApp("narrative");
const PAPER_TRADING_APP = remoteWorkbenchApp("paper-trading");
const EVOLUTION_APP = remoteWorkbenchApp("evolution");
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
    const params = new URLSearchParams(location.search);
    const section = params.get("section");
    const embedded = params.get("embedded");
    const target = embedded
      ? `/workspace/realtime/new?embedded=${encodeURIComponent(embedded)}`
      : "/workspace/realtime/new";
    navigate(target, { replace: true });
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
const PublicThreadSharePage = lazy(() => import("./app/share/[token]/page"));
const DesktopPage = lazy(() => import("./app/desktop/page"));
const TopBrowserPage = lazy(() => import("./app/browser/page"));
const MediaAppPage = lazy(() => import("./app/apps/media/page"));

const WorkspaceLayout = lazy(() => import("./app/workspace/layout"));
const ChatPage = lazy(
  () => import("./app/workspace/realtime/[thread_id]/page"),
);
const TeamJoinPage = lazy(() => import("./app/workspace/team/join/page"));
const ComputerPage = lazy(() => import("./app/workspace/computer/page"));
const DesktopOrganizerPage = lazy(
  () => import("./app/workspace/desktop-organizer/page"),
);
const AgentsPage = lazy(loadAgentsPage);
const AgentsNewPage = lazy(() => import("./app/workspace/agents/new/page"));
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
const KnowledgePage = lazy(() => import("./app/workspace/knowledge/page"));
const StoragePage = lazy(() => import("./app/workspace/storage/page"));
const ProjectsPage = lazy(loadProjectsPage);
const WorkspaceWebAppPage = lazy(() => import("./app/workspace/web-app/page"));
// Reflex monitor + YAML editor. See app/workspace/reflex/page.tsx.
const ReflexMonitorPage = lazy(() => import("./app/workspace/reflex/page"));
const ReflexEditorPage = lazy(() => import("./app/workspace/reflex/edit/page"));
const SLOW_PAGE_LOADING_MS = 8_000;

export function PageLoading() {
  const { t } = useI18n();
  const [isSlow, setIsSlow] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(
      () => setIsSlow(true),
      SLOW_PAGE_LOADING_MS,
    );
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className="flex h-full min-h-[320px] w-full items-start justify-center p-4 sm:p-6"
    >
      {!isSlow ? <span className="sr-only">{t.common.loading}</span> : null}
      <div
        className="w-full max-w-6xl animate-pulse space-y-4"
        data-testid="page-loading-skeleton"
      >
        <div className="flex items-center justify-between gap-4">
          <div className="space-y-2">
            <div className="h-5 w-32 rounded-md bg-muted" />
            <div className="h-3 w-56 max-w-[60vw] rounded bg-muted/70" />
          </div>
          <div className="h-8 w-24 rounded-lg bg-muted" />
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <div
              key={index}
              className="h-28 rounded-xl border border-border-subtle bg-muted/35"
            />
          ))}
        </div>
        {isSlow ? (
          <div className="flex animate-none flex-col items-center gap-2 pt-2 text-center">
            <div className="text-sm text-muted-foreground">
              {t.common.loadingWorkspace}
            </div>
            <button
              type="button"
              className="rounded-md border border-border-default px-3 py-1.5 text-xs text-foreground transition hover:bg-muted"
              onClick={() => window.location.reload()}
            >
              {t.conversation.retry}
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function AppRouter() {
  return (
    <ErrorBoundary>
      <ElectronTitleBarProvider>
        <ElectronTitleBar />
        <Suspense fallback={<PageLoading />}>
          <Routes>
            <Route path="/" element={<LoginPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/about" element={<AboutPage />} />
            <Route path="/terms" element={<TermsPage />} />
            <Route path="/privacy" element={<PrivacyPage />} />
            {/* Capability-token snapshots are intentionally outside the auth
              guard and workspace shell. The public endpoint already returns
              a bounded, sanitised, read-only projection. */}
            <Route path="/share/:token" element={<PublicThreadSharePage />} />

            <Route element={<ProtectedRoute />}>
              <Route
                path="/settings"
                element={<Navigate to="/workspace/settings" replace />}
              />
              <Route path="/desktop" element={<DesktopPage />} />
              <Route path="/browser" element={<TopBrowserPage />} />
              <Route
                path="/apps/photos"
                element={<MediaAppPage kind="image" />}
              />
              <Route
                path="/apps/media"
                element={<MediaAppPage kind="video" />}
              />
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
                {/* Browser previews stay in the Agent workbench. The complete
                    desktop browser mode owns the top-level /browser route. */}
                <Route
                  path="browser"
                  element={<Navigate to="/browser" replace />}
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
                <Route path="settings" element={<SettingsRoute />} />
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
                <Route
                  path="community"
                  element={<RemoteWorkbenchSurface app={COMMUNITY_APP} />}
                />
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
                <Route
                  path="intelligence"
                  element={<RemoteWorkbenchSurface app={INTELLIGENCE_APP} />}
                />
                <Route path="knowledge" element={<KnowledgePage />} />
                <Route path="storage" element={<StoragePage />} />
                <Route path="nas" element={<StorageRedirect />} />
                <Route path="database" element={<StorageRedirect />} />
                <Route
                  path="evolution"
                  element={<RemoteWorkbenchSurface app={EVOLUTION_APP} />}
                />
                <Route path="projects" element={<ProjectsPage />} />
                <Route
                  path="design"
                  element={<RemoteWorkbenchSurface app={DESIGN_APP} />}
                />
                <Route
                  path="narrative"
                  element={<RemoteWorkbenchSurface app={NARRATIVE_APP} />}
                />
                <Route
                  path="paper-trading"
                  element={<RemoteWorkbenchSurface app={PAPER_TRADING_APP} />}
                />
                <Route path="web-app" element={<WorkspaceWebAppPage />} />
                <Route
                  path="replay"
                  element={<Navigate to={LEGACY_REDIRECTS.replay} replace />}
                />
                <Route
                  path="workflows"
                  element={<Navigate to={LEGACY_REDIRECTS.workflows} replace />}
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
      </ElectronTitleBarProvider>
    </ErrorBoundary>
  );
}
