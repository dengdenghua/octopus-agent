/**
 * Adapter: in-app workbench replay (``WorkBlock[]``) → a portable ``ReplayData``
 * for the self-contained HTML exporter in ``@/core/sharing/replay-html``.
 *
 * This is where **export-time redaction** happens — the produced HTML is a file
 * the user can send to anyone, so before a step's command/output is embedded we
 * truncate it and scrub obvious secrets (API keys, JWTs, bearer tokens, long
 * hex digests). Best-effort, not a guarantee: the user still inspects the file
 * before sharing. Screenshots are inlined only when the event already carries a
 * ``data:`` URL — this module never fetches the network.
 */

import type { ReplayData, ReplayStep } from "@/core/sharing/replay-html";

import {
  commandForBlock,
  stringFromKeys,
  textFromUnknown,
} from "./agent-workbench-utils";
import type { WorkBlock } from "./work-blocks";

const MAX_BODY = 1200;

/** Best-effort secret scrub applied to every embedded body. */
export function redactSecrets(text: string): string {
  return text
    .replace(
      /eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}/g,
      "«redacted-jwt»",
    )
    .replace(
      /\b(?:sk|pk|rk|ghp|gho|ghs|ghu|xox[baprs])[-_][A-Za-z0-9]{12,}\b/g,
      "«redacted-token»",
    )
    .replace(
      /\b(?:Bearer|Authorization:?)\s+[A-Za-z0-9._-]{12,}/gi,
      "«redacted-bearer»",
    )
    .replace(
      /(["']?(?:api[_-]?key|secret|password|passwd|token)["']?\s*[:=]\s*)["']?[^\s"',}]{6,}/gi,
      "$1«redacted»",
    )
    .replace(/\b[A-Fa-f0-9]{40,}\b/g, "«redacted-hex»");
}

function truncate(text: string, max = MAX_BODY): string {
  const clean = text.trimEnd();
  return clean.length <= max ? clean : `${clean.slice(0, max - 1)}…`;
}

function bodyForBlock(block: WorkBlock): string {
  const parts: string[] = [];
  if (block.kind === "terminal") {
    const cmd = commandForBlock(block);
    if (cmd) parts.push(`$ ${cmd}`);
    const out = block.outputText || textFromUnknown(block.event.output);
    if (out) parts.push(out);
  } else {
    if (block.inputText && block.inputText !== block.subtitle) {
      parts.push(block.inputText);
    }
    if (block.outputText) parts.push(block.outputText);
  }
  const joined = parts.join("\n").trim();
  return joined ? truncate(redactSecrets(joined)) : "";
}

/** Inline a screenshot only if the event already holds a ``data:image`` URL. */
function imageForBlock(block: WorkBlock): string | undefined {
  for (const source of [block.event.output, block.event.input]) {
    const candidate = stringFromKeys(source, [
      "screenshot",
      "image",
      "image_data_url",
      "data_url",
      "dataUrl",
      "preview",
    ]);
    if (candidate.startsWith("data:image/")) return candidate;
  }
  return undefined;
}

function isLifecycleBlock(block: WorkBlock): boolean {
  return Boolean(
    block.event.lifecycle ||
      /subagent_(spawned|finished)/i.test(block.event.name),
  );
}

export interface ReplayMeta {
  title: string;
  brand?: string;
  footer?: string;
  frameMs?: number;
}

export function buildReplayFromBlocks(
  blocks: WorkBlock[],
  meta: ReplayMeta,
): ReplayData {
  const steps: ReplayStep[] = blocks
    .filter((block) => !isLifecycleBlock(block))
    .map((block): ReplayStep => {
      const body = bodyForBlock(block);
      const image = imageForBlock(block);
      return {
        kind: block.kind,
        title: block.title,
        subtitle: block.subtitle || undefined,
        body: body || undefined,
        status: block.status,
        image,
      };
    })
    .filter((step) => step.title || step.body || step.image);

  return {
    title: meta.title,
    steps,
    brand: meta.brand,
    footer: meta.footer,
    frameMs: meta.frameMs,
  };
}
