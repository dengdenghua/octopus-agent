type MermaidRunOptions = {
  nodes?: ArrayLike<Element>;
};

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const mermaid = {
  initialize(_config?: Record<string, unknown>) {
    return undefined;
  },
  async run(options?: MermaidRunOptions) {
    const nodes = Array.from(options?.nodes ?? []);
    for (const node of nodes) {
      const source = node.textContent?.trim() ?? "";
      node.innerHTML = `<pre class="overflow-x-auto rounded-md border border-border bg-muted/40 p-3 text-xs">${escapeHtml(source)}</pre>`;
    }
  },
  async render(id: string, source: string) {
    return {
      bindFunctions: undefined,
      diagramType: "text",
      svg: `<svg id="${escapeHtml(id)}" xmlns="http://www.w3.org/2000/svg" width="640" height="160" role="img" aria-label="Diagram source"><foreignObject width="100%" height="100%"><pre xmlns="http://www.w3.org/1999/xhtml" style="font:12px monospace;white-space:pre-wrap;margin:0;padding:12px;border:1px solid #ddd;border-radius:8px;background:#f8fafc;color:#334155;">${escapeHtml(source)}</pre></foreignObject></svg>`,
    };
  },
};

export default mermaid;
