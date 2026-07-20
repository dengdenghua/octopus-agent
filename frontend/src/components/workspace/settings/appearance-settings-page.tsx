import {
  MonitorSmartphoneIcon,
  MoonIcon,
  SparklesIcon,
  SunIcon,
} from "lucide-react";
import { useTheme } from "next-themes";
import {
  useCallback,
  useMemo,
  useRef,
  type ComponentType,
  type PointerEvent,
  type SVGProps,
} from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Separator } from "@/components/ui/separator";
import { isLocale, SUPPORTED_LOCALES, type Locale } from "@/core/i18n";
import { useI18n } from "@/core/i18n/hooks";
import { enUS, jaJP, koKR, zhCN, type Translations } from "@/core/i18n/locales";
import { useLocalSettings } from "@/core/settings";
import {
  useAppearance,
  type CornerScale,
  type Density,
  type MaterialIntensity,
  type MaterialTheme,
} from "@/hooks/use-appearance";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

function useLanguageOptions(): { value: Locale; label: string }[] {
  return SUPPORTED_LOCALES.map((value) => ({
    value,
    label: TRANSLATIONS_BY_LOCALE[value].locale.localName,
  }));
}

const TRANSLATIONS_BY_LOCALE: Record<Locale, Translations> = {
  "en-US": enUS,
  "zh-CN": zhCN,
  "ja-JP": jaJP,
  "ko-KR": koKR,
};

function AppleIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d="M12 2c1.5 0 2.7.6 3.5 1.5.8.9 1.2 2 1.2 3.2 0 .3 0 .6-.1.9.3-.1.6-.1.9-.1 1.2 0 2.3.4 3.2 1.2.9.8 1.3 1.8 1.3 3 0 1.8-.9 3.4-2.7 4.8-.6.5-1.2.9-1.7 1.2-.3.2-.5.3-.7.5-.2.2-.3.4-.3.7 0 .3.1.5.3.7.2.2.5.4.8.6.5.3 1.1.7 1.7 1.2 1.2 1 2.1 2 2.6 3.2.3.6.4 1.2.4 1.9 0 1.1-.4 2-1.2 2.7-.8.7-1.8 1-3 1-.8 0-1.5-.2-2.2-.5-.7-.3-1.3-.8-1.8-1.3-.3-.3-.5-.5-.7-.7-.2-.2-.4-.3-.6-.3-.2 0-.4.1-.6.3-.2.2-.5.5-.8.8-.6.6-1.2 1-1.9 1.3-.7.3-1.4.4-2.2.4-1.2 0-2.2-.4-3-1.1C4.4 20 4 19.1 4 18c0-.7.2-1.3.5-1.9.3-.6.8-1.2 1.4-1.7.6-.5 1.1-.9 1.6-1.2.3-.2.5-.4.7-.6.2-.2.3-.4.3-.7 0-.3-.1-.5-.3-.7-.2-.2-.4-.3-.7-.5-.5-.3-1.1-.7-1.7-1.2C4 8.1 3.1 6.5 3.1 4.7c0-1.2.5-2.2 1.3-3C5.2 1 6.3.6 7.5.6c.3 0 .6 0 .9.1-.1-.3-.1-.6-.1-.9" />
    </svg>
  );
}

export default function AppearanceSettingsPage() {
  const { t, locale, changeLocale } = useI18n();
  const { theme, setTheme, systemTheme } = useTheme();
  const currentTheme = (theme ?? "system") as
    | "system"
    | "light"
    | "dark"
    | "apple";
  const [settings, setSetting] = useLocalSettings();
  const {
    cornerScale,
    density,
    materialIntensity,
    materialTheme,
    setCornerScale,
    setDensity,
    setMaterialIntensity,
    setMaterialTheme,
  } = useAppearance();
  const materialIntensityOptions = [
    {
      value: "crystal",
      label: t.settings.appearance.materialIntensityCrystal,
      description: t.settings.appearance.materialIntensityCrystalDescription,
    },
    {
      value: "clear",
      label: t.settings.appearance.materialIntensityClear,
      description: t.settings.appearance.materialIntensityClearDescription,
    },
    {
      value: "balanced",
      label: t.settings.appearance.materialIntensityBalanced,
      description: t.settings.appearance.materialIntensityBalancedDescription,
    },
    {
      value: "deep",
      label: t.settings.appearance.materialIntensityDeep,
      description: t.settings.appearance.materialIntensityDeepDescription,
    },
    {
      value: "frosted",
      label: t.settings.appearance.materialIntensityFrosted,
      description: t.settings.appearance.materialIntensityFrostedDescription,
    },
  ] satisfies AppearanceStepOption<MaterialIntensity>[];

  const themeOptions = useMemo(
    () => [
      {
        id: "system",
        label: t.settings.appearance.system,
        description: t.settings.appearance.systemDescription,
        icon: MonitorSmartphoneIcon,
      },
      {
        id: "light",
        label: t.settings.appearance.light,
        description: t.settings.appearance.lightDescription,
        icon: SunIcon,
      },
      {
        id: "dark",
        label: t.settings.appearance.dark,
        description: t.settings.appearance.darkDescription,
        icon: MoonIcon,
      },
      {
        id: "apple",
        label: t.settings.appearance.apple,
        description: t.settings.appearance.appleDescription,
        icon: AppleIcon,
      },
    ],
    [
      t.settings.appearance.dark,
      t.settings.appearance.darkDescription,
      t.settings.appearance.light,
      t.settings.appearance.lightDescription,
      t.settings.appearance.system,
      t.settings.appearance.systemDescription,
      t.settings.appearance.apple,
      t.settings.appearance.appleDescription,
    ],
  );

  return (
    <div className="space-y-8">
      <SettingsSection
        title={t.settings.appearance.themeTitle}
        description={t.settings.appearance.themeDescription}
      >
        <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
          {themeOptions.map((option) => (
            <ThemePreviewCard
              key={option.id}
              icon={option.icon}
              label={option.label}
              description={option.description}
              active={currentTheme === option.id}
              mode={option.id as "system" | "light" | "dark" | "apple"}
              systemTheme={systemTheme}
              onSelect={(value) => setTheme(value)}
            />
          ))}
        </div>
      </SettingsSection>

      <Separator />

      <SettingsSection
        title={t.settings.appearance.materialTitle}
        description={t.settings.appearance.materialDescription}
      >
        <div className="space-y-3">
          <SegmentedControl<MaterialTheme>
            aria-label={t.settings.appearance.materialTitle}
            value={materialTheme}
            onChange={setMaterialTheme}
            fullWidth
            options={[
              {
                value: "standard",
                label: t.settings.appearance.materialStandard,
                preview: t.settings.appearance.materialStandardDescription,
              },
              {
                value: "liquid",
                label: t.settings.appearance.materialLiquid,
                preview: t.settings.appearance.materialLiquidDescription,
                icon: <SparklesIcon className="size-3.5" />,
              },
            ]}
          />
          <div className="grid gap-3 md:grid-cols-2">
            <MaterialPreviewCard
              active={materialTheme === "standard"}
              tone="standard"
              label={t.settings.appearance.materialStandard}
            />
            <MaterialPreviewCard
              active={materialTheme === "liquid"}
              tone="liquid"
              intensity={materialIntensity}
              label={t.settings.appearance.materialLiquid}
            />
          </div>
          {materialTheme === "liquid" && (
            <AppearanceStepSlider<MaterialIntensity>
              value={materialIntensity}
              onChange={setMaterialIntensity}
              label={t.settings.appearance.materialIntensityTitle}
              options={materialIntensityOptions}
            />
          )}
        </div>
      </SettingsSection>

      <Separator />

      <SettingsSection
        title={t.settings.appearance.languageTitle}
        description={t.settings.appearance.languageDescription}
      >
        <Select
          value={locale}
          onValueChange={(value) => {
            if (isLocale(value)) {
              changeLocale(value);
            }
          }}
        >
          <SelectTrigger
            aria-label={t.settings.appearance.languageTitle}
            className="w-full sm:w-[220px]"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {useLanguageOptions().map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </SettingsSection>

      <Separator />

      <SettingsSection
        title={t.settings.appearance.chatFontSizeTitle}
        description={t.settings.appearance.chatFontSizeDescription}
      >
        <Select
          value={settings.display.chat_font_size}
          onValueChange={(value) => {
            if (value === "small" || value === "medium" || value === "large") {
              setSetting("display", { chat_font_size: value });
            }
          }}
        >
          <SelectTrigger
            aria-label={t.settings.appearance.chatFontSizeTitle}
            className="w-full sm:w-[220px] max-w-full"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="small">
              {t.settings.appearance.chatFontSizeSmall}
            </SelectItem>
            <SelectItem value="medium">
              {t.settings.appearance.chatFontSizeMedium}
            </SelectItem>
            <SelectItem value="large">
              {t.settings.appearance.chatFontSizeLarge}
            </SelectItem>
          </SelectContent>
        </Select>
      </SettingsSection>

      <Separator />

      <SettingsSection
        title={t.settings.appearance.cornerRadiusTitle}
        description={t.settings.appearance.cornerRadiusDescription}
      >
        <AppearanceStepSlider<CornerScale>
          label={t.settings.appearance.cornerRadiusTitle}
          value={cornerScale}
          onChange={setCornerScale}
          showHeader={false}
          options={[
            {
              value: 0.5,
              label: t.settings.appearance.cornerCrisp,
              preview: "0.25rem",
            },
            {
              value: 0.75,
              label: t.settings.appearance.cornerSoft,
              preview: "0.375rem",
            },
            {
              value: 1,
              label: t.settings.appearance.cornerDefault,
              preview: "0.5rem",
            },
            {
              value: 1.25,
              label: t.settings.appearance.cornerRound,
              preview: "0.625rem",
            },
            {
              value: 1.5,
              label: t.settings.appearance.cornerPill,
              preview: "0.75rem",
            },
          ]}
        />
      </SettingsSection>

      <Separator />

      <SettingsSection
        title={t.settings.appearance.uiDensityTitle}
        description={t.settings.appearance.uiDensityDescription}
      >
        <AppearanceStepSlider<Density>
          label={t.settings.appearance.uiDensityTitle}
          value={density}
          onChange={setDensity}
          showHeader={false}
          options={[
            {
              value: "relaxed",
              label: t.settings.appearance.densityRelaxed,
              preview: "16px",
            },
            {
              value: "comfortable",
              label: t.settings.appearance.densityComfortable,
              preview: "15px",
            },
            {
              value: "compact",
              label: t.settings.appearance.densityCompact,
              preview: "14px",
            },
            {
              value: "dense",
              label: t.settings.appearance.densityDense,
              preview: "13px",
            },
            {
              value: "ultradense",
              label: t.settings.appearance.densityUltraDense,
              preview: "12.5px",
            },
          ]}
        />
      </SettingsSection>
    </div>
  );
}

type AppearanceStepValue = string | number;

type AppearanceStepOption<TValue extends AppearanceStepValue> = {
  value: TValue;
  label: string;
  description?: string;
  preview?: string;
};

function AppearanceStepSlider<TValue extends AppearanceStepValue>({
  label,
  onChange,
  options,
  showHeader = true,
  value,
}: {
  label: string;
  onChange: (value: TValue) => void;
  options: AppearanceStepOption<TValue>[];
  showHeader?: boolean;
  value: TValue;
}) {
  const activeIndex = Math.max(
    0,
    options.findIndex((option) => option.value === value),
  );
  const fallbackOption: AppearanceStepOption<TValue> = {
    value,
    label,
    description: "",
  };
  const active = options[activeIndex] ?? options[0] ?? fallbackOption;
  const activeDetail = active.description ?? active.preview ?? "";
  const progress =
    options.length > 1 ? (activeIndex / (options.length - 1)) * 100 : 0;
  const trackRef = useRef<HTMLDivElement>(null);
  const updateFromIndex = useCallback(
    (index: number) => {
      const next = options[index];
      if (next) onChange(next.value);
    },
    [onChange, options],
  );
  const updateFromInputValue = (rawValue: string) => {
    updateFromIndex(Number(rawValue));
  };
  const updateFromPointer = useCallback(
    (event: PointerEvent<HTMLDivElement>) => {
      const track = trackRef.current;
      if (!track || options.length < 1) return;

      const rect = track.getBoundingClientRect();
      const ratio = Math.min(
        1,
        Math.max(0, (event.clientX - rect.left) / rect.width),
      );
      updateFromIndex(Math.round(ratio * (options.length - 1)));
    },
    [options, updateFromIndex],
  );

  return (
    <div className="rounded-lg border bg-muted/20 px-4 py-3">
      {showHeader ? (
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <div className="text-sm font-medium">{label}</div>
            {activeDetail ? (
              <div className="mt-1 text-xs text-muted-foreground">
                {activeDetail}
              </div>
            ) : null}
          </div>
          <div className="rounded-full border bg-background/75 px-2.5 py-1 text-xs font-medium shadow-[var(--shadow-xs)]">
            <span>{active.label}</span>
            {active.preview ? (
              <span className="ml-1 text-muted-foreground">
                {active.preview}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
      <div
        className="relative px-1"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          updateFromPointer(event);
        }}
        onPointerMove={(event) => {
          if (event.buttons === 1) updateFromPointer(event);
        }}
        ref={trackRef}
      >
        <input
          aria-label={label}
          className="octo-appearance-step-slider"
          aria-valuetext={[active.label, activeDetail]
            .filter(Boolean)
            .join(": ")}
          max={options.length - 1}
          min={0}
          onChange={(event) => updateFromInputValue(event.currentTarget.value)}
          onInput={(event) => updateFromInputValue(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === "Home") {
              event.preventDefault();
              updateFromIndex(0);
            }
            if (event.key === "End") {
              event.preventDefault();
              updateFromIndex(options.length - 1);
            }
            if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
              event.preventDefault();
              updateFromIndex(Math.max(0, activeIndex - 1));
            }
            if (event.key === "ArrowRight" || event.key === "ArrowUp") {
              event.preventDefault();
              updateFromIndex(Math.min(options.length - 1, activeIndex + 1));
            }
          }}
          step={1}
          style={{
            background: `linear-gradient(90deg, color-mix(in oklch, var(--primary) 72%, white 18%) 0 ${progress}%, color-mix(in oklch, var(--muted) 72%, transparent) ${progress}% 100%)`,
          }}
          type="range"
          value={activeIndex}
        />
        <div className="pointer-events-none absolute inset-x-1 top-1/2 flex -translate-y-1/2 justify-between">
          {options.map((option, index) => (
            <span
              aria-hidden="true"
              className={cn(
                "size-2.5 rounded-full border border-background shadow-[var(--shadow-xs)]",
                index <= activeIndex ? "bg-primary" : "bg-muted-foreground/30",
              )}
              key={option.value}
            />
          ))}
        </div>
      </div>
      <div
        className="mt-2 grid gap-1 text-xs"
        style={{
          gridTemplateColumns: `repeat(${options.length}, minmax(0, 1fr))`,
        }}
      >
        {options.map((option, index) => (
          <button
            aria-pressed={index === activeIndex}
            className={cn(
              "min-w-0 rounded-md px-1 py-1 text-center leading-none transition-colors",
              index === activeIndex
                ? "bg-primary/12 text-primary"
                : "text-muted-foreground hover:bg-muted/55 hover:text-foreground",
            )}
            key={option.value}
            onClick={() => updateFromIndex(index)}
            type="button"
          >
            <span className="block truncate">{option.label}</span>
            {option.preview ? (
              <span className="mt-0.5 block truncate text-xs font-normal text-muted-foreground">
                {option.preview}
              </span>
            ) : null}
          </button>
        ))}
      </div>
    </div>
  );
}

function MaterialPreviewCard({
  active,
  intensity = "balanced",
  tone,
  label,
}: {
  active: boolean;
  intensity?: MaterialIntensity;
  tone: "standard" | "liquid";
  label: string;
}) {
  const liquidPreviewClass = {
    crystal:
      "bg-[radial-gradient(circle_at_15%_10%,color-mix(in_oklch,var(--primary)_12%,transparent),transparent_42%),linear-gradient(135deg,color-mix(in_oklch,var(--card)_34%,transparent),color-mix(in_oklch,var(--background)_58%,transparent))] shadow-[var(--shadow-xs)] backdrop-blur-md",
    clear:
      "bg-[radial-gradient(circle_at_15%_10%,color-mix(in_oklch,var(--primary)_16%,transparent),transparent_42%),linear-gradient(135deg,color-mix(in_oklch,var(--card)_46%,transparent),color-mix(in_oklch,var(--background)_68%,transparent))] shadow-[var(--shadow-xs)] backdrop-blur-lg",
    balanced:
      "bg-[radial-gradient(circle_at_15%_10%,color-mix(in_oklch,var(--primary)_22%,transparent),transparent_42%),linear-gradient(135deg,color-mix(in_oklch,var(--card)_52%,transparent),color-mix(in_oklch,var(--background)_72%,transparent))] shadow-[var(--shadow-xs)] backdrop-blur-xl",
    deep: "bg-[radial-gradient(circle_at_15%_10%,color-mix(in_oklch,var(--primary)_28%,transparent),transparent_42%),linear-gradient(135deg,color-mix(in_oklch,var(--card)_62%,transparent),color-mix(in_oklch,var(--background)_78%,transparent))] shadow-[var(--shadow-sm)] backdrop-blur-2xl",
    frosted:
      "bg-[radial-gradient(circle_at_15%_10%,color-mix(in_oklch,var(--primary)_18%,transparent),transparent_42%),linear-gradient(135deg,color-mix(in_oklch,var(--card)_78%,transparent),color-mix(in_oklch,var(--background)_88%,transparent))] shadow-[var(--shadow-sm)] backdrop-blur-3xl",
  } satisfies Record<MaterialIntensity, string>;
  const liquidTone = tone === "liquid" && liquidPreviewClass[intensity];

  return (
    <div
      className={cn(
        "relative h-28 overflow-hidden rounded-lg border p-3 transition-all",
        active
          ? "border-primary ring-primary/25 ring-2"
          : "border-border-default",
        liquidTone || "bg-card",
      )}
    >
      <div
        className={cn(
          "absolute inset-x-5 top-4 h-10 rounded-lg border",
          tone === "liquid"
            ? cn(
                "border-white/35 bg-white/22 shadow-[inset_0_1px_0_rgba(255,255,255,0.55),0_14px_30px_rgba(15,23,42,0.13)] backdrop-blur-2xl",
                intensity === "crystal" && "bg-white/10 backdrop-blur-md",
                intensity === "clear" && "bg-white/16 backdrop-blur-lg",
                intensity === "deep" &&
                  "bg-white/28 shadow-[inset_0_1px_0_rgba(255,255,255,0.64),0_18px_36px_rgba(15,23,42,0.18)] backdrop-blur-3xl",
                intensity === "frosted" &&
                  "bg-white/42 shadow-[inset_0_1px_0_rgba(255,255,255,0.72),0_20px_42px_rgba(15,23,42,0.2)] backdrop-blur-3xl",
              )
            : "border-border-default bg-muted/60",
        )}
      />
      <div
        className={cn(
          "absolute bottom-4 left-5 right-20 h-8 rounded-lg border",
          tone === "liquid"
            ? cn(
                "border-white/30 bg-white/18 shadow-[inset_0_1px_0_rgba(255,255,255,0.45)] backdrop-blur-xl",
                intensity === "crystal" && "bg-white/8 backdrop-blur-sm",
                intensity === "clear" && "bg-white/12 backdrop-blur-md",
                intensity === "deep" && "bg-white/24 backdrop-blur-2xl",
                intensity === "frosted" && "bg-white/36 backdrop-blur-3xl",
              )
            : "border-border-default bg-muted/45",
        )}
      />
      <div
        className={cn(
          "absolute bottom-4 right-5 h-8 w-10 rounded-lg",
          tone === "liquid"
            ? "bg-primary/30 shadow-[0_10px_26px_color-mix(in_oklch,var(--primary)_28%,transparent)]"
            : "bg-primary/18",
        )}
      />
      <div className="relative text-xs font-medium">{label}</div>
    </div>
  );
}

function ThemePreviewCard({
  icon: Icon,
  label,
  description,
  active,
  mode,
  systemTheme,
  onSelect,
}: {
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  label: string;
  description: string;
  active: boolean;
  mode: "system" | "light" | "dark" | "apple";
  systemTheme?: string;
  onSelect: (mode: "system" | "light" | "dark" | "apple") => void;
}) {
  const previewMode =
    mode === "system" ? (systemTheme === "dark" ? "dark" : "light") : mode;
  const previewIsDark = previewMode === "dark";
  const previewIsApple = previewMode === "apple";
  const previewFrameClass =
    previewMode === "dark"
      ? "border-neutral-800 bg-neutral-950 text-neutral-200"
      : previewMode === "apple"
        ? "border-border-strong bg-[linear-gradient(145deg,#f8fbff_0%,#ffffff_42%,#f3f6fb_100%)] text-foreground shadow-[var(--shadow-xs)]"
        : "border-border bg-white text-foreground";
  const previewTopbarClass =
    previewMode === "dark"
      ? "border-white/10 bg-neutral-900"
      : previewMode === "apple"
        ? "border-white/70 bg-white/58 backdrop-blur-xl"
        : "border-border bg-muted";
  const previewSidebarClass =
    previewMode === "dark"
      ? "border-white/10 bg-[linear-gradient(180deg,#171717_0%,#101010_100%)]"
      : previewMode === "apple"
        ? "border-white/70 bg-[radial-gradient(circle_at_0%_4%,rgba(147,197,253,0.22),transparent_42%),radial-gradient(circle_at_100%_100%,rgba(251,207,232,0.18),transparent_44%),rgba(255,255,255,0.62)] shadow-[inset_-1px_0_0_rgba(255,255,255,0.65),0_10px_30px_rgba(15,23,42,0.08)] backdrop-blur-xl"
        : "border-border bg-muted/85";
  const previewCanvasClass =
    previewMode === "dark"
      ? "bg-neutral-900"
      : previewMode === "apple"
        ? "bg-[radial-gradient(circle_at_22%_0%,rgba(96,165,250,0.12),transparent_38%),linear-gradient(180deg,rgba(255,255,255,0.92),rgba(248,250,252,0.72))]"
        : "bg-white";
  const activeDotClass =
    previewMode === "dark"
      ? "bg-emerald-400"
      : previewMode === "apple"
        ? "bg-blue-500"
        : "bg-emerald-500";
  return (
    <button
      type="button"
      onClick={() => onSelect(mode)}
      aria-pressed={active}
      className={cn(
        "group flex h-full flex-col gap-3 rounded-lg border p-4 text-left transition-all",
        active
          ? "border-primary ring-primary/30 shadow-[var(--shadow-xs)] ring-2"
          : "hover:border-border hover:shadow-[var(--shadow-xs)]",
      )}
    >
      <div className="flex items-start gap-3">
        <div className="bg-muted rounded-lg p-2">
          <Icon className="size-4" />
        </div>
        <div className="space-y-1">
          <div className="text-sm leading-none font-semibold">{label}</div>
          <p className="text-muted-foreground text-xs leading-snug">
            {description}
          </p>
        </div>
      </div>
      <div
        className={cn(
          "relative overflow-hidden rounded-lg border text-xs transition-colors",
          previewFrameClass,
        )}
      >
        <div
          className={cn(
            "flex items-center gap-2 border-b px-3 py-2",
            previewTopbarClass,
          )}
        >
          <div className={cn("h-2 w-2 rounded-full", activeDotClass)} />
          <div className="h-2 w-10 rounded-md bg-current/20" />
          <div className="h-2 w-6 rounded-md bg-current/15" />
        </div>
        <div className="grid grid-cols-[32px_minmax(0,1fr)]">
          <div
            className={cn(
              "flex min-h-[142px] flex-col gap-2 border-r px-2 py-3",
              previewSidebarClass,
            )}
          >
            <div className={cn("h-3 w-3 rounded-full", activeDotClass)} />
            <div className="h-2 w-4 rounded-full bg-current/18" />
            <div className="h-2 w-4 rounded-full bg-current/14" />
            <div className="mt-auto h-2 w-4 rounded-full bg-current/12" />
          </div>
          <div
            className={cn(
              "grid grid-cols-[1fr_92px] gap-3 px-3 py-3",
              previewCanvasClass,
            )}
          >
            <div className="space-y-2">
              <div className="h-3 w-3/4 rounded-md bg-current/15" />
              <div className="h-3 w-1/2 rounded-md bg-current/10" />
              <div
                className={cn(
                  "h-[88px] rounded-lg border bg-current/5",
                  previewIsApple
                    ? "border-white/70 bg-white/42 shadow-[0_8px_22px_rgba(15,23,42,0.08)] backdrop-blur-xl"
                    : previewIsDark
                      ? "border-white/10 bg-white/[0.03]"
                      : "border-border bg-white",
                )}
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <div
                  className={cn(
                    "h-8 w-8 rounded-lg",
                    previewIsApple
                      ? "rounded-lg bg-blue-500/10"
                      : "bg-current/10",
                  )}
                />
                <div className="space-y-2">
                  <div className="h-2 w-10 rounded-md bg-current/15" />
                  <div className="h-2 w-7 rounded-md bg-current/10" />
                </div>
              </div>
              <div
                className={cn(
                  "flex flex-col gap-1 rounded-lg border border-dashed p-2",
                  previewIsApple
                    ? "rounded-lg border-blue-200/50 bg-white/34"
                    : previewIsDark
                      ? "border-white/10"
                      : "border-border",
                )}
              >
                <div className="h-2 w-3/5 rounded-md bg-current/15" />
                <div className="h-2 w-2/5 rounded-md bg-current/10" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </button>
  );
}
