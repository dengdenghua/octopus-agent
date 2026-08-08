import {
  MonitorSmartphoneIcon,
  MoonIcon,
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
import { Separator } from "@/components/ui/separator";
import { isLocale, SUPPORTED_LOCALES, type Locale } from "@/core/i18n";
import { useI18n } from "@/core/i18n/hooks";
import { enUS, jaJP, koKR, zhCN, type Translations } from "@/core/i18n/locales";
import { useLocalSettings } from "@/core/settings";
import {
  useAppearance,
  type CornerScale,
  type Density,
  type Palette,
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

export default function AppearanceSettingsPage() {
  const { t, locale, changeLocale } = useI18n();
  const { theme, setTheme, systemTheme } = useTheme();
  const currentTheme = (theme ?? "system") as
    | "system"
    | "light"
    | "dark";
  const [settings, setSetting] = useLocalSettings();
  const {
    cornerScale,
    density,
    palette,
    customColor,
    setCornerScale,
    setDensity,
    setPalette,
    setCustomColor,
  } = useAppearance();

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
    ],
    [
      t.settings.appearance.dark,
      t.settings.appearance.darkDescription,
      t.settings.appearance.light,
      t.settings.appearance.lightDescription,
      t.settings.appearance.system,
      t.settings.appearance.systemDescription,
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
              mode={option.id as "system" | "light" | "dark"}
              systemTheme={systemTheme}
              onSelect={(value) => setTheme(value)}
            />
          ))}
        </div>
      </SettingsSection>

      <Separator />

      <SettingsSection
        title={t.settings.appearance.paletteTitle}
        description={t.settings.appearance.paletteDescription}
      >
        <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 md:grid-cols-4">
          <PalettePreviewCard
            label={t.settings.appearance.paletteRose}
            description={t.settings.appearance.paletteRoseDescription}
            active={palette === "rouge"}
            swatch="#e85d75"
            onSelect={() => setPalette("rouge")}
          />
          <PalettePreviewCard
            label={t.settings.appearance.paletteSteel}
            description={t.settings.appearance.paletteSteelDescription}
            active={palette === "steel"}
            swatch="#3e6fd8"
            onSelect={() => setPalette("steel")}
          />
          <PalettePreviewCard
            label={t.settings.appearance.paletteEmerald}
            description={t.settings.appearance.paletteEmeraldDescription}
            active={palette === "emerald"}
            swatch="#1a7a56"
            onSelect={() => setPalette("emerald")}
          />
          <PalettePreviewCard
            label={t.settings.appearance.paletteViolet}
            description={t.settings.appearance.paletteVioletDescription}
            active={palette === "violet"}
            swatch="#6a5fb4"
            onSelect={() => setPalette("violet")}
          />
          <PalettePreviewCard
            label={t.settings.appearance.paletteAmber}
            description={t.settings.appearance.paletteAmberDescription}
            active={palette === "amber"}
            swatch="#8a5a1c"
            onSelect={() => setPalette("amber")}
          />
          <PalettePreviewCard
            label={t.settings.appearance.paletteTeal}
            description={t.settings.appearance.paletteTealDescription}
            active={palette === "teal"}
            swatch="#1a7a80"
            onSelect={() => setPalette("teal")}
          />
          <PalettePreviewCard
            label={t.settings.appearance.paletteCustom}
            description={t.settings.appearance.paletteCustomDescription}
            active={palette === "custom"}
            swatch={customColor}
            onSelect={() => setCustomColor(customColor)}
          />
        </div>
        <div className="mt-3 flex items-center gap-3 rounded-lg border bg-muted/20 px-4 py-3">
          <input
            type="color"
            aria-label={t.settings.appearance.paletteCustom}
            className="h-9 w-12 cursor-pointer rounded border bg-transparent p-0.5"
            value={customColor}
            onChange={(event) => setCustomColor(event.target.value)}
          />
          <span className="font-mono text-sm uppercase">{customColor}</span>
          <span className="text-xs text-muted-foreground">
            {t.settings.appearance.paletteCustomHint}
          </span>
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

function PalettePreviewCard({
  label,
  description,
  active,
  swatch,
  onSelect,
}: {
  label: string;
  description: string;
  active: boolean;
  swatch: string;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      className={cn(
        "group flex h-full flex-col gap-3 rounded-lg border p-4 text-left transition-all",
        active
          ? "border-primary ring-primary/30 shadow-[var(--shadow-xs)] ring-2"
          : "hover:border-border hover:shadow-[var(--shadow-xs)]",
      )}
    >
      <div className="flex items-center gap-3">
        <span
          className="size-8 rounded-full border border-black/5 shadow-inner"
          style={{ backgroundColor: swatch }}
        />
        <div className="space-y-1">
          <div className="text-sm leading-none font-semibold">{label}</div>
          <p className="text-muted-foreground text-xs leading-snug">
            {description}
          </p>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <span className="h-20 rounded-md border" style={{ backgroundColor: swatch }} />
        <span className="h-20 rounded-md border bg-white" />
        <span className="h-20 rounded-md border bg-muted" />
      </div>
    </button>
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
  mode: "system" | "light" | "dark";
  systemTheme?: string;
  onSelect: (mode: "system" | "light" | "dark") => void;
}) {
  const previewMode =
    mode === "system" ? (systemTheme === "dark" ? "dark" : "light") : mode;
  const previewIsDark = previewMode === "dark";
  const previewFrameClass =
    previewMode === "dark"
      ? "border-neutral-800 bg-neutral-950 text-neutral-200"
      : "border-border bg-white text-foreground";
  const previewTopbarClass =
    previewMode === "dark"
      ? "border-white/10 bg-neutral-900"
      : "border-border bg-muted";
  const previewSidebarClass =
    previewMode === "dark"
      ? "border-white/10 bg-[linear-gradient(180deg,#171717_0%,#101010_100%)]"
      : "border-border bg-muted/85";
  const previewCanvasClass =
    previewMode === "dark"
      ? "bg-neutral-900"
      : "bg-white";
  const activeDotClass =
    previewMode === "dark"
      ? "bg-success"
      : "bg-success";
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
                  previewIsDark
                    ? "border-white/10 bg-white/[0.03]"
                    : "border-border bg-white",
                )}
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <div className="h-8 w-8 rounded-lg bg-current/10" />
                <div className="space-y-2">
                  <div className="h-2 w-10 rounded-md bg-current/15" />
                  <div className="h-2 w-7 rounded-md bg-current/10" />
                </div>
              </div>
              <div
                className={cn(
                  "flex flex-col gap-1 rounded-lg border border-dashed p-2",
                  previewIsDark
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
