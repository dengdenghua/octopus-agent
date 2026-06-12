import type { FileHunk } from "@/core/realtime";

/**
 * Build a minimal unified-diff containing only the target hunk so the
 * server can reverse-apply just this one without touching its
 * siblings. We prefer the whole-file diff when supplied (server echoes
 * it alongside the hunks); otherwise synthesize one from the hunk body.
 *
 * Copied verbatim from the original page.tsx — keeping the same
 * shape so the round-trip semantics are identical.
 *
 * NOTE: this module once also exported a `FileChangeView` component (the
 * per-hunk accept/reject UI) and a `DecideHunkFn` type, but production
 * renders MessageOutputSummary, which imports only `singleHunkDiff` from
 * here. The component tree was orphaned (verified: zero external refs) and
 * removed; this helper is the only live export.
 */
export function singleHunkDiff(
  path: string,
  hunk: FileHunk,
  _wholeFileDiff: string | null,
): string {
  const header = `@@ -${hunk.oldStart},${hunk.oldLines} +${hunk.newStart},${hunk.newLines} @@`;
  const body = hunk.body.endsWith("\n") ? hunk.body : hunk.body + "\n";
  return `--- a/${path}\n+++ b/${path}\n${header}\n${body}`;
}
