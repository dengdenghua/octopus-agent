// Scan : any annotations in production source.
// A hit is `:` followed by optional whitespace then `any` followed by
// something that is NOT a word char or `$` (filters out `anyType` / `anything`).
// Also report `as any` and `<any>` generics as separate categories so
// we know the full surface area.
import { readFile, readdir } from "node:fs/promises";
import { join, relative, sep } from "node:path";

const SRC = process.argv[2] ?? "src";
const SKIP_TEST = /\.(test|spec)\.(ts|tsx|mjs|js)$/;
const SKIP_DTS = /\.d\.ts$/;

const colonAny = [];
const asAny = [];
const genericAny = [];

function relPosix(p) {
  return relative(process.cwd(), p).split(sep).join("/");
}

async function* walk(dir) {
  for (const e of await readdir(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name === ".next" || e.name === "dist")
        continue;
      yield* walk(p);
    } else if (/\.(ts|tsx|mjs|js)$/.test(e.name)) {
      yield p;
    }
  }
}

for await (const f of walk(SRC)) {
  if (SKIP_TEST.test(f) || SKIP_DTS.test(f)) continue;
  const src = await readFile(f, "utf8");
  const lines = src.split(/\r?\n/);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    // : any not followed by word char (i.e. end of token)
    if (/:\s*any(?![A-Za-z0-9_$])/.test(line)) {
      colonAny.push({ file: relPosix(f), line: i + 1, text: line.trim() });
    }
    if (/\bas\s+any(?![A-Za-z0-9_$])/.test(line)) {
      asAny.push({ file: relPosix(f), line: i + 1, text: line.trim() });
    }
    if (/<\s*any\s*>/.test(line)) {
      genericAny.push({ file: relPosix(f), line: i + 1, text: line.trim() });
    }
  }
}

console.log(`--- : any (annotation) — ${colonAny.length} hits ---`);
for (const h of colonAny) {
  console.log(`  ${h.file}:${h.line}  →  ${h.text}`);
}
console.log(`\n--- as any — ${asAny.length} hits ---`);
for (const h of asAny) {
  console.log(`  ${h.file}:${h.line}  →  ${h.text}`);
}
console.log(`\n--- <any> generic — ${genericAny.length} hits ---`);
for (const h of genericAny) {
  console.log(`  ${h.file}:${h.line}  →  ${h.text}`);
}
