import { MonitorSmartphoneIcon, MoonIcon, SunIcon } from "lucide-react";
import { useTheme } from "next-themes";
import { useMemo, type ComponentType, type SVGProps } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Separator } from "@/components/ui/separator";
import { isLocale, type Locale } from "@/core/i18n";
import { useI18n } from "@/core/i18n/hooks";
import { useLocalSettings } from "@/core/settings";
import {
  useAppearance,
  type CornerScale,
  type Density,
} from "@/hooks/use-appearance";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

function useLanguageOptions(
  t: ReturnType<typeof useI18n>["t"],
): { value: Locale; label: string }[] {
  return [
    { value: "en-US", label: t.settings.appearance.languageEnglish },
    { value: "zh-CN", label: t.settings.appearance.languageChineseSimplified },
  ];
}

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
  const { cornerScale, density, setCornerScale, setDensity } = useAppearance();

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
          <SelectTrigger className="w-[220px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {useLanguageOptions(t).map((item) => (
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
          <SelectTrigger className="w-[220px]">
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
        <SegmentedControl<CornerScale>
          aria-label={t.settings.appearance.cornerRadiusTitle}
          value={cornerScale}
          onChange={setCornerScale}
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
        <SegmentedControl<Density>
          aria-label={t.settings.appearance.uiDensityTitle}
          value={density}
          onChange={setDensity}
          options={[
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
          ]}
        />
      </SettingsSection>
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
  return (
    <button
      type="button"
      onClick={() => onSelect(mode)}
      className={cn(
        "group flex h-full flex-col gap-3 rounded-lg border p-4 text-left transition-all",
        active
          ? "border-primary ring-primary/30 shadow-sm ring-2"
          : "hover:border-border hover:shadow-sm",
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
          previewMode === "dark"
            ? "border-neutral-800 bg-neutral-900 text-neutral-200"
            : previewMode === "apple"
              ? "border-slate-200/80 bg-white text-slate-800 shadow-sm"
              : "border-slate-200 bg-white text-slate-900",
        )}
      >
        <div
          className={cn(
            "flex items-center gap-2 border-b px-3 py-2",
            previewMode === "apple"
              ? "border-slate-100 bg-slate-50/50"
              : "border-border/50",
          )}
        >
          <div
            className={cn(
              "h-2 w-2 rounded-full",
              previewMode === "dark"
                ? "bg-emerald-400"
                : previewMode === "apple"
                  ? "bg-blue-500"
                  : "bg-emerald-500",
            )}
          />
          <div className="h-2 w-10 rounded-md bg-current/20" />
          <div className="h-2 w-6 rounded-md bg-current/15" />
        </div>
        <div className="grid grid-cols-[1fr_240px] gap-3 px-3 py-3">
          <div className="space-y-2">
            <div className="h-3 w-3/4 rounded-md bg-current/15" />
            <div className="h-3 w-1/2 rounded-md bg-current/10" />
            <div
              className={cn(
                "h-[90px] rounded-xl border bg-current/5",
                previewMode === "apple"
                  ? "border-slate-200 shadow-sm"
                  : "border-current/10",
              )}
            />
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <div
                className={cn(
                  "h-8 w-8 rounded-lg",
                  previewMode === "apple"
                    ? "bg-blue-500/10 rounded-xl"
                    : "bg-current/10",
                )}
              />
              <div className="space-y-2">
                <div className="h-2 w-14 rounded-md bg-current/15" />
                <div className="h-2 w-10 rounded-md bg-current/10" />
              </div>
            </div>
            <div
              className={cn(
                "flex flex-col gap-1 rounded-lg border border-dashed p-2",
                previewMode === "apple"
                  ? "border-slate-300/40 rounded-xl"
                  : "border-current/15",
              )}
            >
              <div className="h-2 w-3/5 rounded-md bg-current/15" />
              <div className="h-2 w-2/5 rounded-md bg-current/10" />
            </div>
          </div>
        </div>
      </div>
    </button>
  );
}
