import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Github,
  Brain,
  Workflow,
  Plug,
  Shield,
  Layers,
  Globe,
  Target,
  ListChecks,
  PlayCircle,
  Eye,
  Database,
  TrendingUp,
  Sparkles,
  Zap,
  BarChart3,
} from "lucide-react";
import { GITHUB_URL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { Button } from "@/components/ui/button";
import { FlickeringGrid } from "@/components/ui/flickering-grid";

const featureMeta = [
  { icon: Brain, key: "deepResearch" as const, title: "Planner" },
  { icon: Workflow, key: "multiAgent" as const, title: "Workers" },
  { icon: Plug, key: "skillsTools" as const, title: "Skills & Tools" },
  { icon: Shield, key: "sandbox" as const, title: "Sandbox" },
  { icon: Layers, key: "memory" as const, title: "Memory & Journal" },
  { icon: Globe, key: "multiChannel" as const, title: "Surfaces" },
];

const loopSteps = [
  { icon: Target, key: "goal" as const },
  { icon: ListChecks, key: "plan" as const },
  { icon: PlayCircle, key: "execute" as const },
  { icon: Eye, key: "observe" as const },
  { icon: Database, key: "remember" as const },
  { icon: TrendingUp, key: "improve" as const },
];

const primaryRouteMeta = [
  { icon: Sparkles, key: "agentTask" as const },
  { icon: Zap, key: "codeWork" as const },
  { icon: BarChart3, key: "inspectRuntime" as const },
];

function OctopusMark({ className = "" }: { className?: string }) {
  return (
    <svg
      width="96"
      height="96"
      viewBox="0 0 512 512"
      fill="none"
      className={className}
    >
      <path
        d="M256 32C167.6 32 96 103.6 96 192c0 52.8 25.6 99.6 65.2 128.8C128 348 96 404 96 448c0 17.7 14.3 32 32 32s32-14.3 32-32c0-28 16-68 40-96 8 4 16.4 7.2 25.2 9.6-4 26.4-9.2 56-9.2 86.4 0 17.7 14.3 32 32 32s32-14.3 32-32c0-26.4 4-52 8-76 12-2.4 23.6-6 34.8-11.2C348 384 368 420 368 448c0 17.7 14.3 32 32 32s32-14.3 32-32c0-48-36-108-72-147.2C399.6 271.6 416 233.6 416 192c0-88.4-71.6-160-160-160zm0 64c53 0 96 43 96 96s-43 96-96 96-96-43-96-96 43-96 96-96z"
        fill="currentColor"
      />
      <circle cx="224" cy="176" r="20" fill="currentColor" />
      <circle cx="288" cy="176" r="20" fill="currentColor" />
      <circle cx="228" cy="180" r="10" fill="#08080c" />
      <circle cx="292" cy="180" r="10" fill="#08080c" />
    </svg>
  );
}

export default function HomePage() {
  const navigate = useNavigate();
  const { t } = useI18n();

  const features = featureMeta.map((f) => ({
    ...f,
    description: t.landing.features[f.key],
  }));

  const loop = loopSteps.map((s) => ({
    ...s,
    label: t.workspace.landing.systemLoop[s.key],
  }));

  const primaryRoutes = primaryRouteMeta.map((r) => ({
    ...r,
    title: t.workspace.landing.primaryRoutes[r.key].title,
    description: t.workspace.landing.primaryRoutes[r.key].description,
  }));

  return (
    <div className="octo-landing-root text-foreground">
      <div className="pointer-events-none absolute inset-0 opacity-[0.18]">
        <FlickeringGrid
          color="rgb(56, 189, 248)"
          squareSize={3}
          gridGap={5}
          flickerChance={0.12}
          maxOpacity={0.35}
        />
      </div>

      <main className="relative z-10 mx-auto max-w-6xl px-6 py-16 md:py-24">
        {/* Hero */}
        <section className="grid min-h-[calc(100vh-8rem)] items-center gap-8 py-8 md:min-h-[calc(100vh-12rem)] md:grid-cols-2 md:gap-16 md:py-0">
          <div className="flex flex-col justify-center space-y-8">
            <div className="inline-flex w-fit items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-medium text-primary backdrop-blur-sm">
              <span className="relative flex size-1.5">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary opacity-75" />
                <span className="relative inline-flex size-1.5 rounded-full bg-primary" />
              </span>
              {t.workspace.landing.badge}
            </div>

            <div className="space-y-5">
              <h1 className="text-5xl font-semibold tracking-tight md:text-7xl">
                <span className="octo-landing-shimmer">Octopus</span>
              </h1>
              <p className="max-w-xl text-xl leading-relaxed text-foreground/80 md:text-2xl">
                {t.landing.tagline}
              </p>
              <p className="max-w-lg text-base leading-relaxed text-muted-foreground">
                {t.workspace.landing.description}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button
                size="lg"
                onClick={() => navigate("/workspace")}
                className="group gap-2 rounded-xl px-6 shadow-lg shadow-primary/20"
              >
                {t.landing.getStarted}
                <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
              </Button>
              <Button
                size="lg"
                variant="outline"
                asChild
                className="group gap-2 rounded-xl border-border/60 bg-card/40 backdrop-blur-sm"
              >
                <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer">
                  <Github className="size-4" />
                  GitHub
                </a>
              </Button>
            </div>

            <p className="text-xs text-muted-foreground/60">
              {t.landing.subtitle}
            </p>
          </div>

          <div className="relative flex items-center justify-center">
            <div className="octo-landing-core octo-landing-float relative flex size-64 items-center justify-center rounded-3xl border border-white/10 bg-card/30 text-primary shadow-2xl shadow-primary/10 backdrop-blur-xl md:size-80">
              <div className="absolute inset-0 rounded-3xl bg-gradient-to-br from-primary/10 via-transparent to-cyan-500/10" />
              <OctopusMark className="relative z-10 size-28 drop-shadow-[0_0_32px_rgba(var(--primary)_0.35)] md:size-36" />
            </div>

            <div className="absolute -right-4 top-8 hidden rounded-xl border border-border/50 bg-card/60 p-3 shadow-xl backdrop-blur-md md:block">
              <Brain className="size-5 text-primary" />
            </div>
            <div className="absolute -left-4 bottom-16 hidden rounded-xl border border-border/50 bg-card/60 p-3 shadow-xl backdrop-blur-md md:block">
              <Workflow className="size-5 text-cyan-400" />
            </div>
            <div className="absolute bottom-4 right-12 hidden rounded-xl border border-border/50 bg-card/60 p-3 shadow-xl backdrop-blur-md md:block">
              <Shield className="size-5 text-violet-400" />
            </div>
          </div>
        </section>

        {/* System loop */}
        <section className="relative my-24 rounded-2xl border border-border/40 bg-card/40 p-8 shadow-2xl backdrop-blur-xl md:p-12">
          <div className="octo-landing-loop-line hidden md:block">
            <div className="octo-landing-loop-dot" />
          </div>

          <div className="mb-10 text-center">
            <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
              {t.landing.subtitle.split(" — ")[0]}
            </h2>
            <p className="mt-2 text-sm text-muted-foreground">
              {t.landing.capabilitiesPanel}
            </p>
          </div>

          <div className="relative grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-6 md:gap-3">
            {loop.map((step, index) => (
              <div
                key={step.key}
                className="group relative flex flex-col items-center gap-3 rounded-xl border border-border/40 bg-background/40 p-4 text-center transition-all hover:-translate-y-1 hover:border-primary/30 hover:bg-background/60 hover:shadow-lg"
                style={{ animationDelay: `${index * 120}ms` }}
              >
                <div className="flex size-10 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary shadow-sm transition-colors group-hover:bg-primary/20">
                  <step.icon className="size-4.5" />
                </div>
                <span className="text-xs font-medium text-foreground/90">
                  {step.label}
                </span>
              </div>
            ))}
          </div>
        </section>

        {/* Capabilities */}
        <section className="my-24">
          <div className="mb-10 text-center">
            <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
              {t.landing.capabilitiesPanel}
            </h2>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {features.map((f, index) => (
              <div
                key={f.key}
                tabIndex={0}
                aria-label={f.title}
                role="article"
                className="octo-landing-card group cursor-default p-6 outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                style={{ animationDelay: `${index * 80}ms` }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    navigate("/workspace");
                  }
                }}
                onMouseMove={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  e.currentTarget.style.setProperty(
                    "--mouse-x",
                    `${e.clientX - rect.left}px`,
                  );
                  e.currentTarget.style.setProperty(
                    "--mouse-y",
                    `${e.clientY - rect.top}px`,
                  );
                }}
              >
                <div className="mb-4 flex size-10 items-center justify-center rounded-lg border border-primary/15 bg-primary/8 text-primary transition-colors group-hover:bg-primary/15">
                  <f.icon className="size-5" />
                </div>
                <h3 className="mb-1 text-sm font-semibold text-foreground/90">
                  {f.title}
                </h3>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {f.description}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* Primary routes */}
        <section className="my-24">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {primaryRoutes.map((route, index) => (
              <button
                key={route.key}
                type="button"
                aria-label={route.title}
                onClick={() => navigate("/workspace")}
                className="octo-landing-card group cursor-pointer p-6 text-left transition-all active:scale-[0.98] outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                style={{ animationDelay: `${index * 100}ms` }}
                onMouseMove={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  e.currentTarget.style.setProperty(
                    "--mouse-x",
                    `${e.clientX - rect.left}px`,
                  );
                  e.currentTarget.style.setProperty(
                    "--mouse-y",
                    `${e.clientY - rect.top}px`,
                  );
                }}
              >
                <div className="mb-4 flex items-center justify-between">
                  <div className="flex size-10 items-center justify-center rounded-lg border border-primary/15 bg-primary/8 text-primary transition-colors group-hover:bg-primary/15">
                    <route.icon className="size-5" />
                  </div>
                  <ArrowRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
                </div>
                <h3 className="mb-1 text-sm font-semibold text-foreground/90">
                  {route.title}
                </h3>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {route.description}
                </p>
              </button>
            ))}
          </div>
        </section>

        {/* Footer */}
        <footer className="flex flex-col items-center justify-between gap-4 border-t border-border/30 pt-10 text-xs text-muted-foreground md:flex-row">
          <div className="flex items-center gap-2">
            <OctopusMark className="size-5 text-primary" />
            <span className="font-medium text-foreground/80">Octopus</span>
            <span className="text-muted-foreground/60">
              Agent OS · {t.common.version} 0.2.0
            </span>
          </div>
          <div className="flex items-center gap-5">
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="transition-colors hover:text-foreground"
            >
              GitHub
            </a>
            <button
              type="button"
              onClick={() => navigate("/workspace")}
              className="transition-colors hover:text-foreground"
            >
              {t.landing.clickToEnter}
            </button>
          </div>
        </footer>
      </main>
    </div>
  );
}
