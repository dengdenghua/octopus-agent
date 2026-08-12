/**
 * Report-deliverable heuristics shared by the realtime mapping layer
 * (which precomputes `LiveToolEvent.isReportLike` once per item) and
 * the realtime page's "must this run end with a report?" check.
 *
 * Lives in core/threads so the hook layer can use it without importing
 * page code (pages depend on hooks, never the reverse).
 */

/**
 * Tool names / payloads that imply the run must end with a report-style
 * deliverable before it can be considered settled.
 *
 * Word boundaries on the bare keywords are deliberate: `research` without
 * them would match `researcher` / `researching` inside a run_orchestration
 * payload (`"agent_id": ["critic","explorer","researcher"]`) and wrongly
 * flag a completed turn as "still needs a report" (pet error).
 * `deep[-_]research` deliberately has NO boundary requirement so wrapper
 * tool names like `run_deep_research` still count as report-like.
 *
 * NOTE: `app/workspace/realtime/[thread_id]/page.tsx` still carries a
 * local copy named REPORT_DELIVERABLE_PATTERN — keep the two literals
 * in sync until the page imports this one.
 */
export const REPORT_DELIVERABLE_PATTERN =
  /\b(?:report|docx|pptx|pdf|research|swarm)\b|deep[-_]research/i;

/**
 * Per-event report-deliverable check, mirroring the page-level
 * `requiresReportDeliverable` predicate: cheap name test first,
 * serialized input/output only as fallback. Meant to run at mapping
 * time (once per WeakMap-cached item) so per-frame renders never
 * stringify payloads.
 */
export function liveEventIsReportLike(event: {
  name: string;
  input?: unknown;
  output?: unknown;
}): boolean {
  if (REPORT_DELIVERABLE_PATTERN.test(event.name)) return true;
  if (event.input != null && serializedMatches(event.input)) return true;
  return event.output != null && serializedMatches(event.output);
}

function serializedMatches(value: unknown): boolean {
  // Raw-string fast path: JSON.stringify would only add quotes and
  // escapes (none of the pattern's keywords contain escapable chars),
  // and copying a large aggregated command output is the expensive
  // part.
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return typeof text === "string" && REPORT_DELIVERABLE_PATTERN.test(text);
}
