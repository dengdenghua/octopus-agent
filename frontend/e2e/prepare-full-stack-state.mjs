import { mkdirSync, rmSync } from "node:fs";
import { isAbsolute, relative, resolve, sep } from "node:path";

const repoRoot = resolve(process.cwd());
const disposableRoot = resolve(repoRoot, "test-results");
const stateRoot = resolve(process.env.OCTOPUS_HOME || "");
const dataDir = resolve(process.env.OCTOPUS_DATA_DIR || "");
const relativeStateRoot = relative(disposableRoot, stateRoot);

if (
  !process.env.OCTOPUS_HOME ||
  !process.env.OCTOPUS_DATA_DIR ||
  !relativeStateRoot ||
  isAbsolute(relativeStateRoot) ||
  relativeStateRoot === ".." ||
  relativeStateRoot.startsWith(`..${sep}`)
) {
  throw new Error(
    `Refusing to reset E2E state outside ${disposableRoot}: ${stateRoot}`,
  );
}

const relativeDataDir = relative(stateRoot, dataDir);
if (
  !relativeDataDir ||
  isAbsolute(relativeDataDir) ||
  relativeDataDir === ".." ||
  relativeDataDir.startsWith(`..${sep}`)
) {
  throw new Error(`OCTOPUS_DATA_DIR must be inside OCTOPUS_HOME: ${dataDir}`);
}

rmSync(stateRoot, { force: true, recursive: true });
mkdirSync(dataDir, { recursive: true });
