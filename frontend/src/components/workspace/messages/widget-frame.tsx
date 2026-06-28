import { useEffect, useId, useState } from "react";

/**
 * Render agent-emitted interactive HTML/JS inline, in a tightly sandboxed
 * iframe — the octopus equivalent of Claude's `show_widget`.
 *
 * SECURITY: ``sandbox="allow-scripts"`` ONLY. That gives the iframe a unique
 * *null* origin, so the widget's scripts run but cannot read the app's DOM,
 * cookies, localStorage, or make same-origin requests. NEVER add
 * ``allow-same-origin`` here — combined with ``allow-scripts`` it would let
 * untrusted agent code escape into the app origin. No top-navigation / popups.
 *
 * The content arrives as a fenced ``` ```widget ``` code block, so it bypasses
 * the message-level DOMPurify (which would strip its <script>) and is rendered
 * here in the sandbox instead.
 */
export function WidgetFrame({ code, className }: { code: string; className?: string }) {
  const frameId = useId();
  const [height, setHeight] = useState(320);

  const srcDoc = `<!doctype html><html><head><meta charset="utf-8">
<style>
  :root { color-scheme: light dark; }
  html, body { margin: 0; padding: 0; background: transparent;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
</style></head><body>
${code}
<script>
  (function () {
    function report() {
      try {
        var h = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
        parent.postMessage({ __octopusWidget: ${JSON.stringify(frameId)}, height: h }, "*");
      } catch (e) { /* sandboxed; ignore */ }
    }
    window.addEventListener("load", report);
    setTimeout(report, 60);
    try { new ResizeObserver(report).observe(document.body); } catch (e) { /* older engines */ }
  })();
</script>
</body></html>`;

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const data = event.data as { __octopusWidget?: string; height?: number } | null;
      if (
        data &&
        typeof data === "object" &&
        data.__octopusWidget === frameId &&
        typeof data.height === "number"
      ) {
        setHeight(Math.min(Math.max(data.height + 8, 80), 2000));
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [frameId]);

  return (
    <iframe
      title="interactive widget"
      sandbox="allow-scripts"
      referrerPolicy="no-referrer"
      srcDoc={srcDoc}
      className={className}
      style={{
        width: "100%",
        height,
        border: "1px solid var(--border, rgba(0,0,0,0.1))",
        borderRadius: "0.75rem",
        background: "transparent",
      }}
    />
  );
}
