/**
 * App Authorization management page.
 *
 * Similar to Accio Work's app authorization interface.
 */

import { useMemo, useState } from "react";
import {
  Search,
  Link2,
  Unlink,
  RefreshCw,
  TestTube,
  AlertCircle,
  CheckCircle2,
  Clock,
  XCircle,
  ExternalLink,
  Brain,
  Mail,
  MessageCircle,
  FileText,
  Github,
  Twitter,
  Linkedin,
  HardDrive,
  Globe,
  Zap,
  Bot,
  MessageSquare,
  Gitlab,
  Ticket,
  Figma,
  Box,
  Calendar,
  Youtube,
  Instagram,
  Music,
  Hash,
  Table,
  LayoutGrid,
  GitBranch,
  CheckSquare,
  ListTodo,
  Layout,
  CreditCard,
  Send,
  Phone,
  ShoppingBag,
  Target,
  Cloud,
  Users,
  Container,
  Triangle,
  Shield,
  Database,
  Flame,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/core/i18n/hooks";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  useProviders,
  useProviderTypes,
  useAuthorizations,
  useCreateApiKeyAuth,
  useCreateTokenAuth,
  useCreateCookieAuth,
  useDeleteAuthorization,
  useTestAuthorization,
  useBrowserCapture,
  type ProviderInfo,
  type Authorization,
} from "@/core/integrations";
import { cn } from "@/lib/utils";

// Icon mapping
const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Brain,
  Mail,
  MessageCircle,
  FileText,
  Github,
  Twitter,
  Linkedin,
  HardDrive,
  Globe,
  Zap,
  Bot,
  MessageSquare,
  Gitlab,
  Ticket,
  Figma,
  Box,
  Calendar,
  Youtube,
  Instagram,
  Music,
  Hash,
  Table,
  LayoutGrid,
  GitBranch,
  CheckSquare,
  ListTodo,
  Layout,
  CreditCard,
  Send,
  Phone,
  ShoppingBag,
  Target,
  Cloud,
  Users,
  Container,
  Triangle,
  Shield,
  Database,
  Flame,
  Sparkles,
};

function ProviderIcon({
  icon,
  color,
  className,
}: {
  icon: string | null;
  color: string | null;
  className?: string;
}) {
  const Icon = icon && ICON_MAP[icon] ? ICON_MAP[icon] : Link2;
  return (
    <div
      className={cn(
        "flex h-10 w-10 items-center justify-center rounded-lg",
        className,
      )}
      style={{ backgroundColor: color ? `${color}20` : undefined }}
    >
      <Icon
        className="h-5 w-5"
        style={{ color: color || undefined }}
      />
    </div>
  );
}

function StatusBadge({ status }: { status: Authorization["status"] }) {
  const { t } = useI18n();
  const config = {
    connected: { icon: CheckCircle2, color: "text-green-600", bg: "bg-green-50", label: t.appAuth.statusConnected },
    expired: { icon: Clock, color: "text-yellow-600", bg: "bg-yellow-50", label: t.appAuth.statusExpired },
    revoked: { icon: XCircle, color: "text-gray-600", bg: "bg-gray-50", label: t.appAuth.statusRevoked },
    error: { icon: AlertCircle, color: "text-red-600", bg: "bg-red-50", label: t.appAuth.statusError },
    pending: { icon: Clock, color: "text-blue-600", bg: "bg-blue-50", label: t.appAuth.statusPending },
  };

  const { icon: Icon, color, bg, label } = config[status];

  return (
    <Badge variant="secondary" className={cn("gap-1", bg)}>
      <Icon className={cn("h-3 w-3", color)} />
      <span className={color}>{label}</span>
    </Badge>
  );
}

function AuthCard({
  auth,
  provider,
  onDelete,
  onTest,
}: {
  auth: Authorization;
  provider?: ProviderInfo;
  onDelete: (id: string) => void;
  onTest: (id: string) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex items-start gap-4 rounded-lg border p-4 hover:bg-muted/50 transition-colors">
      <ProviderIcon
        icon={auth.icon_url || provider?.icon}
        color={provider?.color}
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h3 className="font-medium">{auth.display_name}</h3>
          <StatusBadge status={auth.status} />
        </div>
        <p className="text-sm text-muted-foreground mt-1">
          {auth.description || provider?.description}
        </p>
        {auth.last_error && (
          <p className="text-sm text-red-600 mt-1">{auth.last_error}</p>
        )}
        <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
          <span>{t.appAuth.typePrefix} {provider?.provider_type_label || auth.provider_type}</span>
          <span>
            {t.appAuth.connectedAtPrefix} {new Date(auth.connected_at * 1000).toLocaleDateString()}
          </span>
          {auth.last_used_at && (
            <span>
              {t.appAuth.lastUsedAtPrefix} {new Date(auth.last_used_at * 1000).toLocaleDateString()}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onTest(auth.id)}
          title={t.appAuth.testConnectionTooltip}
        >
          <TestTube className="h-4 w-4" />
        </Button>
        {auth.status === "expired" && (
          <Button variant="ghost" size="sm" title={t.appAuth.refreshTooltip}>
            <RefreshCw className="h-4 w-4" />
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onDelete(auth.id)}
          className="text-red-600 hover:text-red-700"
          title={t.appAuth.disconnectTooltip}
        >
          <Unlink className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

function ProviderCard({
  provider,
  onConnect,
}: {
  provider: ProviderInfo;
  onConnect: (provider: ProviderInfo) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex items-start gap-4 rounded-lg border p-4 hover:border-primary/50 transition-colors">
      <ProviderIcon icon={provider.icon} color={provider.color} />
      <div className="flex-1 min-w-0">
        <h3 className="font-medium">{provider.name}</h3>
        <p className="text-sm text-muted-foreground mt-1">
          {provider.description}
        </p>
        <div className="flex items-center gap-2 mt-2">
          <Badge variant="outline" className="text-xs">
            {provider.provider_type_label}
          </Badge>
          <Badge variant="outline" className="text-xs">
            {provider.auth_type === "api_key" && "API Key"}
            {provider.auth_type === "oauth2" && "OAuth"}
            {provider.auth_type === "cookie" && "Cookie"}
            {provider.auth_type === "token" && "Token"}
          </Badge>
        </div>
      </div>
      <Button size="sm" onClick={() => onConnect(provider)}>
        <Link2 className="h-4 w-4 mr-1" />
        {t.appAuth.connectButton}
      </Button>
    </div>
  );
}

function ConnectDialog({
  provider,
  open,
  onOpenChange,
  onSubmit,
}: {
  provider: ProviderInfo | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: { apiKey?: string; token?: string; cookie?: string }) => void;
}) {
  const { t } = useI18n();
  const [apiKey, setApiKey] = useState("");
  const [token, setToken] = useState("");
  const [cookie, setCookie] = useState("");

  if (!provider) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({ apiKey, token, cookie });
    setApiKey("");
    setToken("");
    setCookie("");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ProviderIcon icon={provider.icon} color={provider.color} />
            {t.appAuth.connectDialogTitle(provider.name)}
          </DialogTitle>
          <DialogDescription>{provider.description}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {provider.auth_type === "api_key" && (
            <div className="space-y-2">
              <label className="text-sm font-medium">
                {provider.auth_config.key_label || t.appAuth.apiKeyLabelFallback}
              </label>
              <Input
                type="password"
                placeholder={provider.auth_config.key_placeholder}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
              {provider.auth_config.help_url && (
                <a
                  href={provider.auth_config.help_url as string}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-primary flex items-center gap-1"
                >
                  {t.appAuth.howToGetApiKey} <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>
          )}

          {provider.auth_type === "token" && (
            <div className="space-y-2">
              <label className="text-sm font-medium">
                {provider.auth_config.token_label || t.appAuth.tokenLabelFallback}
              </label>
              <Input
                type="password"
                placeholder={provider.auth_config.token_placeholder as string}
                value={token}
                onChange={(e) => setToken(e.target.value)}
              />
              {provider.auth_config.help_url && (
                <p className="text-xs text-muted-foreground">
                  {provider.auth_config.help_url as string}
                </p>
              )}
            </div>
          )}

          {provider.auth_type === "cookie" && (
            <div className="space-y-2">
              <label className="text-sm font-medium">{t.appAuth.cookieLabel}</label>
              <textarea
                className="w-full min-h-[100px] rounded-md border border-input bg-background px-3 py-2 text-sm"
                placeholder={provider.auth_config.instructions as string}
                value={cookie}
                onChange={(e) => setCookie(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                {t.appAuth.cookieHint((provider.auth_config.domain as string) ?? "")}
              </p>
            </div>
          )}

          {provider.auth_type === "oauth2" && (
            <div className="py-4 text-center">
              <p className="text-sm text-muted-foreground">
                {t.appAuth.oauthRedirectHint(provider.name)}
              </p>
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              {t.appAuth.dialogCancel}
            </Button>
            <Button type="submit" disabled={!apiKey && !token && !cookie}>
              {t.appAuth.connectButton}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function BrowserCaptureDialog({
  provider,
  open,
  session,
  error,
  onCancel,
  onClose,
}: {
  provider: ProviderInfo | null;
  open: boolean;
  session: ReturnType<typeof useBrowserCapture>["session"];
  error: string | null;
  onCancel: () => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  if (!provider) return null;

  const status = session?.status ?? "running";
  const isFinished = status === "success" || status === "failed" || status === "cancelled";

  const StatusIcon =
    status === "success"
      ? CheckCircle2
      : status === "failed"
        ? XCircle
        : status === "cancelled"
          ? AlertCircle
          : Clock;

  const statusColor =
    status === "success"
      ? "text-green-600"
      : status === "failed"
        ? "text-red-600"
        : status === "cancelled"
          ? "text-gray-600"
          : "text-blue-600";

  const statusText =
    status === "success"
      ? t.appAuth.browserStatusSuccess
      : status === "failed"
        ? t.appAuth.browserStatusFailed
        : status === "cancelled"
          ? t.appAuth.browserStatusCancelled
          : t.appAuth.browserStatusWaiting;

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) {
          if (!isFinished) onCancel();
          onClose();
        }
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ProviderIcon icon={provider.icon} color={provider.color} />
            {t.appAuth.connectDialogTitle(provider.name)}
          </DialogTitle>
          <DialogDescription>
            {t.appAuth.browserDialogDescription}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <StatusIcon className={cn("h-5 w-5", statusColor)} />
            <span className={cn("font-medium", statusColor)}>{statusText}</span>
          </div>
          {session?.message && (
            <p className="text-sm text-muted-foreground">{session.message}</p>
          )}
          {error && <p className="text-sm text-red-600">{error}</p>}
          {status === "running" && (
            <div className="text-xs text-muted-foreground space-y-1">
              <p>{t.appAuth.browserStep1}</p>
              <p>{t.appAuth.browserStep2}</p>
              <p>{t.appAuth.browserStep3}</p>
            </div>
          )}
          {session && (status === "success" || status === "failed") && (
            <div className="text-xs text-muted-foreground space-y-1">
              <p>{t.appAuth.browserCookiesLabel} {session.cookies_captured ? t.appAuth.browserCaptured : t.appAuth.browserNotCaptured}</p>
              <p>{t.appAuth.browserBearerLabel} {session.bearer_captured ? t.appAuth.browserCaptured : t.appAuth.browserNotCaptured}</p>
            </div>
          )}
        </div>

        <DialogFooter>
          {isFinished ? (
            <Button onClick={onClose}>{t.appAuth.browserCloseButton}</Button>
          ) : (
            <Button variant="outline" onClick={onCancel}>
              {t.appAuth.browserCancelButton}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function AppAuthPage() {
  const { t } = useI18n();
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedType, setSelectedType] = useState<string>("all");
  const [connectProvider, setConnectProvider] = useState<ProviderInfo | null>(null);
  const [browserProvider, setBrowserProvider] = useState<ProviderInfo | null>(null);

  const { data: providers, isLoading: providersLoading } = useProviders(
    selectedType === "all" ? undefined : selectedType,
  );
  const { data: types } = useProviderTypes();
  const { data: authorizations } = useAuthorizations();

  const createApiKeyAuth = useCreateApiKeyAuth();
  const createTokenAuth = useCreateTokenAuth();
  const createCookieAuth = useCreateCookieAuth();
  const deleteAuth = useDeleteAuthorization();
  const testAuth = useTestAuthorization();
  const browserCapture = useBrowserCapture();

  const connectedProviderIds = useMemo(() => {
    return new Set(authorizations?.map((a) => a.provider) || []);
  }, [authorizations]);

  const filteredProviders = useMemo(() => {
    if (!providers) return [];
    if (!searchQuery) return providers.filter((p) => !connectedProviderIds.has(p.id));
    return providers.filter(
      (p) =>
        !connectedProviderIds.has(p.id) &&
        (p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          p.description.toLowerCase().includes(searchQuery.toLowerCase())),
    );
  }, [providers, connectedProviderIds, searchQuery]);

  const connectedAuths = useMemo(() => {
    if (!authorizations) return [];
    if (!searchQuery) return authorizations;
    return authorizations.filter(
      (a) =>
        a.display_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        a.description.toLowerCase().includes(searchQuery.toLowerCase()),
    );
  }, [authorizations, searchQuery]);

  const handleConnect = (provider: ProviderInfo) => {
    if (provider.provider_type === "browser") {
      setBrowserProvider(provider);
      browserCapture.start(provider.id);
      return;
    }
    setConnectProvider(provider);
  };

  const handleCloseBrowserDialog = () => {
    setBrowserProvider(null);
    browserCapture.reset();
  };

  const handleSubmitConnect = (values: { apiKey?: string; token?: string; cookie?: string }) => {
    if (!connectProvider) return;

    if (connectProvider.auth_type === "api_key" && values.apiKey) {
      createApiKeyAuth.mutate(
        { provider: connectProvider.id, apiKey: values.apiKey },
        { onSuccess: () => setConnectProvider(null) },
      );
    } else if (connectProvider.auth_type === "token" && values.token) {
      createTokenAuth.mutate(
        { provider: connectProvider.id, token: values.token },
        { onSuccess: () => setConnectProvider(null) },
      );
    } else if (connectProvider.auth_type === "cookie" && values.cookie) {
      createCookieAuth.mutate(
        { provider: connectProvider.id, cookieValue: values.cookie },
        { onSuccess: () => setConnectProvider(null) },
      );
    }
  };

  const handleDelete = (id: string) => {
    if (confirm(t.appAuth.confirmDisconnect)) {
      deleteAuth.mutate(id);
    }
  };

  const handleTest = (id: string) => {
    testAuth.mutate(id);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-semibold">{t.appAuth.pageTitle}</h2>
        <p className="text-muted-foreground mt-1">
          {t.appAuth.pageSubtitle}
        </p>
      </div>

      {/* Search and filter */}
      <div className="flex items-center gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder={t.appAuth.searchPlaceholder}
            className="pl-9"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
        <div className="text-sm text-muted-foreground">
          {t.appAuth.connectedCount(connectedAuths.length)}
        </div>
      </div>

      {/* Tabs */}
      <Tabs value={selectedType} onValueChange={setSelectedType}>
        <TabsList>
          <TabsTrigger value="all">{t.appAuth.tabAll}</TabsTrigger>
          {types?.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value={selectedType} className="mt-6">
          {/* Connected authorizations */}
          {connectedAuths.length > 0 && (
            <div className="mb-8">
              <h3 className="text-sm font-medium text-muted-foreground mb-3">
                {t.appAuth.connectedSectionHeader(connectedAuths.length)}
              </h3>
              <div className="space-y-3">
                {connectedAuths.map((auth) => (
                  <AuthCard
                    key={auth.id}
                    auth={auth}
                    provider={providers?.find((p) => p.id === auth.provider)}
                    onDelete={handleDelete}
                    onTest={handleTest}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Available providers */}
          <div>
            <h3 className="text-sm font-medium text-muted-foreground mb-3">
              {t.appAuth.availableSectionHeader(filteredProviders.length)}
            </h3>
            {providersLoading ? (
              <div className="text-center py-8 text-muted-foreground">{t.appAuth.loadingText}</div>
            ) : filteredProviders.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                {t.appAuth.noAvailableApps}
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {filteredProviders.map((provider) => (
                  <ProviderCard
                    key={provider.id}
                    provider={provider}
                    onConnect={handleConnect}
                  />
                ))}
              </div>
            )}
          </div>
        </TabsContent>
      </Tabs>

      {/* Connect dialog */}
      <ConnectDialog
        provider={connectProvider}
        open={!!connectProvider}
        onOpenChange={(open) => !open && setConnectProvider(null)}
        onSubmit={handleSubmitConnect}
      />

      {/* Browser-capture dialog */}
      <BrowserCaptureDialog
        provider={browserProvider}
        open={!!browserProvider}
        session={browserCapture.session}
        error={browserCapture.error}
        onCancel={browserCapture.cancel}
        onClose={handleCloseBrowserDialog}
      />
    </div>
  );
}
