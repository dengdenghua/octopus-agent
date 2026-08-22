import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  ArrowRightIcon,
  KeyRoundIcon,
  MailIcon,
  SparklesIcon,
  ZapIcon,
  GitBranchIcon,
  BoxesIcon,
  UserCircle2Icon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { OctopusBrandMark } from "@/components/brand/octopus-brand-mark";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { type AuthProviderInfo, getAuthProviderInfo } from "@/core/auth/api";
import {
  authReturnToFromSearch,
  registerPathWithReturnTo,
} from "@/core/auth/return-to";
import { octAuthApi, OctApiError } from "@/core/oct/api";
import { useI18n } from "@/core/i18n/hooks";
import { useAuth } from "@/providers/AuthProvider";
import { toast } from "sonner";

const SMS_COOLDOWN_SECONDS = 60;
const AUTH_PROVIDER_RETRY_COUNT = 5; // 24 → 5
const AUTH_PROVIDER_BASE_DELAY_MS = 500;

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isValidEmail(raw: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(raw.trim());
}

function EmailLoginForm({ returnTo }: { returnTo: string }) {
  const navigate = useNavigate();
  const { emailLogin } = useAuth();
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sending, setSending] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const id = setInterval(() => {
      setCooldown((s) => Math.max(0, s - 1));
    }, 1000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cooldown > 0]);

  async function sendCode() {
    const addr = email.trim();
    if (!isValidEmail(addr)) {
      toast.error(t.auth.errors.invalidEmail);
      return;
    }
    setSending(true);
    try {
      const r = await octAuthApi.emailSend(addr);
      toast.success(t.auth.success.emailCodeSent);
      if (r.dev_code) toast.message(t.auth.devCodeNotice(r.dev_code));
      setCooldown(SMS_COOLDOWN_SECONDS);
    } catch (err) {
      if (err instanceof OctApiError && err.status === 503) {
        toast.error(t.auth.errors.gatewayNotEnabled);
      } else {
        toast.error(
          err instanceof Error ? err.message : t.auth.errors.sendFailed,
        );
      }
    } finally {
      setSending(false);
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const addr = email.trim();
    if (!addr || !code) {
      toast.error(t.auth.errors.emailFillRequired);
      return;
    }
    if (!isValidEmail(addr)) {
      toast.error(t.auth.errors.invalidEmail);
      return;
    }
    setSubmitting(true);
    try {
      await emailLogin(addr, code.trim());
      toast.success(t.auth.success.loginSuccess);
      navigate(returnTo, { replace: true });
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t.auth.errors.loginFailed,
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      <div className="space-y-2.5">
        <Label htmlFor="email" className="text-sm font-medium">
          {t.auth.emailLabel}
        </Label>
        <div className="relative">
          <MailIcon className="pointer-events-none absolute left-4 top-1/2 size-[18px] -translate-y-1/2 text-muted-foreground/50" />
          <Input
            id="email"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            autoFocus
            className="h-12 rounded-xl border-border/60 bg-card/50 pl-11 text-base transition-colors focus:border-primary/40 focus:bg-card"
          />
        </div>
      </div>
      <div className="space-y-2.5">
        <Label htmlFor="email-code" className="text-sm font-medium">
          {t.auth.verificationCode}
        </Label>
        <div className="flex gap-3">
          <div className="relative flex-1">
            <KeyRoundIcon className="pointer-events-none absolute left-4 top-1/2 size-[18px] -translate-y-1/2 text-muted-foreground/50" />
            <Input
              id="email-code"
              type="text"
              inputMode="numeric"
              placeholder={t.auth.placeholders.code}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="h-12 rounded-xl border-border/60 bg-card/50 pl-11 text-base transition-colors focus:border-primary/40 focus:bg-card"
            />
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={sendCode}
            disabled={sending || cooldown > 0}
            className="h-12 shrink-0 rounded-xl px-5"
          >
            {cooldown > 0
              ? `${cooldown}s`
              : sending
                ? t.auth.sending
                : t.auth.sendCode}
          </Button>
        </div>
      </div>
      <Button
        type="submit"
        className="h-12 w-full rounded-xl text-base font-medium shadow-lg shadow-primary/10 transition-all hover:shadow-xl hover:shadow-primary/15"
        disabled={submitting}
      >
        {submitting ? t.auth.loggingIn : t.auth.login}
        {!submitting && <ArrowRightIcon className="ml-1 size-4" />}
      </Button>
      <p className="px-1 text-center text-xs leading-relaxed text-muted-foreground/70">
        {t.auth.terms.emailAutoRegister}
        {t.auth.terms.agreeTo}{" "}
        <Link
          to="/terms"
          className="text-primary/80 underline-offset-2 transition-colors hover:text-primary hover:underline"
        >
          {t.auth.terms.userAgreement}
        </Link>{" "}
        {t.auth.terms.and}{" "}
        <Link
          to="/privacy"
          className="text-primary/80 underline-offset-2 transition-colors hover:text-primary hover:underline"
        >
          {t.auth.terms.privacyPolicy}
        </Link>
      </p>
    </form>
  );
}

function LocalLoginForm({
  passwordRequired,
  returnTo,
}: {
  passwordRequired: boolean;
  returnTo: string;
}) {
  const navigate = useNavigate();
  const { login } = useAuth();
  const { t } = useI18n();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmedUsername = username.trim();
    if (!trimmedUsername || (passwordRequired && !password)) {
      toast.error(t.auth.errors.fillRequired);
      return;
    }
    setSubmitting(true);
    try {
      await login({
        username: trimmedUsername,
        ...(password ? { password } : {}),
      });
      toast.success(t.auth.success.loginSuccess);
      navigate(returnTo, { replace: true });
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t.auth.errors.loginFailed,
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-5">
      <div className="rounded-xl border border-border/50 bg-muted/30 px-4 py-3 text-xs text-muted-foreground/80">
        {t.loginPage.localBanner}
      </div>
      <div className="space-y-2.5">
        <Label htmlFor="local-username" className="text-sm font-medium">
          {t.registerPage.usernameLabel}
        </Label>
        <div className="relative">
          <UserCircle2Icon className="pointer-events-none absolute left-4 top-1/2 size-[18px] -translate-y-1/2 text-muted-foreground/50" />
          <Input
            id="local-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder={t.registerPage.usernamePlaceholder}
            autoComplete="username"
            className="h-12 rounded-xl border-border/60 bg-card/50 pl-11 text-base transition-colors focus:border-primary/40 focus:bg-card"
          />
        </div>
      </div>
      {passwordRequired && (
        <div className="space-y-2.5">
          <Label htmlFor="local-password" className="text-sm font-medium">
            {t.registerPage.passwordLabel}
          </Label>
          <div className="relative">
            <KeyRoundIcon className="pointer-events-none absolute left-4 top-1/2 size-[18px] -translate-y-1/2 text-muted-foreground/50" />
            <Input
              id="local-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t.registerPage.passwordPlaceholder}
              autoComplete="current-password"
              className="h-12 rounded-xl border-border/60 bg-card/50 pl-11 text-base transition-colors focus:border-primary/40 focus:bg-card"
            />
          </div>
        </div>
      )}
      <Button
        type="submit"
        className="h-12 w-full rounded-xl text-base font-medium shadow-lg shadow-primary/10 transition-all hover:shadow-xl hover:shadow-primary/15"
        disabled={submitting}
      >
        {submitting ? t.auth.loggingIn : t.auth.login}
        {!submitting && <ArrowRightIcon className="ml-1 size-4" />}
      </Button>
    </form>
  );
}

function FloatingOrb({
  className,
  color,
  size,
  blur,
}: {
  className?: string;
  color: string;
  size: number;
  blur: number;
}) {
  return (
    <div
      className={`pointer-events-none absolute rounded-full ${className}`}
      style={{
        width: size,
        height: size,
        background: color,
        filter: `blur(${blur}px)`,
        opacity: 0.6,
      }}
    />
  );
}

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const returnTo = authReturnToFromSearch(location.search);
  const { authStatus, isLoading, isAuthenticated } = useAuth();
  const { t } = useI18n();
  const [authProviders, setAuthProviders] = useState<AuthProviderInfo[] | null>(
    null,
  );

  useEffect(() => {
    let cancelled = false;

    async function loadAuthProviders() {
      for (let attempt = 0; attempt < AUTH_PROVIDER_RETRY_COUNT; attempt += 1) {
        const providers = await getAuthProviderInfo();
        if (cancelled) return;
        if (providers.length > 0) {
          setAuthProviders(providers);
          return;
        }
        if (attempt < AUTH_PROVIDER_RETRY_COUNT - 1) {
          // 指数退避：500ms, 1s, 2s, 4s
          const backoffDelay =
            AUTH_PROVIDER_BASE_DELAY_MS * Math.pow(2, attempt);
          await delay(backoffDelay);
        }
      }
      // 5 次后仍为空，停止重试
      setAuthProviders([]);
    }

    void loadAuthProviders();
    return () => {
      cancelled = true;
    };
  }, []);

  const providersReady = authProviders !== null;
  const hasOct = authProviders?.some((p) => p.id === "oct") ?? false;
  const localProvider = authProviders?.find((p) => p.id === "local") ?? null;

  useEffect(() => {
    if (isLoading) return;
    if (isAuthenticated) {
      navigate(returnTo, { replace: true });
      return;
    }
    if (authStatus && !authStatus.enabled) {
      navigate(returnTo, { replace: true });
    }
  }, [isLoading, isAuthenticated, authStatus, navigate, returnTo]);

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="animate-pulse text-sm text-muted-foreground">
          {t.common.loading}
        </div>
      </div>
    );
  }

  if (isAuthenticated || (authStatus && !authStatus.enabled)) {
    return null;
  }

  const features = [
    {
      icon: ZapIcon,
      title: "极速响应",
      desc: "多智能体并行协作，任务秒级启动",
    },
    {
      icon: GitBranchIcon,
      title: "灵活编排",
      desc: "可视化工作流，自由组合 Agent 能力",
    },
    {
      icon: BoxesIcon,
      title: "万物连接",
      desc: "打通微信、钉钉、飞书，消息无缝流转",
    },
  ];

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background">
      {/* 背景渐变装饰 */}
      <div className="pointer-events-none absolute inset-0">
        <FloatingOrb
          className="-top-32 -left-32"
          color="linear-gradient(135deg, oklch(0.85 0.15 15), oklch(0.75 0.18 350))"
          size={500}
          blur={100}
        />
        <FloatingOrb
          className="top-1/3 -right-40"
          color="linear-gradient(135deg, oklch(0.8 0.12 260), oklch(0.75 0.15 220))"
          size={450}
          blur={120}
        />
        <FloatingOrb
          className="-bottom-40 left-1/4"
          color="linear-gradient(135deg, oklch(0.88 0.1 140), oklch(0.8 0.12 180))"
          size={400}
          blur={100}
        />
        {/* 细密网格纹理 */}
        <div
          className="absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage: `radial-gradient(circle at 1px 1px, var(--foreground) 1px, transparent 0)`,
            backgroundSize: "32px 32px",
          }}
        />
      </div>

      <div className="relative z-10 grid w-full max-w-6xl items-center gap-16 px-8 py-12 lg:grid-cols-[1.2fr_1fr] lg:gap-20">
        {/* 左侧品牌区 */}
        <div className="hidden flex-col justify-center space-y-10 lg:flex">
          {/* Logo + 品牌名 */}
          <div className="inline-flex items-center gap-3">
            <OctopusBrandMark size="lg" />
            <span className="text-xl font-semibold tracking-tight">
              Octopus Agent
            </span>
          </div>

          {/* 大标题 */}
          <div className="space-y-5">
            <div className="inline-flex items-center gap-2 rounded-full border border-primary/15 bg-primary/5 px-3 py-1.5 text-xs font-medium text-primary">
              <SparklesIcon className="size-3.5" />
              新一代多智能体操作系统
            </div>
            <h1 className="text-5xl font-bold leading-[1.1] tracking-tight lg:text-[3.5rem]">
              你的 AI
              <br />
              <span className="bg-gradient-to-r from-primary via-[oklch(0.65_0.18_20)] to-[oklch(0.6_0.16_320)] bg-clip-text text-transparent">
                私人助理
              </span>
            </h1>
            <p className="max-w-md text-lg leading-relaxed text-muted-foreground">
              一个输入框，解决所有问题。委派任务、管理项目、连接万物，Octopus
              为你代劳。
            </p>
          </div>

          {/* 特性列表 */}
          <ul className="space-y-5">
            {features.map((feature) => {
              const Icon = feature.icon;
              return (
                <li key={feature.title} className="flex items-start gap-4">
                  <div className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl border border-border/60 bg-card/60 backdrop-blur-sm transition-colors group-hover:border-primary/20 group-hover:bg-primary/5">
                    <Icon
                      className="size-5 text-primary/80"
                      strokeWidth={1.8}
                    />
                  </div>
                  <div className="space-y-1">
                    <p className="text-[15px] font-semibold">{feature.title}</p>
                    <p className="text-sm text-muted-foreground/80">
                      {feature.desc}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>

        {/* 右侧登录表单 */}
        <div className="mx-auto w-full max-w-md">
          {/* 移动端 Logo */}
          <div className="mb-8 flex items-center justify-center gap-2.5 lg:hidden">
            <OctopusBrandMark size="md" />
            <span className="text-lg font-semibold tracking-tight">
              Octopus Agent
            </span>
          </div>

          <Card className="overflow-hidden rounded-2xl border-border/50 bg-card/80 shadow-2xl shadow-black/[0.03] backdrop-blur-xl">
            <CardHeader className="space-y-2.5 pb-6 pt-8 text-center">
              <CardTitle className="text-2xl font-semibold tracking-tight">
                欢迎回来
              </CardTitle>
              <CardDescription className="text-[15px] text-muted-foreground/80">
                {hasOct
                  ? "输入邮箱，一键登录开始使用"
                  : "登录你的 Octopus 账户"}
              </CardDescription>
            </CardHeader>
            <CardContent className="px-8 pb-8 pt-0">
              {!providersReady ? (
                <div className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
                  {t.common.loading}
                </div>
              ) : hasOct && localProvider ? (
                <Tabs defaultValue="email" className="w-full">
                  <TabsList className="mb-6 grid h-11 w-full grid-cols-2 rounded-xl bg-muted/50 p-1">
                    <TabsTrigger
                      value="email"
                      className="rounded-lg text-sm font-medium data-[state=active]:bg-card data-[state=active]:shadow-sm"
                    >
                      邮箱登录
                    </TabsTrigger>
                    <TabsTrigger
                      value="local"
                      className="rounded-lg text-sm font-medium data-[state=active]:bg-card data-[state=active]:shadow-sm"
                    >
                      {localProvider.label ?? "本地账户"}
                    </TabsTrigger>
                  </TabsList>
                  <TabsContent value="email" className="mt-0">
                    <EmailLoginForm returnTo={returnTo} />
                  </TabsContent>
                  <TabsContent value="local" className="mt-0">
                    <LocalLoginForm
                      passwordRequired={
                        localProvider.password_required === true
                      }
                      returnTo={returnTo}
                    />
                  </TabsContent>
                </Tabs>
              ) : hasOct ? (
                <EmailLoginForm returnTo={returnTo} />
              ) : localProvider ? (
                <LocalLoginForm
                  passwordRequired={localProvider.password_required === true}
                  returnTo={returnTo}
                />
              ) : (
                <div className="rounded-xl border border-border/50 bg-muted/30 px-4 py-6 text-center text-sm text-muted-foreground">
                  {t.loginPage.errorServiceDisabled}
                </div>
              )}

              {authStatus?.allow_registration && (
                <div className="mt-6 text-center text-sm text-muted-foreground/80">
                  还没有账户？{" "}
                  <Link
                    to={registerPathWithReturnTo(returnTo)}
                    className="font-medium text-primary transition-colors hover:text-primary/80"
                  >
                    立即注册
                  </Link>
                </div>
              )}
            </CardContent>
          </Card>

          <p className="mt-6 text-center text-xs text-muted-foreground/50">
            © {new Date().getFullYear()} Octopus Agent. All rights reserved.
          </p>
        </div>
      </div>
    </div>
  );
}
