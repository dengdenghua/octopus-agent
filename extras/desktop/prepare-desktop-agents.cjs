const fs = require("node:fs");
const path = require("node:path");

const frontendRoot = path.resolve(__dirname, "..");
const repoRoot = path.resolve(frontendRoot, "..");
const sourceRoot = path.join(repoRoot, "agents");
const targetRoot = path.join(frontendRoot, "build", "agents");

const allowedRootFiles = new Set(["profile.jsonc"]);
const allowedCoreFiles = new Set([
  "AGENTS.md",
  "BOOTSTRAP.md",
  "HEARTBEAT.md",
  "IDENTITY.md",
  "SOUL.md",
  "TOOLS.md",
  "tool-registry.jsonc",
]);
const deniedNames = new Set([
  ".scores.jsonl",
  "MEMORY.md",
  "USER.md",
  "custom_models.json",
]);
const deniedDirs = new Set([
  ".soul_history",
  "diary",
  "sessions",
  "workspace",
]);
const deniedExts = new Set([
  ".db",
  ".jsonl",
  ".log",
  ".sqlite",
  ".sqlite3",
]);

function assertInside(parent, child) {
  const relative = path.relative(parent, child);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`refusing to write outside ${parent}: ${child}`);
  }
}

function isAvatar(fileName) {
  return /^avatar\.(svg|png|jpg|jpeg|webp)$/i.test(fileName);
}

function shouldCopy(relativePath) {
  const parts = relativePath.split(/[\\/]+/);
  const fileName = parts[parts.length - 1];
  const ext = path.extname(fileName).toLowerCase();

  if (parts.some((part) => deniedDirs.has(part))) return false;
  if (deniedNames.has(fileName)) return false;
  if (deniedExts.has(ext)) return false;

  if (parts[0] === "_shared") {
    return parts.length === 2 && fileName.endsWith(".md");
  }

  if (parts.length === 2) {
    return allowedRootFiles.has(fileName) || isAvatar(fileName);
  }

  if (parts.length === 3 && parts[1] === "agent-core") {
    return allowedCoreFiles.has(fileName);
  }

  return false;
}

function scanForPrivateMaterial(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (![".json", ".jsonc", ".md", ".txt", ".yaml", ".yml"].includes(ext)) {
    return;
  }
  const text = fs.readFileSync(filePath, "utf8");
  const checks = [
    [/sk-[A-Za-z0-9_-]{20,}/, "looks like an API key"],
    [/(api[_ -]?key|authorization|bearer)\s*[:=]\s*["'][^"']{8,}/i, "looks like a credential"],
    [/(phone|mobile|手机号|手机)\s*[:=]\s*["']?\+?\d{6,}/i, "looks like a phone number"],
    [/(claude-opus|aicodemirror)\s*[:=]\s*["'][^"']{3,}/i, "looks like a local model/account config"],
  ];
  for (const [pattern, reason] of checks) {
    if (pattern.test(text)) {
      throw new Error(`refusing to package ${filePath}: ${reason}`);
    }
  }
}

function copyFile(source, target) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(source, target);
  scanForPrivateMaterial(target);
}

function walk(dir, visitor) {
  for (const item of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, item.name);
    if (item.isDirectory()) {
      walk(fullPath, visitor);
    } else if (item.isFile()) {
      visitor(fullPath);
    }
  }
}

if (!fs.existsSync(sourceRoot)) {
  throw new Error(`agents source not found: ${sourceRoot}`);
}

assertInside(path.join(frontendRoot, "build"), targetRoot);
fs.rmSync(targetRoot, { recursive: true, force: true });

let copied = 0;
let skipped = 0;
walk(sourceRoot, (source) => {
  const relativePath = path.relative(sourceRoot, source);
  if (!shouldCopy(relativePath)) {
    skipped += 1;
    return;
  }
  const target = path.join(targetRoot, relativePath);
  assertInside(targetRoot, target);
  copyFile(source, target);
  copied += 1;
});

const forbidden = [];
walk(targetRoot, (filePath) => {
  const relativePath = path.relative(targetRoot, filePath);
  if (
    /(^|[\\/])(sessions|workspace|diary|\.soul_history)([\\/]|$)/i.test(relativePath) ||
    /(^|[\\/])(MEMORY\.md|USER\.md|\.scores\.jsonl|custom_models\.json)$/i.test(relativePath) ||
    /\.jsonl$/i.test(relativePath)
  ) {
    forbidden.push(relativePath);
  }
});
if (forbidden.length > 0) {
  throw new Error(`forbidden files copied:\n${forbidden.join("\n")}`);
}

const manifest = {
  generatedAt: new Date().toISOString(),
  source: "agents",
  copied,
  skipped,
  excludes: [
    "sessions",
    "workspace",
    "USER.md",
    "MEMORY.md",
    ".jsonl",
    "local model/account config",
  ],
};
fs.writeFileSync(
  path.join(targetRoot, "desktop-agents-manifest.json"),
  `${JSON.stringify(manifest, null, 2)}\n`,
);

console.log(`Prepared desktop agents: ${copied} files copied, ${skipped} skipped`);
