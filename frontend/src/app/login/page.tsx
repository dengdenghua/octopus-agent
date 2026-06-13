import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowRightIcon,
  CheckCircle2Icon,
  KeyRoundIcon,
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
  getAuthProviders,
  isMoliliDisabled,
  moliliSmsSend,
} from "@/core/auth/api";
import { useI18n } from "@/core/i18n/hooks";
import { useAuth } from "@/providers/AuthProvider";
import { toast } from "sonner";

const SMS_COOLDOWN_SECONDS = 60;
const AUTH_PROVIDER_RETRY_COUNT = 24;
const AUTH_PROVIDER_RETRY_DELAY_MS = 500;
const octopusLogoUrl = `${import.meta.env.BASE_URL}images/octopus.svg`;

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
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
          <SmartphoneIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
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
            <KeyRoundIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
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
      <p className="px-2 text-center text-[11px] leading-5 text-slate-500">
        {t.auth.terms.autoRegister}
        {t.auth.terms.agreeTo}{" "}
        <Link
          to="/terms"
          className="text-slate-700 underline-offset-2 hover:text-blue-700 hover:underline"
        >
          {t.auth.terms.userAgreement}
        </Link>{" "}
        {t.common.other}{" "}
        <Link
          to="/privacy"
          className="text-slate-700 underline-offset-2 hover:text-blue-700 hover:underline"
        >
          {t.auth.terms.privacyPolicy}
        </Link>
      </p>
    </form>
  );
}

function GuestLoginForm() {
  const navigate = useNavigate();
  const { guestLogin } = useAuth();
  const { t } = useI18n();
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await guestLogin();
      toast.success(t.auth.success.guestEntered);
      setTimeout(() => {
        navigate("/workspace", { replace: true });
      }, 100);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t.auth.errors.enterFailed,
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
        <p className="text-sm font-medium text-slate-900">
          {t.auth.guestMode.title}
        </p>
        <ul className="mt-2 space-y-1.5 text-xs text-slate-600">
          {t.auth.guestMode.features.map((feature, index) => (
            <li key={index} className="flex items-start gap-2">
              <CheckCircle2Icon className="mt-0.5 size-3.5 shrink-0 text-emerald-500" />
              <span>{feature}</span>
            </li>
          ))}
        </ul>
      </div>
      <Button
        type="submit"
        variant="outline"
        className="w-full"
        disabled={submitting}
      >
        <UserCircle2Icon className="size-4" />
        {submitting ? t.auth.entering : t.auth.enterDirectly}
        {!submitting && <ArrowRightIcon className="size-4" />}
      </Button>
    </form>
  );
}

export default function LoginPage() {
  const navigate = useNavigate();
  const { authStatus, isLoading, isAuthenticated } = useAuth();
  const { t } = useI18n();
  const [authProviders, setAuthProviders] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadAuthProviders() {
      for (let attempt = 0; attempt < AUTH_PROVIDER_RETRY_COUNT; attempt += 1) {
        const providers = await getAuthProviders();
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
  const hasMolili = authProviders?.includes("molili") ?? false;

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
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <div className="animate-pulse text-sm text-slate-500">
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
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-slate-50 text-slate-900">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(59,130,246,0.10),transparent_55%),radial-gradient(ellipse_at_bottom_right,rgba(6,182,212,0.08),transparent_50%)]" />
      <div className="pointer-events-none absolute -top-40 left-1/2 size-[36rem] -translate-x-1/2 rounded-full bg-blue-200/25 blur-3xl" />

      <div className="relative z-10 grid w-full max-w-6xl items-center gap-12 px-6 py-12 md:grid-cols-2 lg:gap-16">
        <div className="hidden flex-col justify-center space-y-8 md:flex">
          <div className="inline-flex items-center gap-2.5">
            <div className="flex size-9 items-center justify-center rounded-lg bg-slate-900 text-white shadow-sm">
              <img src={octopusLogoUrl} alt="" className="size-6" />
            </div>
            <span className="text-base font-semibold tracking-tight text-slate-900">
              Octopus Agent OS
            </span>
          </div>

          <div className="space-y-4">
            <div className="inline-flex items-center gap-1.5 rounded-full border border-blue-100 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700">
              <SparklesIcon className="size-3" />
              {t.workspace.landing.badge}
            </div>
            <h1 className="text-4xl font-semibold leading-[1.08] tracking-tight text-slate-950 lg:text-[2.75rem]">
              {t.workspace.landing.headline}
            </h1>
            <p className="max-w-md text-base leading-relaxed text-slate-600">
              {t.workspace.landing.description}
            </p>
          </div>

          <ul className="space-y-3.5">
            {loopSteps.map((step, index) => {
              const Icon = loopIcons[index] ?? SparklesIcon;
              return (
                <li key={step} className="flex items-center gap-3">
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-700 shadow-sm">
                    <Icon className="size-3.5" />
                  </span>
                  <span className="text-sm font-medium text-slate-800">
                    {step}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="mx-auto w-full max-w-sm">
          <div className="mb-6 flex items-center justify-center gap-2 md:hidden">
            <div className="flex size-9 items-center justify-center rounded-lg bg-slate-900 text-white shadow-sm">
              <img src={octopusLogoUrl} alt="" className="size-6" />
            </div>
            <span className="text-sm font-semibold tracking-tight text-slate-900">
              Octopus Agent OS
            </span>
          </div>

          <Card className="border-slate-200/80 bg-white shadow-sm">
            <CardHeader className="space-y-1.5 pb-4 text-center">
              <CardTitle className="text-xl font-semibold tracking-tight text-slate-950">
                {t.auth.page.title}
              </CardTitle>
              <CardDescription className="text-sm leading-relaxed text-slate-500">
                {t.auth.page.cardDescription}
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-2">
              {!providersReady ? (
                <div className="flex min-h-40 items-center justify-center text-sm text-slate-500">
                  {t.common.loading}
                </div>
              ) : hasMolili ? (
                <Tabs defaultValue="sms" className="w-full">
                  <TabsList className="mb-5 grid w-full grid-cols-2">
                    <TabsTrigger value="sms">{t.auth.phoneNumber}</TabsTrigger>
                    <TabsTrigger value="guest">
                      {t.auth.guestMode.title}
                    </TabsTrigger>
                  </TabsList>
                  <TabsContent value="sms">
                    <SmsLoginForm />
                  </TabsContent>
                  <TabsContent value="guest">
                    <GuestLoginForm />
                  </TabsContent>
                </Tabs>
              ) : (
                <GuestLoginForm />
              )}

              {authStatus?.allow_registration && (
                <div className="mt-4 text-center text-sm text-muted-foreground">
                  {t.auth.terms.autoRegister}
                  <Link
                    to="/register"
                    className="text-blue-700 hover:text-blue-800"
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
