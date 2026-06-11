import { useMemo } from "react";
import React from "react";
import { useI18n } from "@/core/i18n/hooks";

interface InfoRow {
  label: string;
  value: string;
}

export function BundleInfo() {
  const { t } = useI18n();
  const rows: InfoRow[] = useMemo(() => {
    const env = import.meta.env.MODE ?? "unknown";
    const viteVersion = import.meta.env.VITE_VERSION ?? __VITE_VERSION__;
    const reactVersion = React.version;
    const moduleCount =
      typeof import.meta.glob === "function"
        ? Object.keys(import.meta.glob("/src/**/*.{ts,tsx}")).length
        : "N/A";

    return [
      { label: t.bundleInfo.environment, value: env },
      { label: t.bundleInfo.vite, value: viteVersion },
      { label: t.bundleInfo.react, value: reactVersion },
      { label: t.bundleInfo.sourceModules, value: String(moduleCount) },
    ];
  }, [t]);

  return (
    <div className="mt-6 rounded-lg border p-4">
      <h3 className="text-sm font-semibold mb-3">{t.bundleInfo.title}</h3>
      <div className="grid grid-cols-2 gap-y-2 gap-x-4 text-sm">
        {rows.map((row) => (
          <div key={row.label} className="contents">
            <span className="text-muted-foreground">{row.label}</span>
            <span className="font-mono text-xs">{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* Vite injects __VITE_VERSION__ at build time — declare for TS */
declare const __VITE_VERSION__: string;
