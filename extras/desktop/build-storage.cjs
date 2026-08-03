const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const desktopRoot = __dirname;
const repoRoot = path.resolve(desktopRoot, "..", "..");
const storageRoot = path.resolve(repoRoot, "..", "octopus-storage");
const buildRoot = path.join(desktopRoot, "build");
const outputRoot = path.join(buildRoot, "storage");
const workRoot = path.join(buildRoot, "pyinstaller-storage-work");
const entry = path.join(buildRoot, "storage-entry.py");
const python = process.env.PYTHON_EXE || process.env.PYTHON || "python";

if (!fs.existsSync(path.join(storageRoot, "octopus_storage"))) {
  throw new Error(`octopus-storage source not found at ${storageRoot}`);
}
fs.rmSync(outputRoot, { recursive: true, force: true });
fs.rmSync(workRoot, { recursive: true, force: true });
fs.mkdirSync(outputRoot, { recursive: true });
fs.mkdirSync(workRoot, { recursive: true });
fs.writeFileSync(
  entry,
  "from octopus_storage.cli import main\n\nif __name__ == '__main__':\n    main()\n",
);

const executable = process.platform === "win32" ? "octopus-storage.exe" : "octopus-storage";
const result = spawnSync(
  python,
  [
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name",
    "octopus-storage",
    "--distpath",
    outputRoot,
    "--workpath",
    workRoot,
    "--paths",
    storageRoot,
    entry,
  ],
  { cwd: storageRoot, stdio: "inherit" },
);
fs.rmSync(entry, { force: true });
if (result.status !== 0) process.exit(result.status ?? 1);
if (!fs.existsSync(path.join(outputRoot, executable))) {
  throw new Error(`Storage PyInstaller output missing: ${executable}`);
}
console.log(`[storage] built ${path.join(outputRoot, executable)}`);
