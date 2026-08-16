import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { ITEM_STATUSES, TURN_STATUSES } from "@/core/realtime/items";

// The authoritative source of truth lives in the backend
// (`runtime/protocol/items.py`). ITEM_STATUSES / TURN_STATUSES are the
// ACTUAL frontend mirrors exported from `src/core/realtime/items.ts` — the
// union types are derived from them — so this gate fails CI whenever the
// two drift. A new backend status would otherwise fall silently into the
// frontend's default branch.

const REPO_ROOT = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../../../",
);

function parseEnumValues(source: string, className: string): string[] {
  const re = new RegExp(
    `class ${className}\\(StrEnum\\):\\n([\\s\\S]*?)\\n\\n`,
    "m",
  );
  const match = source.match(re);
  if (!match?.[1]) {
    throw new Error(
      `Could not find "class ${className}(StrEnum)" in runtime/protocol/items.py`,
    );
  }
  const values: string[] = [];
  for (const line of match[1].split("\n")) {
    const member = line.match(/^\s+\w+\s*=\s*"([^"]+)"/);
    if (member?.[1]) values.push(member[1]);
  }
  return values;
}

describe("protocol enum parity", () => {
  const source = readFileSync(
    resolve(REPO_ROOT, "runtime/protocol/items.py"),
    "utf8",
  );

  it("ItemStatus matches runtime/protocol/items.py", () => {
    expect(parseEnumValues(source, "ItemStatus")).toEqual([...ITEM_STATUSES]);
  });

  it("TurnStatus matches runtime/protocol/items.py", () => {
    expect(parseEnumValues(source, "TurnStatus")).toEqual([...TURN_STATUSES]);
  });
});
