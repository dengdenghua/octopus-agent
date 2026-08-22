"use strict";
// Desktop backend runtime.
//
// Production installers are self-contained: electron-builder copies the
// PyInstaller backend into resources/backend and packaged Electron processes
// may start only that executable.  They never create a venv, consult a system
// `uv`, or download Python dependencies at first launch.
//
// The uv-managed path below is deliberately development-only.  It keeps the
// unpackaged `--smoke-test-backend` workflow useful without becoming a hidden
// network or host-tool fallback in a released installer.

const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const { app } = require("electron");

// Development layout roots the uv-managed venv under userData/backend. A test
// can override it to reuse an existing venv — e.g. the Playwright smoke reuses
// the checkout's own .venv so the spawn path is exercised without a download.
const backendRoot = () =>
  process.env.OCTOPUS_DESKTOP_BACKEND_ROOT ||
  path.join(app.getPath("userData"), "backend");
const resourcesPath = () => process.resourcesPath;

// The port must match what main.cjs advertises to the renderer via
// OCTOPUS_BACKEND_URL; derive it from that same env when present.
function backendPort() {
  const m = (process.env.OCTOPUS_BACKEND_URL || "").match(/:(\d+)$/);
  return m ? m[1] : "8000";
}

function pythonExe() {
  return process.platform === "win32"
    ? path.join(backendRoot(), ".venv", "Scripts", "python.exe")
    : path.join(backendRoot(), ".venv", "bin", "python");
}

function packagedBackendExecutable() {
  const exe =
    process.platform === "win32" ? "octopus-backend.exe" : "octopus-backend";
  return path.join(resourcesPath(), "backend", exe);
}

function requirePackagedBackendExecutable() {
  const executable = packagedBackendExecutable();
  let info;
  try {
    info = fs.statSync(executable);
  } catch {
    throw new Error(
      `packaged backend executable is missing: ${executable}; refusing system/runtime fallback`,
    );
  }
  if (!info.isFile()) {
    throw new Error(`packaged backend path is not a file: ${executable}`);
  }
  return executable;
}

function developmentUvCmd() {
  if (app.isPackaged) {
    throw new Error("packaged desktop builds must not invoke uv");
  }
  return process.env.OCTOPUS_DESKTOP_DEV_UV || "uv";
}

// Lean core deps for the development-only uv smoke runtime. Keep in sync with
// the `desktop-core` extra in pyproject.toml; released installers use the
// PyInstaller dependency graph instead.
const CORE_DEPS = [
  "fastapi>=0.115,<1.0",
  "starlette>=1.3.1",
  "uvicorn[standard]>=0.32",
  "pyyaml>=6.0",
  "python-multipart>=0.0.31",
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
  desktop: [
    "pyautogui>=0.9.54",
    "pillow>=10.0",
    "uiautomation>=2.0; platform_system == 'Windows'",
  ],
  "code-intel": [
    "tree-sitter>=0.23",
    "tree-sitter-python>=0.23",
    "tree-sitter-typescript>=0.23",
  ],
  vision: [
    "fastembed>=0.8.0",
    "insightface>=1.0.1",
    "opencv-python-headless>=5.0.0.93",
    "rapidocr-onnxruntime>=1.3.0",
  ],
  extract: ["trafilatura>=2.0", "pypdf>=6.15.0"],
  mcp: [
    "mcp>=2.0.0,<3.0",
    "pydantic-settings>=2.14.2",
    "pyjwt[crypto]>=2.13.0",
  ],
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
  if (app.isPackaged) {
    throw new Error(
      "packaged desktop builds use the bundled backend and cannot bootstrap dependencies",
    );
  }
  if (venvReady()) return;
  onProgress?.({ stage: "venv", message: "首次启动：创建后端虚拟环境…" });
  await runProcess(developmentUvCmd(), [
    "venv",
    path.join(backendRoot(), ".venv"),
  ]);
  onProgress?.({
    stage: "deps",
    message: "安装核心依赖（仅首次，约几百 MB）…",
  });
  await runProcess(developmentUvCmd(), [
    "pip",
    "install",
    "--python",
    pythonExe(),
    ...CORE_DEPS,
  ]);
}

// Lazily install a heavy optional capability group on first use.
async function ensureOptionalDeps(group, onProgress) {
  if (app.isPackaged) {
    throw new Error(
      "released desktop capabilities are fixed at build time; rebuild the signed installer with the required optional dependency",
    );
  }
  const pkgs = OPTIONAL_GROUPS[group];
  if (!pkgs) throw new Error(`unknown optional group: ${group}`);
  onProgress?.({ stage: "optional", message: `安装 ${group} 能力…` });
  await runProcess(developmentUvCmd(), [
    "pip",
    "install",
    "--python",
    pythonExe(),
    ...pkgs,
  ]);
}

let backendChild = null;

// Start a fixed bundled executable in packaged mode.  The unpackaged smoke
// path may use the development venv, but there is intentionally no packaged
// fallback to Python, uv, PATH, or the network.
async function spawnBackend(configPath, onProgress) {
  if (backendChild) return backendChild;
  const packaged = Boolean(app.isPackaged);
  if (!packaged) await bootstrapCore(onProgress);
  const env = {
    ...process.env,
    OCTOPUS_DESKTOP: "1",
    OCTOPUS_DATA_DIR: path.join(app.getPath("userData"), "data"),
    OCTOPUS_RESOURCES_DIR: path.join(app.getPath("userData"), "resources"),
  };
  if (!packaged) env.PYTHONPATH = resourcesPath();
  fs.mkdirSync(env.OCTOPUS_DATA_DIR, { recursive: true, mode: 0o700 });
  const executable = packaged
    ? requirePackagedBackendExecutable()
    : pythonExe();
  const args = packaged
    ? [
        "serve",
        "--config",
        configPath,
        "--host",
        "127.0.0.1",
        "--port",
        backendPort(),
      ]
    : [
        "-m",
        "runtime",
        "serve",
        "--config",
        configPath,
        "--host",
        "127.0.0.1",
        "--port",
        backendPort(),
      ];
  const child = spawn(executable, args, {
    stdio: "inherit",
    env,
    windowsHide: true,
  });
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
  packagedBackendExecutable,
  requirePackagedBackendExecutable,
};
