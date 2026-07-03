import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRightIcon, SparklesIcon } from "lucide-react";

import { OctopusBrandMark } from "@/components/brand/octopus-brand-mark";
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
import { useI18n } from "@/core/i18n/hooks";
import { useAuth } from "@/providers/AuthProvider";
import { toast } from "sonner";

export default function RegisterPage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const { register, authStatus, isLoading } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [email, setEmail] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) {
      toast.error(t.registerPage.toastFillRequired);
      return;
    }
    if (password !== confirmPassword) {
      toast.error(t.registerPage.toastPasswordMismatch);
      return;
    }
    if (username.length < 3) {
      toast.error(t.registerPage.toastUsernameTooShort);
      return;
    }
    if (password.length < 6) {
      toast.error(t.registerPage.toastPasswordTooShort);
      return;
    }

    setIsSubmitting(true);
    try {
      await register({ username, password, email: email || undefined });
      toast.success(t.registerPage.toastSuccess);
      navigate("/login");
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t.registerPage.toastFailed,
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="animate-pulse text-sm text-muted-foreground">
          {t.registerPage.loadingText}
        </div>
      </div>
    );
  }

  if (authStatus && (!authStatus.enabled || !authStatus.allow_registration)) {
    navigate("/workspace");
    return null;
  }

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
            <OctopusBrandMark />
            <span className="text-base font-semibold tracking-tight text-foreground">
              Octopus Agent OS
            </span>
          </div>

          <div className="space-y-4">
            <div className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
              <SparklesIcon className="size-3" />
              {t.registerPage.badgeText}
            </div>
            <h1 className="text-4xl font-semibold leading-[1.08] tracking-tight text-foreground lg:text-[2.75rem]">
              {t.registerPage.heroTitleLine1}
              <span className="block text-muted-foreground">
                {t.registerPage.heroTitleLine2}
              </span>
            </h1>
            <p className="max-w-md text-base leading-relaxed text-muted-foreground">
              {t.registerPage.heroDescription}
            </p>
          </div>
        </div>

        <div className="mx-auto w-full max-w-sm">
          <div className="mb-6 flex items-center justify-center gap-2 md:hidden">
            <OctopusBrandMark />
            <span className="text-sm font-semibold tracking-tight text-foreground">
              Octopus Agent OS
            </span>
          </div>

          <Card>
            <CardHeader className="space-y-1.5 pb-4 text-center">
              <div className="mb-2 flex items-center justify-center">
                <OctopusBrandMark size="lg" />
              </div>
              <CardTitle className="text-xl font-semibold tracking-tight text-foreground">
                {t.registerPage.cardTitle}
              </CardTitle>
              <CardDescription>
                {t.registerPage.cardDescription}
              </CardDescription>
            </CardHeader>
            <CardContent className="pt-2">
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="username">
                    {t.registerPage.usernameLabel}
                  </Label>
                  <Input
                    id="username"
                    type="text"
                    placeholder={t.registerPage.usernamePlaceholder}
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoComplete="username"
                    autoFocus
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="email">{t.registerPage.emailLabel}</Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="your@email.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    autoComplete="email"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password">
                    {t.registerPage.passwordLabel}
                  </Label>
                  <Input
                    id="password"
                    type="password"
                    placeholder={t.registerPage.passwordPlaceholder}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoComplete="new-password"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="confirmPassword">
                    {t.registerPage.confirmPasswordLabel}
                  </Label>
                  <Input
                    id="confirmPassword"
                    type="password"
                    placeholder={t.registerPage.confirmPasswordPlaceholder}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    autoComplete="new-password"
                  />
                </div>
                <Button
                  type="submit"
                  className="w-full"
                  disabled={isSubmitting}
                >
                  {isSubmitting
                    ? t.registerPage.submitting
                    : t.registerPage.submitButton}
                  {!isSubmitting && <ArrowRightIcon className="size-4" />}
                </Button>
              </form>
              <div className="mt-4 text-center text-sm text-muted-foreground">
                {t.registerPage.alreadyHaveAccount}{" "}
                <Link
                  to="/login"
                  className="text-primary hover:text-primary/80"
                >
                  {t.registerPage.loginLink}
                </Link>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
