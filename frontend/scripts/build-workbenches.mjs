// Keep each Vite build in its own process to bound memory use.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const builder = fileURLToPath(
  new URL("./build-local-workbench.mjs", import.meta.url),
);
for (const id of [
  "projects",
  "self_evolution",
  "design",
  "narrative_studio",
  "paper-trading",
  "intelligence",
  "community",
]) {
  execFileSync(process.execPath, [builder, id], {
    stdio: "inherit",
    windowsHide: true,
  });
}
