// Thin wrapper that reuses the full browser automation panel so the settings
// dialog shows the same UI as the standalone /workspace/browser route.
// Previously this file hosted a trimmed 158-line re-implementation; keeping
// two parallel views led to drift, so they were consolidated.

import { BrowserPanel, BrowserProvider } from "@/components/workspace/embedded-browser";
import { useI18n } from "@/core/i18n/hooks";

export default function BrowserSettingsPage() {
  const { t } = useI18n();

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold">{t.browserSettings.title}</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {t.browserSettings.description}
        </p>
      </div>
      <BrowserProvider>
        <div className="h-[360px] rounded-lg border bg-muted/10 p-2">
          <BrowserPanel />
        </div>
      </BrowserProvider>
    </div>
  );
}
