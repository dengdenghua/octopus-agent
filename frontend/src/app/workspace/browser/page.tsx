import {
  GlobeIcon,
  LaptopIcon,
  SmartphoneIcon,
  TabletIcon,
  XIcon,
} from "lucide-react";
import {
  BrowserPanel,
  BrowserProvider,
  useBrowserPanel,
  type DevicePreset,
} from "@/components/workspace/embedded-browser";
import { CapabilityQualityStrip } from "@/components/workspace/capability-quality-strip";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";

interface DeviceSpec {
  width: number;
  height: number;
  label: string;
  Icon: typeof LaptopIcon;
}

const DEVICE_SPECS: Record<DevicePreset, DeviceSpec> = {
  desktop: { width: 0, height: 0, label: "Desktop", Icon: LaptopIcon },
  tablet: { width: 768, height: 1024, label: "Tablet", Icon: TabletIcon },
  mobile: { width: 375, height: 812, label: "Mobile", Icon: SmartphoneIcon },
};
const PRESET_ORDER: DevicePreset[] = ["desktop", "tablet", "mobile"];

/* Implementation note. */
function BrowserPageBody() {
  const { t } = useI18n();
  const { mode, setMode, toggle } = useBrowserPanel();
  const spec = DEVICE_SPECS[mode];
  const isPhone = mode !== "desktop";

  const devicePicker = (
    <div className="flex items-center rounded-lg border border-border/60 bg-muted/35 p-0.5 shadow-sm">
      {PRESET_ORDER.map((preset) => {
        const Icon = DEVICE_SPECS[preset].Icon;
        const active = mode === preset;
        return (
          <button
            key={preset}
            onClick={() => setMode(preset)}
            className={
              active
                ? "rounded-md bg-background px-2 py-1 shadow-sm"
                : "rounded-md px-2 py-1 hover:bg-background/70"
            }
            title={
              preset === "desktop"
                ? t.browser.deviceDesktop
                : preset === "tablet"
                  ? t.browser.deviceTablet
                  : t.browser.deviceMobile
            }
          >
            <Icon
              className={
                active
                  ? "size-3.5 text-foreground"
                  : "size-3.5 text-muted-foreground"
              }
            />
          </button>
        );
      })}
    </div>
  );

  return (
    <div className="flex h-full w-full flex-col overflow-hidden p-3">
      {/* Implementation note. */}
      <div className="mx-auto mb-2 flex w-full max-w-6xl flex-col gap-2 md:flex-row md:items-center md:justify-between">
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="text-[11px] text-muted-foreground">
            {isPhone
              ? t.browser.viewportHint(spec.label, spec.width, spec.height)
              : ""}
          </div>
          <CapabilityQualityStrip
            surface="browser"
            includeBrowserDesktop
            className="rounded-lg px-3 py-2"
          />
        </div>
        <div className="flex shrink-0 items-center justify-end gap-1">
          {devicePicker}
          <button
            onClick={toggle}
            className="rounded-lg border border-transparent p-1.5 hover:border-border/60 hover:bg-muted"
            aria-label="关闭浏览器预览"
          >
            <XIcon className="size-4 text-muted-foreground" />
          </button>
        </div>
      </div>

      {/* Implementation note. */}
      <div className="flex flex-1 items-center justify-center overflow-hidden">
        <div
          className={
            isPhone
              ? "flex flex-col overflow-hidden rounded-[1.75rem] border-[6px] border-foreground/80 bg-background shadow-2xl"
              : "flex h-full w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-border/60 bg-card shadow-sm"
          }
          style={
            isPhone
              ? {
                  // Implementation note.
                  // Implementation note.
                  // Implementation note.
                  // Implementation note.
                  // Implementation note.
                  height: "100%",
                  maxWidth: "100%",
                  aspectRatio: `${spec.width} / ${spec.height}`,
                  minWidth: 0,
                  minHeight: 0,
                  flexShrink: 0,
                }
              : undefined
          }
        >
          <div className="flex h-11 items-center gap-2.5 border-b border-border/60 bg-muted/20 px-3">
            <span className="flex size-7 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <GlobeIcon className="size-4" />
            </span>
            <h1 className="text-sm font-semibold">{t.sidebar.browser}</h1>
          </div>
          <div className="flex-1 overflow-hidden bg-muted/15 p-2.5">
            <BrowserPanel />
          </div>
        </div>
      </div>
    </div>
  );
}

export default function BrowserPage() {
  return (
    <BrowserProvider>
      <WorkspaceContainer>
        <WorkspaceHeader />
        <WorkspaceBody className="overflow-hidden">
          <BrowserPageBody />
        </WorkspaceBody>
      </WorkspaceContainer>
    </BrowserProvider>
  );
}
