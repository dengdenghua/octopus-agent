const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

// This script lives in extras/desktop/ — repo root is two levels up, and
// electron-builder resolves "build/backend" relative to THIS package root.
const desktopRoot = __dirname;
const repoRoot = path.resolve(desktopRoot, "..", "..");
const buildRoot = path.join(desktopRoot, "build");
const backendOut = path.join(buildRoot, "backend");
const workPath = path.join(buildRoot, "pyinstaller-work");
const specPath = path.join(repoRoot, "packaging", "windows", "octopus-backend.spec");
const expectedExe = path.join(backendOut, "octopus-backend.exe");
const python = process.env.PYTHON_EXE || process.env.PYTHON || "python";

function assertInside(parent, child) {
  const rel = path.relative(parent, child);
  if (rel.startsWith("..") || path.isAbsolute(rel)) {
    throw new Error(`refusing to operate outside ${parent}: ${child}`);
  }
}

for (const target of [backendOut, workPath]) {
  assertInside(desktopRoot, target);
  fs.rmSync(target, { recursive: true, force: true });
}
fs.mkdirSync(backendOut, { recursive: true });
fs.mkdirSync(workPath, { recursive: true });

const result = spawnSync(
  python,
  [
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--distpath",
    backendOut,
    "--workpath",
    workPath,
    specPath,
  ],
  {
    cwd: repoRoot,
    stdio: "inherit",
  },
);

if (result.status !== 0) {
  process.exit(result.status ?? 1);
}

if (!fs.existsSync(expectedExe)) {
  throw new Error(`PyInstaller finished but ${expectedExe} was not created`);
}

console.log(`[backend] built ${expectedExe}`);
