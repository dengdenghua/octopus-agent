import { useEffect, useRef } from "react";
import { Streamdown } from "streamdown";

import type { StreamdownProps } from "streamdown";

export default Streamdown;
export type { StreamdownProps } from "streamdown";

// Map of English text/labels from streamdown's hard-coded UI to Chinese.
// streamdown doesn't expose i18n props, so we localize via a post-render
// DOM patch inside a wrapper. This is fragile but acceptable because
// (a) these labels are stable across patch versions and (b) if the
// library ever adds i18n support we can remove this wrapper entirely.
const TITLE_REPLACEMENTS: Record<string, string> = {
  "Copy table as markdown": "复制表格为 Markdown",
  "Copy table as csv": "复制表格为 CSV",
  "Download table": "下载表格",
  "Download file": "下载文件",
  "Download image": "下载图片",
};

const TEXT_REPLACEMENTS: Record<string, string> = {
  "Loading diagram...": "正在加载图表...",
  "Mermaid Error:": "Mermaid 错误：",
  "Show Code": "显示代码",
};

function localizeStreamdownDom(root: HTMLElement) {
  // Patch button titles (native tooltips)
  root.querySelectorAll<HTMLButtonElement>("button[title]").forEach((btn) => {
    const originalTitle = btn.getAttribute("title");
    if (originalTitle) {
      const newTitle = (TITLE_REPLACEMENTS as Record<string, string>)[originalTitle];
      if (newTitle) btn.setAttribute("title", newTitle);
    }
  });

  // Patch text nodes inside menu items and status spans
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
  const textNodes: Text[] = [];
  let currentNode: Node | null;
  while ((currentNode = walker.nextNode())) {
    textNodes.push(currentNode as Text);
  }
  for (const textNode of textNodes) {
    const text = textNode.textContent ?? "";
    const trimmed = text.trim();
    if (trimmed) {
      const replacement = (TEXT_REPLACEMENTS as Record<string, string>)[trimmed];
      if (replacement) {
        // Preserve surrounding whitespace
        const leading = text.startsWith(" ") ? " " : "";
        const trailing = text.endsWith(" ") ? " " : "";
        textNode.textContent = leading + replacement + trailing;
      }
    }
  }
}

/**
 * Wrapper around Streamdown that patches the library's hard-coded English
 * UI labels into Chinese after each render.
 */
export function LocalizedStreamdown(props: StreamdownProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Run once on mount / content change
    localizeStreamdownDom(container);

    // Also watch for async additions (e.g. mermaid finishes rendering,
    // streamed markdown arrives, copy/download dropdown opens)
    // Coalesce mutation bursts into one patch per frame: during streaming
    // every chunk mutates the subtree, and an unthrottled callback would
    // re-scan the whole container per token (and re-trigger itself).
    let raf = 0;
    const observer = new MutationObserver(() => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        localizeStreamdownDom(container);
      });
    });
    observer.observe(container, {
      childList: true,
      subtree: true,
      characterData: true,
    });
    return () => {
      observer.disconnect();
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div ref={containerRef} className="streamdown-localized">
      <Streamdown {...props} />
    </div>
  );
}
