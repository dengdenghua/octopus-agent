import { useCallback, useEffect, useRef, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";

interface IframeRendererProps {
  url: string;
  width: number | "100%";
  onFallbackNeeded: () => void;
}

export function IframeRenderer({
  url,
  width,
  onFallbackNeeded,
}: IframeRendererProps) {
  const { t } = useI18n();
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [loading, setLoading] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const loadingRef = useRef(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const isDesktop = typeof window !== "undefined" && window.__OCTOPUS_DESKTOP__;

  const handleLoad = useCallback(() => {
    loadingRef.current = false;
    setLoading(false);
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
  }, []);

  // React to URL changes via useEffect instead of render-phase side effects
  useEffect(() => {
    if (!url) return;

    loadingRef.current = true;
    setLoading(true);
    setBlocked(false);

    // Timeout-based detection: if iframe doesn't load in 5s, assume blocked
    timeoutRef.current = setTimeout(() => {
      if (loadingRef.current) {
        if (isDesktop) {
          onFallbackNeeded();
        } else {
          setBlocked(true);
          setLoading(false);
          loadingRef.current = false;
        }
      }
    }, 5000);

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [url, isDesktop, onFallbackNeeded]);

  if (!url) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground text-sm">
        {t.browser.startBrowsingHint}
      </div>
    );
  }

  if (blocked) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground text-sm">
        <p>{t.browser.embeddedBlocked}</p>
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary underline underline-offset-4 hover:text-primary/80"
        >
          {t.browser.openExternal}
        </a>
      </div>
    );
  }

  return (
    <div className="relative h-full w-full">
      {loading && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/50">
          <div className="size-6 animate-spin rounded-lg border-2 border-primary border-t-transparent" />
        </div>
      )}
      <iframe
        ref={iframeRef}
        src={url}
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox"
        style={{
          width: typeof width === "number" ? `${width}px` : width,
          height: "100%",
        }}
        className="mx-auto border-0"
        onLoad={handleLoad}
        title="Embedded Browser"
      />
    </div>
  );
}
