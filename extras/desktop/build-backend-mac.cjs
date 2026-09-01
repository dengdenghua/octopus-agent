const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

// macOS mirror of build-backend-win.cjs. Builds the PyInstaller backend for
// x86_64 using the Rosetta-hosted .venv-x64 interpreter (PyInstaller cannot
// cross-compile architectures, so an x86_64 Python is required to produce an
// x86_64 backend on an Apple Silicon host).
//
// Create the build interpreter with:
//   UV_PROJECT_ENVIRONMENT=.venv-x64 arch -x86_64 <x64-uv> sync --locked \
//     --python 3.11.9 --extra desktop-core --extra desktop-build

const desktopRoot = __dirname;
const repoRoot = path.resolve(desktopRoot, "..", "..");
const buildRoot = path.join(desktopRoot, "build");
const backendOut = path.join(buildRoot, "backend");
const workPath = path.join(buildRoot, "pyinstaller-work-mac");
const specPath = path.join(repoRoot, "packaging", "macos", "octopus-backend.spec");
const expectedExe = path.join(backendOut, "octopus-backend");
// Native arm64 builds use the uv-locked dev interpreter (.venv). x86_64
// builds require the Rosetta-hosted mirror (.venv-x64) because PyInstaller
// cannot cross-compile architectures.
const MAC_ARCH = process.env.OCTOPUS_MAC_ARCH || process.arch;
const venvDir = MAC_ARCH === "x64" ? ".venv-x64" : ".venv";
const expectedLockedPython = path.join(repoRoot, venvDir, "bin", "python");
const configuredPython = process.env.PYTHON_EXE;

function assertInside(parent, child) {
  const rel = path.relative(parent, child);
  if (rel.startsWith("..") || path.isAbsolute(rel)) {
    throw new Error(`refusing to operate outside ${parent}: ${child}`);
  }
}

if (!configuredPython) {
  throw new Error(
    "PYTHON_EXE must point to the Rosetta-hosted x86_64 uv-locked build environment",
  );
}

const lockedPython = path.resolve(configuredPython);
if (lockedPython !== expectedLockedPython) {
  throw new Error(`PYTHON_EXE must resolve to ${expectedLockedPython}`);
}
if (!fs.existsSync(lockedPython) || !fs.statSync(lockedPython).isFile()) {
  throw new Error(
    `locked macOS x86_64 build interpreter is missing: ${lockedPython}; ` +
      "create it with UV_PROJECT_ENVIRONMENT=.venv-x64 " +
      "arch -x86_64 uv sync --locked --python 3.11.9 " +
      "--extra desktop-core --extra desktop-build",
  );
}

for (const target of [backendOut, workPath]) {
  assertInside(desktopRoot, target);
  fs.rmSync(target, { recursive: true, force: true });
}
fs.mkdirSync(backendOut, { recursive: true });
fs.mkdirSync(workPath, { recursive: true });

const result = spawnSync(
  lockedPython,
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

fs.chmodSync(expectedExe, 0o755);

console.log(`[backend] built ${expectedExe}`);
