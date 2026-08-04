"use strict";
// uv-managed packaged backend runtime.
//
// The shipped desktop app does NOT bundle a Python interpreter or a ~1.1GB
// site-packages. On first launch it uses `uv` (bundled per-platform binary,
// or a system `uv` as fallback) to create a venv under the user-data dir and
// install a lean core (serve + http + pydantic). Heavy optional capabilities
// (browser, vision, code-intel, …) are installed on demand via
// ensureOptionalDeps().
//
// This is the "B" hybrid: the app stays ~350MB, core functions work offline,
// and heavy deps are pulled only when actually used.

const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const { app } = require("electron");

const backendRoot = () => path.join(app.getPath("userData"), "backend");
const resourcesPath = () => process.resourcesPath;

function pythonExe() {
  return process.platform === "win32"
    ? path.join(backendRoot(), ".venv", "Scripts", "python.exe")
    : path.join(backendRoot(), ".venv", "bin", "python");
}

function bundledUv() {
  const exe = process.platform === "win32" ? "uv.exe" : "uv";
  const p = path.join(resourcesPath(), "uv", exe);
  return fs.existsSync(p) ? p : null;
}

function uvCmd() {
  return bundledUv() || "uv";
}

// Lean core deps for the packaged serve backend. Deliberately small — heavy
// optional groups are declared in pyproject `[project.optional-dependencies]`
// and installed on demand via ensureOptionalDeps(). Keep in sync with the
// `desktop-core` extra in pyproject.toml.
const CORE_DEPS = [
  "fastapi>=0.115,<1.0",
  "uvicorn[standard]>=0.32",
  "pyyaml>=6.0",
  "python-multipart>=0.0.9",
  "httpx>=0.27",
  "python-dotenv>=1.0",
  "pydantic>=2.12.0",
  // anthropic is required at boot: the default desktop config routes the
  // planner through AnthropicModelRouter, which is constructed eagerly in
  // builder._build_planner. Small pure-Python SDK (~2-3MB), so it lives in
  // the core set instead of the lazy extras.
  "anthropic>=0.40,<1.0",
];

// Heavy optional capability → pyproject extra. Installed lazily on first use.
const OPTIONAL_GROUPS = {
  browser: ["playwright>=1.48"],
  desktop: ["pyautogui>=0.9.54", "pillow>=10.0"],
  "code-intel": [
    "tree-sitter>=0.23",
    "tree-sitter-python>=0.23",
    "tree-sitter-typescript>=0.23",
  ],
  vision: [
    "fastembed>=0.8.0",
    "insightface>=1.0.1",
    "opencv-python-headless>=5.0.0.93",
  ],
  extract: ["trafilatura>=2.0"],
  mcp: ["mcp>=0.9,<2.0"],
};

function venvReady() {
  return fs.existsSync(pythonExe());
}

// Spawn a process, forward output, resolve on successful exit.
function runProcess(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, {
      stdio: opts.stream ? "inherit" : ["ignore", "inherit", "inherit"],
      env: { ...process.env, ...opts.env },
    });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${cmd} exited with code ${code}`));
    });
  });
}

// Create the venv + install the core deps if missing. Runs once on first
// launch and downloads the Python interpreter + a lean dep set.
async function bootstrapCore(onProgress) {
  if (venvReady()) return;
  onProgress?.({ stage: "venv", message: "首次启动：创建后端虚拟环境…" });
  await runProcess(uvCmd(), ["venv", path.join(backendRoot(), ".venv")]);
  onProgress?.({ stage: "deps", message: "安装核心依赖（仅首次，约几百 MB）…" });
  await runProcess(uvCmd(), [
    "pip",
    "install",
    "--python",
    pythonExe(),
    ...CORE_DEPS,
  ]);
}

// Lazily install a heavy optional capability group on first use.
async function ensureOptionalDeps(group, onProgress) {
  const pkgs = OPTIONAL_GROUPS[group];
  if (!pkgs) throw new Error(`unknown optional group: ${group}`);
  onProgress?.({ stage: "optional", message: `安装 ${group} 能力…` });
  await runProcess(uvCmd(), [
    "pip",
    "install",
    "--python",
    pythonExe(),
    ...pkgs,
  ]);
}

let backendChild = null;

// Start the packaged backend using the uv-managed venv python. Bootstraps the
// runtime on first launch (non-blocking) so the renderer can show progress.
async function spawnBackend(configPath, onProgress) {
  if (backendChild) return backendChild;
  await bootstrapCore(onProgress);
  const env = {
    ...process.env,
    PYTHONPATH: resourcesPath(),
  };
  const child = spawn(
    pythonExe(),
    [
      "-m",
      "runtime",
      "serve",
      "--config",
      configPath,
      "--host",
      "127.0.0.1",
      "--port",
      "8000",
    ],
    { stdio: "inherit", env },
  );
  backendChild = child;
  child.on("exit", (code, signal) => {
    console.warn(
      `[octopus] backend exited (code=${code}, signal=${signal}); restart via backend.restart`,
    );
    if (backendChild === child) backendChild = null;
  });
  child.on("error", (err) => {
    console.warn("[octopus] backend spawn failed:", err.message);
    if (backendChild === child) backendChild = null;
  });
  return child;
}

function killBackend() {
  if (!backendChild) return;
  const child = backendChild;
  backendChild = null;
  try {
    child.kill();
  } catch (err) {
    console.warn("[octopus] backend kill failed:", err.message);
  }
}

module.exports = {
  spawnBackend,
  killBackend,
  ensureOptionalDeps,
  bootstrapCore,
  venvReady,
  pythonExe,
};