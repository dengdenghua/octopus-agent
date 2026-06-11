import { GlobeIcon, LaptopIcon, SmartphoneIcon, TabletIcon, XIcon } from "lucide-react";
import {
  BrowserPanel,
  BrowserProvider,
  useBrowserPanel,
  type DevicePreset,
} from "@/components/workspace/embedded-browser";
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
    <div className="flex items-center rounded border bg-muted/40 p-0.5">
      {PRESET_ORDER.map((preset) => {
        const Icon = DEVICE_SPECS[preset].Icon;
        const active = mode === preset;
        return (
          <button
            key={preset}
            onClick={() => setMode(preset)}
            className={
              active
                ? "rounded bg-background px-1.5 py-1 shadow-sm"
                : "rounded px-1.5 py-1 hover:bg-background/60"
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
    <div className="flex h-full w-full flex-col overflow-hidden p-4">
      {/* Implementation note. */}
      <div className="mx-auto mb-3 flex w-full max-w-6xl items-center justify-between gap-3">
        <div className="text-[11px] text-muted-foreground">
          {isPhone
            ? t.browser.viewportHint(spec.label, spec.width, spec.height)
            : ""}
        </div>
        <div className="flex items-center gap-1">
          {devicePicker}
          <button onClick={toggle} className="rounded p-1 hover:bg-muted">
            <XIcon className="size-4 text-muted-foreground" />
          </button>
        </div>
      </div>

      {/* Implementation note. */}
      <div className="flex flex-1 items-center justify-center overflow-hidden">
        <div
          className={
            isPhone
              ? "workspace-panel flex flex-col overflow-hidden rounded-[2rem] border-[6px] border-foreground/80 bg-background shadow-2xl"
              : "workspace-panel flex h-full w-full max-w-6xl flex-col overflow-hidden rounded-[1.75rem]"
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
          <div className="flex items-center gap-3 border-b px-4 py-3">
            <GlobeIcon className="h-5 w-5 text-primary" />
            <h1 className="font-semibold">{t.sidebar.browser}</h1>
          </div>
          <div className="flex-1 overflow-hidden p-4">
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
