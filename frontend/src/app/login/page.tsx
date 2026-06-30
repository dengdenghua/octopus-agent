import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRightIcon,
  KeyRoundIcon,
  MailIcon,
  SmartphoneIcon,
  SparklesIcon,
  TargetIcon,
  ListChecksIcon,
  PlayCircleIcon,
  UserCircle2Icon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
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
import {
  type AuthProviderInfo,
  getAuthProviderInfo,
  isMoliliDisabled,
  moliliSmsSend,
} from "@/core/auth/api";
import { octAuthApi, OctApiError } from "@/core/oct";
import { useI18n } from "@/core/i18n/hooks";
import { useAuth } from "@/providers/AuthProvider";
import { toast } from "sonner";

const SMS_COOLDOWN_SECONDS = 60;
const AUTH_PROVIDER_RETRY_COUNT = 24;
const AUTH_PROVIDER_RETRY_DELAY_MS = 500;

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function BrandMark() {
  return (
    <span
      aria-hidden="true"
      className="relative grid size-9 shrink-0 place-items-center overflow-hidden rounded-xl border border-white/15 bg-[linear-gradient(145deg,rgba(59,130,246,0.32),rgba(14,165,233,0.16)_48%,rgba(15,23,42,0.82))] shadow-[inset_0_1px_0_rgba(255,255,255,0.28),0_14px_34px_rgba(37,99,235,0.24)] ring-1 ring-primary/25"
    >
      <span className="absolute inset-0 bg-[radial-gradient(circle_at_30%_22%,rgba(255,255,255,0.38),transparent_28%),radial-gradient(circle_at_72%_78%,rgba(34,211,238,0.25),transparent_32%)]" />
      <span className="absolute left-1/2 top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full border border-sky-200/75 bg-foreground/45 shadow-[0_0_18px_rgba(56,189,248,0.72)]" />
      <span className="absolute left-1/2 top-[0.42rem] h-[1.05rem] w-px -translate-x-1/2 bg-sky-100/70" />
      <span className="absolute bottom-[0.42rem] left-1/2 h-[1.05rem] w-px -translate-x-1/2 bg-sky-100/70" />
      <span className="absolute left-[0.42rem] top-1/2 h-px w-[1.05rem] -translate-y-1/2 bg-sky-100/70" />
      <span className="absolute right-[0.42rem] top-1/2 h-px w-[1.05rem] -translate-y-1/2 bg-sky-100/70" />
      <span className="absolute left-[0.48rem] top-[0.48rem] size-1.5 rounded-full bg-cyan-200 shadow-[0_0_10px_rgba(125,211,252,0.82)]" />
      <span className="absolute right-[0.48rem] top-[0.48rem] size-1.5 rounded-full bg-blue-200 shadow-[0_0_10px_rgba(147,197,253,0.82)]" />
      <span className="absolute bottom-[0.48rem] left-[0.48rem] size-1.5 rounded-full bg-blue-300 shadow-[0_0_10px_rgba(96,165,250,0.82)]" />
      <span className="absolute bottom-[0.48rem] right-[0.48rem] size-1.5 rounded-full bg-cyan-300 shadow-[0_0_10px_rgba(34,211,238,0.82)]" />
    </span>
  );
}

function isValidCnPhone(raw: string): boolean {
  const cleaned = raw.trim();
  const digits = cleaned.replace(/\D/g, "");
  return /^1\d{10}$/.test(digits) || digits.length >= 7;
}

function normalizePhone(raw: string): string {
  const cleaned = raw.trim();
  if (cleaned.startsWith("+")) {
    return `+${cleaned.slice(1).replace(/\D/g, "")}`;
  }
  return cleaned.replace(/\D/g, "");
}

function SmsLoginForm() {
  const navigate = useNavigate();
  const { smsLogin } = useAuth();
  const { t } = useI18n();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sending, setSending] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (cooldown <= 0) return;
    tickRef.current = setInterval(() => {
      setCooldown((s) => Math.max(0, s - 1));
    }, 1000);
    return () => {
      if (tickRef.current) clearInterval(tickRef.current);
    };
  }, [cooldown]);

  async function sendCode() {
    const normalizedPhone = normalizePhone(phone);
    if (!isValidCnPhone(normalizedPhone)) {
      toast.error(t.auth.errors.invalidPhone);
      return;
    }
    setSending(true);
    try {
      await moliliSmsSend(normalizedPhone);
      toast.success(t.auth.success.codeSent);
      setCooldown(SMS_COOLDOWN_SECONDS);
    } catch (err) {
      if (isMoliliDisabled(err)) {
        toast.error(t.auth.errors.moliliNotEnabled);
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
    const normalizedPhone = normalizePhone(phone);
    if (!normalizedPhone || !code) {
      toast.error(t.auth.errors.fillRequired);
      return;
    }
    if (!isValidCnPhone(normalizedPhone)) {
      toast.error(t.auth.errors.invalidPhone);
      return;
    }
    setSubmitting(true);
    try {
      await smsLogin(normalizedPhone, code.trim());
      toast.success(t.auth.success.loginSuccess);
      navigate("/workspace");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t.auth.errors.loginFailed,
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="phone">{t.auth.phoneNumber}</Label>
        <div className="relative">
          <SmartphoneIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/60" />
          <Input
            id="phone"
            type="tel"
            placeholder={t.auth.placeholders.phone}
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            autoComplete="tel"
            autoFocus
            className="pl-9"
          />
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="code">{t.auth.verificationCode}</Label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <KeyRoundIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/60" />
            <Input
              id="code"
              type="text"
              inputMode="numeric"
              placeholder={t.auth.placeholders.code}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="pl-9"
            />
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={sendCode}
            disabled={sending || cooldown > 0}
            className="shrink-0"
          >
            {cooldown > 0
              ? `${cooldown}s`
              : sending
                ? t.auth.sending
                : t.auth.sendCode}
          </Button>
        </div>
      </div>
      <Button type="submit" className="w-full" disabled={submitting}>
        {submitting ? t.auth.loggingIn : t.auth.login}
        {!submitting && <ArrowRightIcon className="size-4" />}
      </Button>
      <p className="px-2 text-center text-[11px] leading-5 text-muted-foreground">
        {t.auth.terms.autoRegister}
        {t.auth.terms.agreeTo}{" "}
        <Link
          to="/terms"
          className="text-primary underline-offset-2 hover:text-primary/80 hover:underline"
        >
          {t.auth.terms.userAgreement}
        </Link>{" "}
        {t.common.other}{" "}
        <Link
          to="/privacy"
          className="text-primary underline-offset-2 hover:text-primary/80 hover:underline"
        >
          {t.auth.terms.privacyPolicy}
        </Link>
      </p>
    </form>
  );
}

function isValidEmail(raw: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(raw.trim());
}

function EmailLoginForm() {
  const navigate = useNavigate();
  const { emailLogin } = useAuth();
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sending, setSending] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (cooldown <= 0) return;
    tickRef.current = setInterval(() => {
      setCooldown((s) => Math.max(0, s - 1));
    }, 1000);
    return () => {
      if (tickRef.current) clearInterval(tickRef.current);
    };
  }, [cooldown]);

  async function sendCode() {
    const addr = email.trim();
    if (!isValidEmail(addr)) {
      toast.error("请输入有效的邮箱地址");
      return;
    }
    setSending(true);
    try {
      const r = await octAuthApi.emailSend(addr);
      toast.success(t.auth.success.codeSent);
      if (r.dev_code) toast.message(`验证码(开发模式): ${r.dev_code}`);
      setCooldown(SMS_COOLDOWN_SECONDS);
    } catch (err) {
      if (err instanceof OctApiError && err.status === 503) {
        toast.error(t.auth.errors.moliliNotEnabled);
      } else {
        toast.error(err instanceof Error ? err.message : t.auth.errors.sendFailed);
      }
    } finally {
      setSending(false);
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const addr = email.trim();
    if (!addr || !code) {
      toast.error(t.auth.errors.fillRequired);
      return;
    }
    if (!isValidEmail(addr)) {
      toast.error("请输入有效的邮箱地址");
      return;
    }
    setSubmitting(true);
    try {
      await emailLogin(addr, code.trim());
      toast.success(t.auth.success.loginSuccess);
      navigate("/workspace");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.auth.errors.loginFailed);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="email">邮箱</Label>
        <div className="relative">
          <MailIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/60" />
          <Input
            id="email"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            autoFocus
            className="pl-9"
          />
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="email-code">{t.auth.verificationCode}</Label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <KeyRoundIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/60" />
            <Input
              id="email-code"
              type="text"
              inputMode="numeric"
              placeholder={t.auth.placeholders.code}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="pl-9"
            />
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={sendCode}
            disabled={sending || cooldown > 0}
            className="shrink-0"
          >
            {cooldown > 0
              ? `${cooldown}s`
              : sending
                ? t.auth.sending
                : t.auth.sendCode}
          </Button>
        </div>
      </div>
      <Button type="submit" className="w-full" disabled={submitting}>
        {submitting ? t.auth.loggingIn : t.auth.login}
        {!submitting && <ArrowRightIcon className="size-4" />}
      </Button>
      <p className="px-2 text-center text-[11px] leading-5 text-muted-foreground">
        {t.auth.terms.autoRegister}
        {t.auth.terms.agreeTo}{" "}
        <Link
          to="/terms"
          className="text-primary underline-offset-2 hover:text-primary/80 hover:underline"
        >
          {t.auth.terms.userAgreement}
        </Link>{" "}
        {t.common.other}{" "}
        <Link
          to="/privacy"
          className="text-primary underline-offset-2 hover:text-primary/80 hover:underline"
        >
          {t.auth.terms.privacyPolicy}
        </Link>
      </p>
    </form>
  );
}

function LocalLoginForm({
  passwordRequired,
}: {
  passwordRequired: boolean;
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
      navigate("/workspace", { replace: true });
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t.auth.errors.loginFailed,
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="rounded-lg border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">
        {t.loginPage.localBanner}
      </div>
      <div className="space-y-2">
        <Label htmlFor="local-username">{t.registerPage.usernameLabel}</Label>
        <div className="relative">
          <UserCircle2Icon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/60" />
          <Input
            id="local-username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder={t.registerPage.usernamePlaceholder}
            autoComplete="username"
            className="pl-9"
          />
        </div>
      </div>
      {passwordRequired && (
        <div className="space-y-2">
          <Label htmlFor="local-password">{t.registerPage.passwordLabel}</Label>
          <div className="relative">
            <KeyRoundIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/60" />
            <Input
              id="local-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t.registerPage.passwordPlaceholder}
              autoComplete="current-password"
              className="pl-9"
            />
          </div>
        </div>
      )}
      <Button
        type="submit"
        className="w-full"
        disabled={submitting}
      >
        {submitting ? t.auth.loggingIn : t.auth.login}
        {!submitting && <ArrowRightIcon className="size-4" />}
      </Button>
    </form>
  );
}

export default function LoginPage() {
  const navigate = useNavigate();
  const { authStatus, isLoading, isAuthenticated } = useAuth();
  const { t } = useI18n();
  const [authProviders, setAuthProviders] =
    useState<AuthProviderInfo[] | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadAuthProviders() {
      for (let attempt = 0; attempt < AUTH_PROVIDER_RETRY_COUNT; attempt += 1) {
        const providers = await getAuthProviderInfo();
        if (cancelled) return;
        if (providers.length > 0 || attempt === AUTH_PROVIDER_RETRY_COUNT - 1) {
          setAuthProviders(providers);
          return;
        }
        await delay(AUTH_PROVIDER_RETRY_DELAY_MS);
      }
    }

    void loadAuthProviders();
    return () => {
      cancelled = true;
    };
  }, []);

  const providersReady = authProviders !== null;
  const hasOct = authProviders?.some((p) => p.id === "oct") ?? false;
  const hasMolili = authProviders?.some((p) => p.id === "molili") ?? false;
  const localProvider = authProviders?.find((p) => p.id === "local") ?? null;

  useEffect(() => {
    if (isLoading) return;
    if (isAuthenticated) {
      navigate("/workspace", { replace: true });
      return;
    }
    if (authStatus && !authStatus.enabled) {
      navigate("/workspace", { replace: true });
    }
  }, [isLoading, isAuthenticated, authStatus, navigate]);

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

  const loopIcons = [TargetIcon, ListChecksIcon, PlayCircleIcon];
  const loopSteps = [
    t.workspace.landing.systemLoop.goal,
    t.workspace.landing.systemLoop.plan,
    t.workspace.landing.systemLoop.execute,
  ];

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background text-foreground">
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background: `radial-gradient(ellipse at top, color-mix(in oklch, var(--primary) 10%, transparent), transparent 55%), radial-gradient(ellipse at bottom right, color-mix(in oklch, var(--primary) 8%, transparent), transparent 50%)`,
        }}
      />
      <div className="pointer-events-none absolute -top-40 left-1/2 size-[36rem] -translate-x-1/2 rounded-full bg-primary/15 blur-3xl" />

      <div className="relative z-10 grid w-full max-w-6xl items-center gap-12 px-6 py-12 md:grid-cols-2 lg:gap-16">
        <div className="hidden flex-col justify-center space-y-8 md:flex">
          <div className="inline-flex items-center gap-2.5">
            <BrandMark />
            <span className="text-base font-semibold tracking-tight text-foreground">
              Octopus Agent OS
            </span>
          </div>

          <div className="space-y-4">
            <div className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
              <SparklesIcon className="size-3" />
              {t.workspace.landing.badge}
            </div>
            <h1 className="text-4xl font-semibold leading-[1.08] tracking-tight text-foreground lg:text-[2.75rem]">
              {t.workspace.landing.headline}
            </h1>
            <p className="max-w-md text-base leading-relaxed text-muted-foreground">
              {t.workspace.landing.description}
            </p>
          </div>

          <ul className="space-y-3.5">
            {loopSteps.map((step, index) => {
              const Icon = loopIcons[index] ?? SparklesIcon;
              return (
                <li key={step} className="flex items-center gap-3">
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-border bg-card text-foreground shadow-sm">
                    <Icon className="size-3.5" />
                  </span>
                  <span className="text-sm font-medium text-foreground/90">
                    {step}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="mx-auto w-full max-w-sm">
          <div className="mb-6 flex items-center justify-center gap-2 md:hidden">
            <BrandMark />
            <span className="text-sm font-semibold tracking-tight text-foreground">
              Octopus Agent OS
            </span>
          </div>

          <Card>
            <CardHeader className="space-y-1.5 pb-4 text-center">
              <CardTitle className="text-xl font-semibold tracking-tight text-foreground">
                {t.auth.page.title}
              </CardTitle>
              <CardDescription>{t.auth.page.cardDescription}</CardDescription>
            </CardHeader>
            <CardContent className="pt-2">
              {!providersReady ? (
                <div className="flex min-h-40 items-center justify-center text-sm text-muted-foreground">
                  {t.common.loading}
                </div>
              ) : hasOct && localProvider ? (
                <Tabs defaultValue="email" className="w-full">
                  <TabsList className="mb-5 grid w-full grid-cols-2">
                    <TabsTrigger value="email">邮箱登录</TabsTrigger>
                    <TabsTrigger value="local">
                      {localProvider.label ?? t.registerPage.usernameLabel}
                    </TabsTrigger>
                  </TabsList>
                  <TabsContent value="email">
                    <EmailLoginForm />
                  </TabsContent>
                  <TabsContent value="local">
                    <LocalLoginForm
                      passwordRequired={localProvider.password_required === true}
                    />
                  </TabsContent>
                </Tabs>
              ) : hasOct ? (
                <EmailLoginForm />
              ) : hasMolili && localProvider ? (
                <Tabs defaultValue="sms" className="w-full">
                  <TabsList className="mb-5 grid w-full grid-cols-2">
                    <TabsTrigger value="sms">{t.auth.phoneNumber}</TabsTrigger>
                    <TabsTrigger value="local">
                      {localProvider.label ?? t.registerPage.usernameLabel}
                    </TabsTrigger>
                  </TabsList>
                  <TabsContent value="sms">
                    <SmsLoginForm />
                  </TabsContent>
                  <TabsContent value="local">
                    <LocalLoginForm
                      passwordRequired={localProvider.password_required === true}
                    />
                  </TabsContent>
                </Tabs>
              ) : hasMolili ? (
                <SmsLoginForm />
              ) : localProvider ? (
                <LocalLoginForm
                  passwordRequired={localProvider.password_required === true}
                />
              ) : (
                <div className="rounded-lg border border-border bg-muted px-3 py-4 text-center text-sm text-muted-foreground">
                  {t.loginPage.errorServiceDisabled}
                </div>
              )}

              {authStatus?.allow_registration && (
                <div className="mt-4 text-center text-sm text-muted-foreground">
                  {t.auth.terms.autoRegister}
                  <Link
                    to="/register"
                    className="text-primary hover:text-primary/80"
                  >
                    {t.auth.login}
                  </Link>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
