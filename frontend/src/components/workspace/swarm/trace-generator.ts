import type { SwarmAgent, TraceEntry } from "./types";

/**
 * Shape of the label bag callers pass in to localize the simulated trace
 * stream. Mirrors the `traceGenerator` section in the i18n locales. When
 * no bag is passed we fall back to hardcoded English — better than a
 * TypeError from `.searchTitle` on `undefined`.
 */
export interface TraceGeneratorLabels {
  searchTitle: (query: string) => string;
  resultCount: (n: number) => string;
  toolCallTitle: string;
  toolCallDetail: string;
  milestoneSave: (bucket: number, total: number) => string;
  thinkThoughts: string[];
}

const DEFAULT_LABELS: TraceGeneratorLabels = {
  searchTitle: (q) => `Web search: ${q}`,
  resultCount: (n) => `${n} results`,
  toolCallTitle: "Tool call: fs.read_file",
  toolCallDetail: "Reading prior notes for context",
  milestoneSave: (bucket, total) => `Save milestone note (part ${bucket}/${total})`,
  thinkThoughts: [
    "Synthesize collected info",
    "Identify key differentiators",
    "Assess data reliability",
    "Plan next retrieval step",
    "Cross-check multiple sources",
  ],
};

// Pool of plausible activities each agent might emit. Chosen at random
// during simulation to keep the trace feed alive without backend data.
const SEARCH_QUERIES = [
  "best practices",
  "architecture deep dive",
  "pricing comparison",
  "open source alternatives",
  "case studies 2024",
  "failure modes",
  "performance benchmarks",
  "security posture",
  "migration guide",
];

const READ_TITLES = [
  "Getting started guide",
  "Architecture overview",
  "Case study: enterprise rollout",
  "Changelog & release notes",
  "API reference",
  "Community discussion thread",
];

const READ_DOMAINS = [
  { host: "developer.example.io", favicon: "📘" },
  { host: "docs.example.org", favicon: "📗" },
  { host: "blog.example.dev", favicon: "📰" },
  { host: "arxiv.org", favicon: "📕" },
  { host: "github.com", favicon: "🐙" },
];

let seq = 0;
function nextId() {
  seq += 1;
  return `t-${Date.now().toString(36)}-${seq}`;
}

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]!;
}

/**
 * Produce 0-2 new trace entries for an agent at each simulation tick.
 * Kind distribution is roughly: 45% search/read, 35% think, 15% write on
 * milestone progress, 5% tool.
 *
 * @param agent  Current agent snapshot
 * @param labels Localized label bag (defaults to English). Pass
 *               `t.traceGenerator` from the i18n context in callers.
 */
export function generateTraceTick(
  agent: SwarmAgent,
  labels: TraceGeneratorLabels = DEFAULT_LABELS,
): TraceEntry[] {
  if (agent.status === "done" || agent.status === "pending") return [];
  // Low chance of emitting nothing this tick.
  if (Math.random() < 0.4) return [];

  const now = Date.now();
  const entries: TraceEntry[] = [];
  const roll = Math.random();

  if (roll < 0.3) {
    // search
    const q = `${pick(SEARCH_QUERIES)} ${agent.name.slice(0, 3)}`;
    entries.push({
      id: nextId(),
      agentId: agent.id,
      timestamp: now,
      kind: "search",
      title: labels.searchTitle(q),
      detail: labels.resultCount(5 + Math.floor(Math.random() * 40)),
    });
  } else if (roll < 0.6) {
    // read
    const d = pick(READ_DOMAINS);
    entries.push({
      id: nextId(),
      agentId: agent.id,
      timestamp: now,
      kind: "read",
      title: pick(READ_TITLES),
      detail:
        "This is a simulated page fetched by the agent. Real deployments will surface the fetched URL's summary here with proper truncation and formatting.",
      url: `https://${d.host}/page-${Math.floor(Math.random() * 1000)}`,
      faviconEmoji: d.favicon,
    });
  } else if (roll < 0.93) {
    // think
    entries.push({
      id: nextId(),
      agentId: agent.id,
      timestamp: now,
      kind: "think",
      title: pick(labels.thinkThoughts),
    });
  } else {
    // tool use
    entries.push({
      id: nextId(),
      agentId: agent.id,
      timestamp: now,
      kind: "tool",
      title: labels.toolCallTitle,
      detail: labels.toolCallDetail,
    });
  }

  // Milestone write when crossing a 0.25 progress boundary.
  const bucket = Math.floor(agent.progress * 4);
  const nextBucket = Math.floor((agent.progress + 0.04) * 4);
  if (nextBucket > bucket && nextBucket < 4) {
    entries.push({
      id: nextId(),
      agentId: agent.id,
      timestamp: now + 1,
      kind: "write",
      title: labels.milestoneSave(nextBucket, 4),
    });
  }

  return entries;
}
