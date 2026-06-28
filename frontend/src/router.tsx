import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes, useParams } from "react-router-dom";

import { ProtectedRoute } from "@/components/auth/protected-route";
import { ErrorBoundary } from "@/components/ui/error-boundary";
import { useI18n } from "@/core/i18n/hooks";

/**
 * Redirect old /realtime/:id bookmarks into the workspace shell.
 */
function RealtimeRedirect() {
  const { threadId } = useParams<{ threadId: string }>();
  if (!threadId) return <Navigate to="/realtime" replace />;
  return <Navigate to={`/workspace/realtime/${threadId}`} replace />;
}

function LegacyCodeRedirect() {
  const { threadId } = useParams<{ threadId: string }>();
  const target =
    !threadId || threadId === "new"
      ? "/workspace/realtime/new"
      : `/workspace/realtime/${threadId}`;
  return <HashRedirect to={target} />;
}

function StorageRedirect() {
  const search = window.location.hash.includes("?")
    ? window.location.hash.slice(window.location.hash.indexOf("?"))
    : "?surface=company";
  return <Navigate to={`/workspace/storage${search}`} replace />;
}

function HashRedirect({ to }: { to: string }) {
  useEffect(() => {
    window.location.replace(`${window.location.pathname}#${to}`);
  }, [to]);
  return null;
}

const LoginPage = lazy(() => import("./app/login/page"));
const RegisterPage = lazy(() => import("./app/register/page"));
const AboutPage = lazy(() => import("./app/about/page"));
const TermsPage = lazy(() => import("./app/terms/page"));
const PrivacyPage = lazy(() => import("./app/privacy/page"));
const DesktopPage = lazy(() => import("./app/desktop/page"));
const TopBrowserPage = lazy(() => import("./app/browser/page"));
const PluginsPage = lazy(() => import("./app/plugins/page"));

const WorkspaceLayout = lazy(() => import("./app/workspace/layout"));
const ChatPage = lazy(() => import("./app/workspace/chats/[thread_id]/page"));
const TeamIndexPage = lazy(() => import("./app/workspace/team/page"));
const TeamJoinPage = lazy(() => import("./app/workspace/team/join/page"));
const TeamPage = lazy(() => import("./app/workspace/team/[thread_id]/page"));
const BrowserPage = lazy(() => import("./app/workspace/browser/page"));
const ComputerPage = lazy(() => import("./app/workspace/computer/page"));
const DesktopOrganizerPage = lazy(
  () => import("./app/workspace/desktop-organizer/page"),
);
const MobilePage = lazy(() => import("./app/workspace/mobile/page"));
const AgentsPage = lazy(() => import("./app/workspace/agents/page"));
const AgentsNewPage = lazy(() => import("./app/workspace/agents/new/page"));
// /workspace/store now redirects to /workspace/agents (HR/agent market).
// The StorePage component is unused but the file remains for browser/page.tsx
// which still imports UnifiedStoreOverlay from the same module.
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
const MigratePage = lazy(() => import("./app/workspace/migrate/page"));
const EvolutionPage = lazy(() => import("./app/workspace/evolution/page"));
const WorkflowsPage = lazy(() => import("./app/workspace/workflows/page"));
// Standalone replay surface. See app/workspace/replay/page.tsx.
const ReplayPage = lazy(() => import("./app/workspace/replay/page"));
// Reflex monitor + YAML editor. See app/workspace/reflex/page.tsx.
const ReflexMonitorPage = lazy(() => import("./app/workspace/reflex/page"));
const ReflexEditorPage = lazy(() => import("./app/workspace/reflex/edit/page"));
// Standalone realtime index (outside workspace shell).
const RealtimeIndexPage = lazy(() => import("./app/realtime/page"));

function PageLoading() {
  const { t } = useI18n();
  return (
    <div className="flex h-screen items-center justify-center">
      <div className="text-muted-foreground text-sm">{t.common.loading}</div>
    </div>
  );
}

export function AppRouter() {
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
            <Route path="/desktop" element={<DesktopPage />} />
            <Route path="/browser" element={<TopBrowserPage />} />
            <Route path="/plugins" element={<PluginsPage />} />

            <Route path="/realtime" element={<RealtimeIndexPage />} />
            {/* Backwards-compat: old /realtime/:id bookmarks */}
            <Route path="/realtime/:threadId" element={<RealtimeRedirect />} />
            <Route
              path="/workspace/swarm"
              element={<HashRedirect to="/workspace/realtime/new" />}
            />

            <Route path="/workspace" element={<WorkspaceLayout />}>
              <Route index element={<Navigate to="realtime/new" replace />} />
              <Route
                path="realtime"
                element={<Navigate to="/workspace/realtime/new" replace />}
              />
              <Route path="realtime/:threadId" element={<ChatPage />} />
              <Route path="chats/:threadId" element={<ChatPage />} />
              {/* Legacy code routes → realtime */}
              <Route
                path="code"
                element={<HashRedirect to="/workspace/realtime/new" />}
              />
              <Route
                path="code/new"
                element={<HashRedirect to="/workspace/realtime/new" />}
              />
              <Route path="code/:threadId" element={<LegacyCodeRedirect />} />
              <Route path="team" element={<TeamIndexPage />} />
              <Route path="team/new" element={<TeamPage />} />
              <Route path="team/join" element={<TeamJoinPage />} />
              <Route path="team/:threadId" element={<TeamPage />} />
              <Route path="browser" element={<BrowserPage />} />
              <Route path="computer" element={<ComputerPage />} />
              <Route
                path="desktop-organizer"
                element={<DesktopOrganizerPage />}
              />
              <Route path="mobile" element={<MobilePage />} />
              <Route
                path="agents/:agentName/chats/:threadId"
                element={<ChatPage />}
              />
              <Route path="agents" element={<AgentsPage />} />
              <Route path="agents/new" element={<AgentsNewPage />} />
              <Route path="plugins" element={<PluginsPage />} />
              <Route
                path="store"
                element={<Navigate to="/workspace/agents" replace />}
              />
              <Route path="channels" element={<ChannelsPage />} />
              <Route path="architecture" element={<ArchitecturePage />} />
              <Route path="observability" element={<ObservabilityPage />} />
              <Route path="intelligence" element={<IntelligencePage />} />
              <Route
                path="swarm"
                element={<HashRedirect to="/workspace/realtime/new" />}
              />
              <Route path="knowledge" element={<KnowledgePage />} />
              <Route path="storage" element={<StoragePage />} />
              <Route path="migrate" element={<MigratePage />} />
              <Route path="nas" element={<StorageRedirect />} />
              <Route path="database" element={<StorageRedirect />} />
              <Route path="evolution" element={<EvolutionPage />} />
              <Route path="replay" element={<ReplayPage />} />
              <Route path="workflows" element={<WorkflowsPage />} />
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
