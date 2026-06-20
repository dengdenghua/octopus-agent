import {
  BookOpenIcon,
  EditIcon,
  FileTextIcon,
  FolderIcon,
  Loader2Icon,
  MaximizeIcon,
  MinimizeIcon,
  RefreshCwIcon,
  SaveIcon,
  SparklesIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import DOMPurify from "dompurify";
import { toast } from "sonner";

import { swallow } from "@/core/utils/log";
import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import { joinPath } from "@/lib/path-utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface WikiStatus {
  exists: boolean;
  status: "not_generated" | "current" | "outdated";
  generated_at?: string;
  updated_at?: string;
  files_analyzed?: number;
  modules?: string[];
  languages?: string[];
  generated_files?: string[];
  changes_pending?: { modified: number; added: number; removed: number } | null;
}

interface WikiDocEntry {
  path: string;
  name: string;
  size: number;
}

interface WikiProgress {
  total_steps: number;
  completed_steps: number;
  current_step: string;
  progress_pct: number;
  elapsed_seconds: number;
  errors: string[];
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

// Implementation note.
// the per-project wiki ( <workDir>/.octopus-wiki/ ). When no workDir
// passes through (legacy callers) the suffix is empty and the backend
// falls back to Octopus self-docs (docs/auto/) — kept for back-compat.
const rootQ = (root?: string): string =>
  root && root.trim() ? `&root=${encodeURIComponent(root.trim())}` : "";
const rootQ1 = (root?: string): string =>
  root && root.trim() ? `?root=${encodeURIComponent(root.trim())}` : "";

const api = {
  async status(root?: string): Promise<WikiStatus> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/wiki/status${rootQ1(root)}`,
      { headers: authHeaders() },
    );
    if (!res.ok) {
      throw new Error(`Failed to fetch wiki status: HTTP ${res.status}`);
    }
    return res.json();
  },
  async docs(lang = "en", root?: string): Promise<WikiDocEntry[]> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/wiki/docs?lang=${lang}${rootQ(root)}`,
      { headers: authHeaders() },
    );
    if (!res.ok) return [];
    const data = await res.json();
    return data.docs ?? [];
  },
  async readDoc(path: string, root?: string): Promise<string> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/wiki/docs/${encodeURIComponent(path)}${rootQ1(root)}`,
      { headers: authHeaders() },
    );
    if (!res.ok) throw new Error("Failed to read document");
    const data = await res.json();
    return data.content;
  },
  async writeDoc(path: string, content: string): Promise<void> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/wiki/docs/${encodeURIComponent(path)}`,
      {
        method: "PUT",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({ content }),
      },
    );
    if (!res.ok) throw new Error("Failed to save document");
  },
  async generate(root?: string): Promise<void> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/wiki/generate${rootQ1(root)}`,
      { method: "POST", headers: authHeaders() },
    );
    if (!res.ok) throw new Error("Failed to start generation");
  },
  async update(
    root?: string,
  ): Promise<{ status: string; updated_files?: number }> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/wiki/update${rootQ1(root)}`,
      { method: "POST", headers: authHeaders() },
    );
    if (!res.ok) throw new Error("Failed to update wiki");
    return res.json();
  },
  async progress(): Promise<WikiProgress> {
    const res = await fetch(`${getBackendBaseURL()}/api/wiki/progress`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error("Failed to fetch progress");
    return res.json();
  },
  // Per-project autosync flag · only meaningful when the wiki is
  // running in per-project mode (root passed). Backend rejects
  // missing root with 400.
  async getSettings(
    root: string,
  ): Promise<{ autosync: boolean; watching?: boolean }> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/wiki/settings${rootQ1(root)}`,
      { headers: authHeaders() },
    );
    if (!res.ok) return { autosync: false, watching: false };
    return res.json();
  },
  async setSettings(
    root: string,
    autosync: boolean,
  ): Promise<{
    autosync: boolean;
    watching?: boolean;
    watcher_error?: string;
  }> {
    const res = await fetch(
      `${getBackendBaseURL()}/api/wiki/settings${rootQ1(root)}`,
      {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({ autosync }),
      },
    );
    if (!res.ok) throw new Error("Failed to save autosync setting");
    return res.json();
  },
};

// ---------------------------------------------------------------------------
// Fallback: legacy static file loading (for projects without generated wiki)
// ---------------------------------------------------------------------------

const LEGACY_CANDIDATES = [
  "CLAUDE.md",
  "README.md",
  "README_zh.md",
  "docs/ARCHITECTURE.md",
  "docs/CONFIGURATION.md",
  "docs/API.md",
  "CONTRIBUTING.md",
  "CHANGELOG.md",
];

async function fetchLegacyDocs(workDir: string) {
  const results = await Promise.all(
    LEGACY_CANDIDATES.map(async (name) => {
      const fullPath = joinPath(workDir, name);
      try {
        const res = await fetch(
          `${getBackendBaseURL()}/api/fs/read?path=${encodeURIComponent(fullPath)}&max_lines=5000`,
          { headers: authHeaders() },
        );
        if (!res.ok) return null;
        const data = await res.json();
        if (data.binary) return null;
        return { path: name, name, content: data.content as string };
      } catch (e) {
        swallow(e);
        return null;
      }
    }),
  );
  return results.filter(Boolean) as Array<{
    path: string;
    name: string;
    content: string;
  }>;
}

// ---------------------------------------------------------------------------
// Markdown renderer (kept lightweight)
// ---------------------------------------------------------------------------

// HTML-escape untrusted text before applying markdown substitutions so any
// raw <script>/<img onerror=...>/etc. becomes inert entities.
function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Only allow http(s)/relative/anchor hrefs — blocks javascript:, data:, etc.
function safeHref(raw: string): string {
  const trimmed = raw.trim();
  if (/^(https?:\/\/|\/|#|mailto:)/i.test(trimmed)) return trimmed;
  return "#";
}

function simpleMarkdownToHtml(md: string): string {
  // Two-pass strategy:
  //
  //   1. Apply markdown rules to the RAW input (no blanket escape up
  //      front). Regex substitutions that embed user-provided text
  //      escape INDIVIDUAL capture groups at the substitution site so
  //      code spans / link labels / list items stay safe.
  //   2. Sanitize the final HTML through DOMPurify with a restrictive
  //      allowlist. Raw HTML in README-style docs (``<p align="center">``,
  //      ``<img src="...">``, badges) survives · ``<script>`` / ``onerror=``
  //      / ``javascript:`` URLs are stripped.
  //
  // Wiki docs are editable via ``PUT /api/wiki/docs/{path}`` by any
  // authenticated user, so treating content as untrusted is mandatory.
  // Pre-fix the blanket ``escapeHtml(md)`` up front also ate legitimate
  // README formatting — rendering ``<p align="center">`` as literal text
  // instead of centering the content. DOMPurify fixes both.
  let out = md;

  // Mermaid blocks → render-ready div (processed by useEffect).
  // Body is escaped now; mermaid.run() reads textContent, so entities are
  // decoded back to the original diagram source before rendering.
  out = out.replace(
    /```mermaid\n([\s\S]*?)```/g,
    (_m, body: string) =>
      `<div class="mermaid my-3 overflow-x-auto rounded border bg-muted/30 p-2 text-[11px]">${escapeHtml(body)}</div>`,
  );
  // Other code blocks · body escaped · class survives.
  out = out.replace(
    /```(\w*)\n([\s\S]*?)```/g,
    (_m, _lang: string, body: string) =>
      `<pre class="bg-muted rounded-lg p-2 overflow-x-auto text-[11px]"><code>${escapeHtml(body)}</code></pre>`,
  );
  // Inline code · body escaped.
  out = out.replace(
    /`([^`]+)`/g,
    (_m, body: string) =>
      `<code class="bg-muted rounded px-1 text-[11px]">${escapeHtml(body)}</code>`,
  );

  // Markdown structural transforms · these operate on lines that can
  // contain already-valid HTML from the raw README; we keep the HTML
  // intact and only wrap the markdown syntax with additional tags.
  out = out
    .replace(/^#### (.+)$/gm, '<h4 class="text-xs font-bold mt-3 mb-1">$1</h4>')
    .replace(/^### (.+)$/gm, '<h3 class="text-sm font-bold mt-4 mb-1">$1</h3>')
    .replace(
      /^## (.+)$/gm,
      '<h2 class="text-sm font-bold mt-4 mb-2 pb-1 border-b">$1</h2>',
    )
    .replace(/^# (.+)$/gm, '<h1 class="text-base font-bold mt-4 mb-2">$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>");

  // Markdown links · keep the safeHref contract; escape label to stop
  // ``[<script>alert(1)</script>](url)`` style smuggling.
  out = out.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    (_m, label: string, href: string) =>
      `<a href="${escapeHtml(safeHref(href))}" class="text-blue-500 hover:underline" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`,
  );

  out = out
    .replace(/^- (.+)$/gm, '<li class="ml-3">$1</li>')
    .replace(/^\d+\. (.+)$/gm, '<li class="ml-3 list-decimal">$1</li>')
    .replace(/^---$/gm, '<hr class="my-3 border-border">')
    .replace(/\n\n/g, "</p><p>")
    .replace(/\n/g, "<br>");

  return out;
}

/**
 * DOMPurify allowlist for sanitized wiki / README HTML. Allows the
 * tags a typical project README needs for layout (centering, badges,
 * images, anchor links) while dropping ``<script>``, event handlers,
 * and ``javascript:`` URLs.
 *
 * Extracted so the full allowlist lives next to one place · if a
 * future README legitimately needs ``<details>`` / ``<summary>`` /
 * etc., add them here explicitly rather than broadening elsewhere.
 */
const DOMPURIFY_CONFIG = {
  ALLOWED_TAGS: [
    "a",
    "b",
    "br",
    "code",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
    "details",
    "summary",
    "blockquote",
  ],
  ALLOWED_ATTR: [
    "align",
    "alt",
    "class",
    "href",
    "id",
    "rel",
    "src",
    "srcset",
    "target",
    "title",
    "width",
    "height",
    "colspan",
    "rowspan",
  ],
  // http / https / relative / anchor only
  ALLOWED_URI_REGEXP:
    /^(?:(?:https?|mailto):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i,
};

function WikiMarkdown({ content }: { content: string }) {
  // Sanitize through DOMPurify after the markdown transform · allowlist
  // in DOMPURIFY_CONFIG keeps README-style HTML (centering / badges /
  // images) while stripping XSS vectors.
  const html = useMemo(() => {
    const raw = `<p>${simpleMarkdownToHtml(content)}</p>`;
    return DOMPurify.sanitize(raw, DOMPURIFY_CONFIG);
  }, [content]);
  const ref = useRef<HTMLDivElement>(null);

  // Render Mermaid diagrams after mount. Loaded from the local bundle
  // (dynamic import = lazy chunk) instead of a CDN <script>, so a CDN
  // compromise cannot inject arbitrary JS into the app.
  useEffect(() => {
    if (!ref.current) return;
    const mermaidDivs =
      ref.current.querySelectorAll<HTMLDivElement>(".mermaid");
    if (mermaidDivs.length === 0) return;

    let cancelled = false;
    void import("mermaid").then((mod) => {
      if (cancelled) return;
      const mermaid = mod.default;
      mermaid.initialize({
        startOnLoad: false,
        theme: "neutral",
        fontSize: 12,
      });
      void mermaid.run({ nodes: Array.from(mermaidDivs) });
    });
    return () => {
      cancelled = true;
    };
  }, [html]);

  return <div ref={ref} dangerouslySetInnerHTML={{ __html: html }} />;
}

// ---------------------------------------------------------------------------
// Doc tree navigation
// ---------------------------------------------------------------------------

function DocTree({
  docs,
  activeDoc,
  onSelect,
}: {
  docs: WikiDocEntry[];
  activeDoc: string | null;
  onSelect: (path: string) => void;
}) {
  const { t } = useI18n();
  // Build tree structure from flat paths
  const tree = useMemo(() => {
    const root: Record<string, unknown> = {};
    for (const doc of docs) {
      const parts = doc.path.split("/");
      let node: Record<string, unknown> = root;
      for (let i = 0; i < parts.length - 1; i++) {
        node[parts[i]!] = (node[parts[i]!] as Record<string, unknown>) || {};
        node = node[parts[i]!] as Record<string, unknown>;
      }
      node[parts[parts.length - 1]!] = doc;
    }
    return root;
  }, [docs]);

  const renderNode = (obj: Record<string, unknown>, prefix = "", depth = 0) => {
    const entries = Object.entries(obj).sort(([a], [b]) => a.localeCompare(b));
    return entries.map(([key, value]) => {
      if (typeof value === "object" && value !== null && "path" in value) {
        // Leaf: document file
        const doc = value as WikiDocEntry;
        const isActive = doc.path === activeDoc;
        return (
          <button
            key={doc.path}
            onClick={() => onSelect(doc.path)}
            className={cn(
              "flex w-full items-center gap-1.5 rounded px-2 py-1 text-left text-[11px] transition-colors",
              isActive
                ? "bg-primary/10 text-primary font-medium"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
            style={{ paddingLeft: `${depth * 12 + 8}px` }}
          >
            <FileTextIcon className="size-3 shrink-0" />
            <span className="truncate">
              {key.replace(/^_/, "").replace(/\.md$/, "") || t.wiki.overview}
            </span>
          </button>
        );
      }
      // Branch: directory
      return (
        <div key={prefix + key}>
          <div
            className="text-muted-foreground flex items-center gap-1 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider"
            style={{ paddingLeft: `${depth * 12 + 8}px` }}
          >
            <FolderIcon className="size-3" />
            {key}
          </div>
          {renderNode(
            value as Record<string, unknown>,
            prefix + key + "/",
            depth + 1,
          )}
        </div>
      );
    });
  };

  return <div className="space-y-0.5 py-1">{renderNode(tree)}</div>;
}

// ---------------------------------------------------------------------------
// Progress bar
// ---------------------------------------------------------------------------

function GenerationProgress({ progress }: { progress: WikiProgress }) {
  const { t } = useI18n();
  return (
    <div className="space-y-2 px-3 py-4">
      <div className="flex items-center gap-2">
        <Loader2Icon className="text-primary size-4 animate-spin" />
        <span className="text-xs font-medium">{t.wiki.generatingWiki}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-lg bg-muted">
        <div
          className="bg-primary h-full rounded-lg transition-all duration-500"
          style={{ width: `${progress.progress_pct}%` }}
        />
      </div>
      <div className="text-muted-foreground flex justify-between text-[10px]">
        <span>{progress.current_step}</span>
        <span>{Math.round(progress.progress_pct)}%</span>
      </div>
      <div className="text-muted-foreground/60 text-[10px]">
        {progress.completed_steps}/{progress.total_steps} {t.wiki.steps} ·{" "}
        {Math.round(progress.elapsed_seconds)}s {t.wiki.elapsed}
      </div>
      {progress.errors.length > 0 && (
        <div className="mt-1 text-[10px] text-amber-500">
          {t.wiki.warnings(progress.errors.length)}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main WikiPanel component
// ---------------------------------------------------------------------------

export function WikiPanel({
  workDir,
  className,
  active = true,
}: {
  workDir: string;
  className?: string;
  /**
   * Whether the panel is currently visible. When false we skip the
   * /api/wiki/status + /api/wiki/docs fetches entirely — the Code-mode
   * page mounts this with `forceMount` for tab state preservation, so
   * without this gate every Code session pays the ~tens-of-seconds wiki
   * API cost even when the tab is never opened. Defaults to true to
   * preserve pre-existing behaviour for any caller that forgets to pass it.
   */
  active?: boolean;
}) {
  const { t } = useI18n();
  const [wikiStatus, setWikiStatus] = useState<WikiStatus | null>(null);
  const [docs, setDocs] = useState<WikiDocEntry[]>([]);
  const [activeDocPath, setActiveDocPath] = useState<string | null>(null);
  const [docContent, setDocContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState<WikiProgress | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [saving, setSaving] = useState(false);
  // ``/api/wiki/*`` isn't implemented on every backend deployment.
  // When ``/api/wiki/status`` 404s on mount we flip this flag so the
  // "Generate Wiki" / "Update" CTAs disappear · rather than letting
  // the user click through to a 404 + ``toastGenerateFailed`` loop.
  // Legacy static docs (fetched via ``/api/fs/read``) continue to
  // render as before.
  const [wikiBackendAvailable, setWikiBackendAvailable] = useState(true);

  // Legacy fallback state
  const [legacyDocs, setLegacyDocs] = useState<
    Array<{ path: string; name: string; content: string }>
  >([]);
  const [useLegacy, setUseLegacy] = useState(false);
  // Per-project autosync flag. Source of truth is the backend
  // (``<workDir>/.octopus-wiki/settings.json``); we hydrate from
  // ``/api/wiki/status`` (it includes ``autosync``) and round-trip
  // changes via ``/api/wiki/settings``.
  //
  // ``watching`` is distinct from ``autosync``: the persisted flag
  // says "user wants this on", the runtime flag says "the file
  // watcher is actually attached right now". They diverge when the
  // backend restarts before the user revisits the wiki tab, or when
  // ``watchdog`` isn't installed (autosync persists, watcher fails
  // to start). UI shows a green dot only when watching is live.
  const [autosync, setAutosync] = useState(false);
  const [watching, setWatching] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadedOnce = useRef(false);

  // ── Load wiki status ──
  const loadStatus = useCallback(async () => {
    // Only show full loading spinner on first load
    if (!loadedOnce.current) setLoading(true);
    try {
      const status = await api.status(workDir);
      setWikiStatus(status);
      // Backend echoes the autosync flag on status responses (per-project
      // mode only). Falls back to false when running against legacy
      // Octopus-self-docs mode (no root passed).
      if (typeof (status as { autosync?: boolean }).autosync === "boolean") {
        setAutosync(Boolean((status as { autosync?: boolean }).autosync));
      }
      // Watching state lives in /api/wiki/settings · the status
      // endpoint doesn't return it. Pull it explicitly when we
      // have a workDir AND the wiki has been generated (no point
      // before · no settings file yet).
      if (workDir && status.exists) {
        try {
          const s = await api.getSettings(workDir);
          setWatching(Boolean(s.watching));
        } catch (e) {
          swallow(e);
        }
      }

      if (status.exists) {
        const lang = status.languages?.[0] || "en";
        const docList = await api.docs(lang, workDir);
        setDocs(docList);
        setUseLegacy(false);
        if (docList.length > 0 && !activeDocPath) {
          setActiveDocPath(docList[0]!.path);
        }
      } else {
        // Only fetch legacy docs on first load (avoid repeated 8 parallel requests)
        if (!loadedOnce.current) {
          const legacy = await fetchLegacyDocs(workDir);
          setLegacyDocs(legacy);
          setUseLegacy(true);
          if (legacy.length > 0 && !activeDocPath) {
            setActiveDocPath(legacy[0]!.path);
            setDocContent(legacy[0]!.content);
          }
        }
      }
    } catch (err) {
      swallow(err);
      // Distinguish "backend has no /api/wiki/* at all" (404) from a
      // transient failure (timeout / 5xx). 404 flips the flag so the
      // Generate / Update CTAs disappear · any other error leaves the
      // backend considered available · user retry will re-probe.
      const msg = err instanceof Error ? err.message : String(err);
      if (/\b404\b|not found/i.test(msg)) {
        setWikiBackendAvailable(false);
      }
      if (!loadedOnce.current) {
        const legacy = await fetchLegacyDocs(workDir);
        setLegacyDocs(legacy);
        setUseLegacy(true);
        if (legacy.length > 0 && !activeDocPath) {
          setActiveDocPath(legacy[0]!.path);
          setDocContent(legacy[0]!.content);
        }
      }
    } finally {
      setLoading(false);
      loadedOnce.current = true;
    }
  }, [workDir, activeDocPath]);

  useEffect(() => {
    // Only fetch wiki data when the panel is actually visible. Prevents
    // the hidden-but-forceMount'd instance in Code mode from hammering
    // /api/wiki/status + /api/wiki/docs during workspace load.
    if (!active) return;
    void loadStatus();
  }, [loadStatus, active]);

  // ── Load document content ──
  const loadDoc = useCallback(
    async (path: string) => {
      setActiveDocPath(path);
      setEditing(false);

      if (useLegacy) {
        const doc = legacyDocs.find((d) => d.path === path);
        setDocContent(doc?.content ?? null);
        return;
      }

      try {
        const content = await api.readDoc(path, workDir);
        setDocContent(content);
      } catch (e) {
        swallow(e);
        setDocContent(t.wiki.failedToLoad);
      }
    },
    [useLegacy, legacyDocs, workDir, t.wiki.failedToLoad],
  );

  // ── Generate wiki ──
  const handleGenerate = useCallback(async () => {
    // Confirm with user — generation consumes LLM tokens
    const confirmed = window.confirm(
      t.wiki.generateConfirmTitle + "\n\n" + t.wiki.generateConfirmBody,
    );
    if (!confirmed) return;

    setGenerating(true);
    try {
      await api.generate(workDir);
      toast.success(t.wiki.generateStarted);

      // Per-project mode is synchronous on the backend (it returns
      // after generation completes), so we don't need to poll progress.
      // Skip the interval when workDir is set.
      if (workDir) {
        setGenerating(false);
        toast.success(t.wiki.generateComplete);
        void loadStatus();
        return;
      }
      // Legacy Octopus-self-docs mode · subprocess + polling.
      pollRef.current = setInterval(async () => {
        try {
          const p = await api.progress();
          setProgress(p);
          if (p.progress_pct >= 100 || p.current_step === "Complete") {
            if (pollRef.current) clearInterval(pollRef.current);
            setGenerating(false);
            setProgress(null);
            toast.success(t.wiki.generateComplete);
            void loadStatus();
          }
        } catch (e) {
          swallow(e);
        }
      }, 2000);
    } catch {
      toast.error(t.wiki.generateFailed);
      setGenerating(false);
    }
  }, [loadStatus, t, workDir]);

  // ── Update wiki ──
  const handleUpdate = useCallback(async () => {
    const confirmed = window.confirm(
      t.wiki.updateConfirmTitle + "\n\n" + t.wiki.updateConfirmBody,
    );
    if (!confirmed) return;

    try {
      const result = await api.update(workDir);
      if (result.status === "up_to_date") {
        toast.info(t.wiki.updateUpToDate);
      } else {
        toast.success(t.wiki.updatedFiles(result.updated_files || 0));
        void loadStatus();
      }
    } catch {
      toast.error(t.wiki.updateFailed);
    }
  }, [loadStatus, t, workDir]);

  // ── Toggle autosync ──
  // Persists the per-project flag and (when turned on) immediately
  // kicks off a regen so the user can see it took effect. Off-state
  // is just the persist · no destructive cleanup of existing wiki.
  const handleToggleAutosync = useCallback(async () => {
    if (!workDir) return;
    const next = !autosync;
    setAutosync(next);
    try {
      const r = await api.setSettings(workDir, next);
      setWatching(Boolean(r.watching));
      if (next) {
        if (r.watcher_error) {
          // Persisted but watcher couldn't start (e.g. watchdog
          // missing). Fail loud so the user knows the toggle is
          // half-on rather than silently misleading them.
          toast.error(r.watcher_error);
        } else {
          toast.success(t.wiki.autosyncOn);
        }
      } else {
        toast.info(t.wiki.autosyncOff);
      }
    } catch {
      // Roll back on failure so the toggle reflects backend truth.
      setAutosync(!next);
      toast.error(t.wiki.autosyncSaveFailed);
    }
  }, [autosync, workDir, t]);

  // ── Save edit ──
  const handleSave = useCallback(async () => {
    if (!activeDocPath) return;
    setSaving(true);
    try {
      await api.writeDoc(activeDocPath, editContent);
      setDocContent(editContent);
      setEditing(false);
      toast.success(t.wiki.documentSaved);
    } catch {
      toast.error(t.wiki.documentSaveFailed);
    } finally {
      setSaving(false);
    }
  }, [activeDocPath, editContent, t]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // ── Rendering ──

  if (loading) {
    return (
      <div
        className={cn(
          "flex flex-col items-center justify-center gap-2 py-12",
          className,
        )}
      >
        <Loader2Icon className="text-muted-foreground size-5 animate-spin" />
        <span className="text-muted-foreground text-xs">
          {t.wiki.loadingWiki}
        </span>
      </div>
    );
  }

  // Generation in progress
  if (generating && progress) {
    return (
      <div className={cn("flex flex-col", className)}>
        <GenerationProgress progress={progress} />
      </div>
    );
  }

  // No wiki and no legacy docs — show generate button (if backend
  // supports generation) or an explanation (if it doesn't).
  if (!wikiStatus?.exists && legacyDocs.length === 0) {
    return (
      <div
        className={cn(
          "flex flex-col items-center justify-center gap-3 px-4 py-12",
          className,
        )}
      >
        <div className="bg-muted/40 rounded-lg p-4">
          <BookOpenIcon className="text-muted-foreground/40 size-8" />
        </div>
        <p className="text-muted-foreground text-sm font-medium">
          {t.wiki.noWikiYet}
        </p>
        <p className="text-muted-foreground/60 text-center text-xs leading-relaxed whitespace-pre-line">
          {t.wiki.noWikiDesc}
        </p>
        {wikiBackendAvailable ? (
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="bg-primary text-primary-foreground mt-2 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors hover:opacity-90 disabled:opacity-50"
          >
            <SparklesIcon className="size-3.5" />
            {t.wiki.generateWiki}
          </button>
        ) : (
          <p className="text-muted-foreground/50 max-w-xs text-center text-[11px] italic leading-relaxed">
            {t.wiki.backendUnavailable}
          </p>
        )}
        <button
          onClick={() => void loadStatus()}
          className="text-muted-foreground hover:text-foreground flex items-center gap-1 text-xs"
        >
          <RefreshCwIcon className="size-3" />
          {t.wiki.refresh}
        </button>
      </div>
    );
  }

  // Has wiki or legacy docs — show content
  const _showDocs = useLegacy ? legacyDocs : docs;

  const wikiContent = (
    <div
      className={cn(
        "flex flex-col",
        expanded
          ? "fixed inset-4 z-[200] rounded-lg border bg-background shadow-2xl"
          : "h-full",
        !expanded && className,
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/60 px-3 py-2">
        <div className="flex items-center gap-1.5">
          <div className="flex size-5 items-center justify-center rounded-lg bg-primary/10">
            <BookOpenIcon className="text-primary size-3" />
          </div>
          <span className="text-xs font-semibold">
            {useLegacy ? t.wiki.docs : t.wiki.repoWiki}
          </span>
          {useLegacy && !wikiStatus?.exists && (
            <span className="text-muted-foreground/50 text-[9px]">
              {t.wiki.static}
            </span>
          )}
          {wikiStatus?.status === "outdated" && (
            <span className="rounded bg-amber-100 px-1 py-0.5 text-[9px] text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
              {wikiStatus.changes_pending
                ? t.wiki.filesChanged(
                    (wikiStatus.changes_pending.modified || 0) +
                      (wikiStatus.changes_pending.added || 0),
                  )
                : t.wiki.outdated}
            </span>
          )}
        </div>
        <div className="flex items-center gap-0.5">
          {wikiBackendAvailable &&
            !useLegacy &&
            wikiStatus?.status === "outdated" && (
              <button
                onClick={handleUpdate}
                className="text-primary hover:text-primary/80 p-1 rounded-lg hover:bg-primary/10 text-[10px] font-medium transition-colors"
                title={t.wiki.update}
              >
                {t.wiki.update}
              </button>
            )}
          {wikiBackendAvailable && !wikiStatus?.exists && (
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="text-primary hover:text-primary/80 p-1 rounded-lg hover:bg-primary/10 transition-colors"
              title={t.wiki.generateWiki}
            >
              <SparklesIcon className="size-3.5" />
            </button>
          )}
          {/* Autosync toggle · only shows when running per-project
              (workDir set) AND wiki has been generated at least once.
              Off state is intentionally low-contrast so it doesn't
              compete with the primary actions.
              Green pulsing dot = watcher is *actually* attached
              (autosync persisted AND watchdog running) · distinct
              from "saved but no watcher" (e.g. watchdog uninstalled
              or backend just restarted before re-arm). */}
          {wikiBackendAvailable && workDir && wikiStatus?.exists && (
            <button
              onClick={handleToggleAutosync}
              className={cn(
                "flex items-center gap-1 rounded-lg px-1.5 py-0.5 text-[10px] font-medium transition-colors",
                autosync
                  ? "bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30"
                  : "text-muted-foreground hover:bg-muted/40",
              )}
              title={
                autosync
                  ? watching
                    ? t.wiki.autosyncOnHint
                    : t.wiki.autosyncSavedNotWatching
                  : t.wiki.autosyncOffHint
              }
            >
              {autosync && (
                <span
                  className={cn(
                    "inline-block size-1.5 rounded-full",
                    watching ? "bg-emerald-400 animate-pulse" : "bg-amber-400",
                  )}
                />
              )}
              {autosync ? t.wiki.autosyncOnLabel : t.wiki.autosyncOffLabel}
            </button>
          )}
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-muted-foreground hover:text-foreground p-1 rounded-lg hover:bg-muted/60 transition-colors"
            title={expanded ? t.wiki.collapse : t.wiki.expand}
          >
            {expanded ? (
              <MinimizeIcon className="size-3" />
            ) : (
              <MaximizeIcon className="size-3" />
            )}
          </button>
          <button
            onClick={() => void loadStatus()}
            className="text-muted-foreground hover:text-foreground p-1 rounded-lg hover:bg-muted/60 transition-colors"
            title={t.wiki.refresh}
          >
            <RefreshCwIcon className="size-3" />
          </button>
        </div>
      </div>

      {/* Content area: vertical in sidebar, horizontal when expanded */}
      <div
        className={cn(
          "flex min-h-0 flex-1",
          expanded ? "flex-row" : "flex-col",
        )}
      >
        {/* Doc tree or list */}
        <div
          className={cn(
            "shrink-0 overflow-y-auto",
            expanded ? "w-56 border-r" : "border-b",
          )}
          style={expanded ? undefined : { maxHeight: "40%" }}
        >
          {useLegacy ? (
            // Legacy file list
            <div className="space-y-0.5 py-1">
              {legacyDocs.map((doc) => (
                <button
                  key={doc.path}
                  onClick={() => void loadDoc(doc.path)}
                  className={cn(
                    "flex w-full items-center gap-1.5 px-3 py-1 text-left text-[11px] transition-colors",
                    doc.path === activeDocPath
                      ? "bg-primary/10 text-primary font-medium"
                      : "text-muted-foreground hover:bg-muted",
                  )}
                >
                  <FileTextIcon className="size-3 shrink-0" />
                  <span className="truncate">{doc.name}</span>
                </button>
              ))}
            </div>
          ) : (
            <DocTree
              docs={docs}
              activeDoc={activeDocPath}
              onSelect={(p) => void loadDoc(p)}
            />
          )}
          {/* Status bar */}
          {!useLegacy && wikiStatus && (
            <div className="text-muted-foreground/60 flex items-center justify-between border-t px-3 py-1 text-[9px]">
              <span>
                {wikiStatus.files_analyzed ?? 0} {t.wiki.files}
              </span>
              <span>
                {wikiStatus.modules?.length ?? 0} {t.wiki.modules}
              </span>
            </div>
          )}
        </div>

        {/* Document content */}
        <div className="flex-1 overflow-y-auto">
          {docContent ? (
            editing ? (
              // Edit mode
              <div className="flex h-full flex-col">
                <div className="flex items-center justify-between border-b px-3 py-1.5">
                  <span className="text-[10px] font-medium text-amber-600">
                    {t.wiki.editing}
                  </span>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={handleSave}
                      disabled={saving}
                      className="text-primary flex items-center gap-0.5 text-[10px] font-medium"
                    >
                      {saving ? (
                        <Loader2Icon className="size-3 animate-spin" />
                      ) : (
                        <SaveIcon className="size-3" />
                      )}
                      {t.wiki.save}
                    </button>
                    <button
                      onClick={() => setEditing(false)}
                      className="text-muted-foreground hover:text-foreground"
                    >
                      <XIcon className="size-3" />
                    </button>
                  </div>
                </div>
                <textarea
                  value={editContent}
                  onChange={(e) => setEditContent(e.target.value)}
                  className="bg-background flex-1 resize-none p-3 font-mono text-[11px] leading-relaxed outline-none"
                  spellCheck={false}
                />
              </div>
            ) : (
              // Read mode
              <div className="relative">
                {!useLegacy && (
                  <button
                    onClick={() => {
                      setEditing(true);
                      setEditContent(docContent);
                    }}
                    className="text-muted-foreground hover:text-foreground absolute top-2 right-2 z-10 rounded p-1"
                    title={t.wiki.editDocument}
                  >
                    <EditIcon className="size-3" />
                  </button>
                )}
                <div className="px-3 py-3">
                  <div className="prose prose-sm dark:prose-invert max-w-none text-xs leading-relaxed">
                    <WikiMarkdown content={docContent} />
                  </div>
                </div>
              </div>
            )
          ) : (
            <div className="text-muted-foreground/50 py-8 text-center text-xs">
              {t.wiki.selectDocument}
            </div>
          )}
        </div>
      </div>
      {/* close content flex row/col */}
    </div>
  );

  // When expanded, also render a backdrop
  if (expanded) {
    return (
      <>
        <div
          className="fixed inset-0 z-[199] bg-black/50"
          onClick={() => setExpanded(false)}
        />
        {wikiContent}
      </>
    );
  }

  return wikiContent;
}
