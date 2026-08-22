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
import {
  authReturnToFromSearch,
  loginPathWithReturnTo,
} from "@/core/auth/return-to";
import { useI18n } from "@/core/i18n/hooks";
import { useAuth } from "@/providers/AuthProvider";
import { toast } from "sonner";

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

export default function RegisterPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const returnTo = authReturnToFromSearch(location.search);
  const { t } = useI18n();
  const { register, authStatus, isLoading } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [email, setEmail] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // 注册被禁用/本地模式时跳转工作区。导航必须放进 effect：渲染期间调用
  // navigate() 会更新 HashRouter 的状态，触发 React 的
  // "Cannot update a component while rendering a different component" 警告。
  const redirectToWorkspace =
    authStatus && (!authStatus.enabled || !authStatus.allow_registration);

  useEffect(() => {
    if (redirectToWorkspace) navigate(returnTo, { replace: true });
  }, [redirectToWorkspace, navigate, returnTo]);

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
      navigate(loginPathWithReturnTo(returnTo), { replace: true });
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

  if (redirectToWorkspace) return null;

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
          <div className="inline-flex items-center gap-3">
            <OctopusBrandMark size="lg" />
            <span className="text-xl font-semibold tracking-tight">
              Octopus Agent
            </span>
          </div>

          <div className="space-y-5">
            <div className="inline-flex items-center gap-2 rounded-full border border-primary/15 bg-primary/5 px-3 py-1.5 text-xs font-medium text-primary">
              <SparklesIcon className="size-3.5" />
              开始你的 AI 助理之旅
            </div>
            <h1 className="text-5xl font-bold leading-[1.1] tracking-tight lg:text-[3.5rem]">
              创建账户
              <br />
              <span className="bg-gradient-to-r from-primary via-[oklch(0.65_0.18_20)] to-[oklch(0.6_0.16_320)] bg-clip-text text-transparent">
                即刻开启
              </span>
            </h1>
            <p className="max-w-md text-lg leading-relaxed text-muted-foreground">
              注册一个账户，立即体验多智能体协作带来的效率提升。
            </p>
          </div>

          <ul className="space-y-5">
            {features.map((feature) => {
              const Icon = feature.icon;
              return (
                <li key={feature.title} className="flex items-start gap-4">
                  <div className="mt-0.5 flex size-10 shrink-0 items-center justify-center rounded-xl border border-border/60 bg-card/60 backdrop-blur-sm">
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

        {/* 右侧注册表单 */}
        <div className="mx-auto w-full max-w-md">
          <div className="mb-8 flex items-center justify-center gap-2.5 lg:hidden">
            <OctopusBrandMark size="md" />
            <span className="text-lg font-semibold tracking-tight">
              Octopus Agent
            </span>
          </div>

          <Card className="overflow-hidden rounded-2xl border-border/50 bg-card/80 shadow-2xl shadow-black/[0.03] backdrop-blur-xl">
            <CardHeader className="space-y-2.5 pb-6 pt-8 text-center">
              <CardTitle className="text-2xl font-semibold tracking-tight">
                创建新账户
              </CardTitle>
              <CardDescription className="text-[15px] text-muted-foreground/80">
                填写以下信息，只需一分钟
              </CardDescription>
            </CardHeader>
            <CardContent className="px-8 pb-8 pt-0">
              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-2.5">
                  <Label htmlFor="username" className="text-sm font-medium">
                    {t.registerPage.usernameLabel}
                  </Label>
                  <div className="relative">
                    <UserCircle2Icon className="pointer-events-none absolute left-4 top-1/2 size-[18px] -translate-y-1/2 text-muted-foreground/50" />
                    <Input
                      id="username"
                      type="text"
                      placeholder={t.registerPage.usernamePlaceholder}
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      autoComplete="username"
                      autoFocus
                      className="h-12 rounded-xl border-border/60 bg-card/50 pl-11 text-base transition-colors focus:border-primary/40 focus:bg-card"
                    />
                  </div>
                </div>
                <div className="space-y-2.5">
                  <Label htmlFor="email" className="text-sm font-medium">
                    {t.registerPage.emailLabel}
                  </Label>
                  <div className="relative">
                    <MailIcon className="pointer-events-none absolute left-4 top-1/2 size-[18px] -translate-y-1/2 text-muted-foreground/50" />
                    <Input
                      id="email"
                      type="email"
                      placeholder="your@email.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      autoComplete="email"
                      className="h-12 rounded-xl border-border/60 bg-card/50 pl-11 text-base transition-colors focus:border-primary/40 focus:bg-card"
                    />
                  </div>
                </div>
                <div className="space-y-2.5">
                  <Label htmlFor="password" className="text-sm font-medium">
                    {t.registerPage.passwordLabel}
                  </Label>
                  <div className="relative">
                    <KeyRoundIcon className="pointer-events-none absolute left-4 top-1/2 size-[18px] -translate-y-1/2 text-muted-foreground/50" />
                    <Input
                      id="password"
                      type="password"
                      placeholder={t.registerPage.passwordPlaceholder}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      autoComplete="new-password"
                      className="h-12 rounded-xl border-border/60 bg-card/50 pl-11 text-base transition-colors focus:border-primary/40 focus:bg-card"
                    />
                  </div>
                </div>
                <div className="space-y-2.5">
                  <Label
                    htmlFor="confirmPassword"
                    className="text-sm font-medium"
                  >
                    {t.registerPage.confirmPasswordLabel}
                  </Label>
                  <div className="relative">
                    <KeyRoundIcon className="pointer-events-none absolute left-4 top-1/2 size-[18px] -translate-y-1/2 text-muted-foreground/50" />
                    <Input
                      id="confirmPassword"
                      type="password"
                      placeholder={t.registerPage.confirmPasswordPlaceholder}
                      value={confirmPassword}
                      onChange={(e) => setConfirmPassword(e.target.value)}
                      autoComplete="new-password"
                      className="h-12 rounded-xl border-border/60 bg-card/50 pl-11 text-base transition-colors focus:border-primary/40 focus:bg-card"
                    />
                  </div>
                </div>
                <Button
                  type="submit"
                  className="h-12 w-full rounded-xl text-base font-medium shadow-lg shadow-primary/10 transition-all hover:shadow-xl hover:shadow-primary/15"
                  disabled={isSubmitting}
                >
                  {isSubmitting
                    ? t.registerPage.submitting
                    : t.registerPage.submitButton}
                  {!isSubmitting && <ArrowRightIcon className="ml-1 size-4" />}
                </Button>
              </form>
              <div className="mt-6 text-center text-sm text-muted-foreground/80">
                已有账户？{" "}
                <Link
                  to={loginPathWithReturnTo(returnTo)}
                  className="font-medium text-primary transition-colors hover:text-primary/80"
                >
                  立即登录
                </Link>
              </div>
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
