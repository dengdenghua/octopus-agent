/// <reference types="vitest" />
import { defineConfig } from "vite";
import type { Plugin } from "vite";
import react from "@vitejs/plugin-react";
import { visualizer } from "rollup-plugin-visualizer";
import { createHash } from "node:crypto";
import { fileURLToPath } from "url";
import { createRequire } from "module";
import path from "path";
import fs from "fs";

import { WEB_BUILD_DEDUPLICATED_PET_ASSETS } from "./config/public-asset-dedup";

const require = createRequire(import.meta.url);
const vitePackage = require("vite/package.json");

function sha256File(filename: string): string {
  return createHash("sha256").update(fs.readFileSync(filename)).digest("hex");
}

function omitDuplicatePetAssetsFromWebBuild(): Plugin {
  let rootDir = "";
  let outputDir = "";

  return {
    name: "octopus-omit-duplicate-pet-authoring-assets",
    apply: "build",
    configResolved(config) {
      rootDir = config.root;
      outputDir = path.resolve(config.root, config.build.outDir);
    },
    closeBundle() {
      // Both source assets remain in the repository. A future edit that makes
      // either copy diverge fails the build instead of silently dropping a
      // newly-used asset from the renderer package.
      for (const asset of WEB_BUILD_DEDUPLICATED_PET_ASSETS) {
        const publicSource = path.resolve(rootDir, "public", asset.publicPath);
        const canonicalSource = path.resolve(rootDir, asset.canonicalPath);
        if (!fs.existsSync(publicSource) || !fs.existsSync(canonicalSource)) {
          throw new Error(
            `Cannot deduplicate missing pet asset: ${asset.publicPath}`,
          );
        }
        if (
          fs.statSync(publicSource).size !==
            fs.statSync(canonicalSource).size ||
          sha256File(publicSource) !== sha256File(canonicalSource)
        ) {
          throw new Error(
            `Pet asset copies diverged; keep the web copy until its loading contract is explicit: ${asset.publicPath}`,
          );
        }
        fs.rmSync(path.resolve(outputDir, asset.publicPath), { force: true });
      }
    },
  };
}

const gatewayTarget =
  process.env.OCTOPUS_INTERNAL_GATEWAY_BASE_URL ||
  `http://127.0.0.1:${process.env.GATEWAY_PORT || "8888"}`;

function packageNameFromNodeModule(id: string): string | null {
  const normalized = id.replace(/\\/g, "/");
  const marker = "/node_modules/";
  const markerIndex = normalized.lastIndexOf(marker);
  if (markerIndex < 0) return null;
  const rest = normalized.slice(markerIndex + marker.length);
  const parts = rest.split("/");
  if (parts[0]?.startsWith("@")) {
    return parts.length >= 2 ? `${parts[0]}/${parts[1]}` : null;
  }
  return parts[0] || null;
}

const proxyConfig = {
  "/api/files/stream": {
    target: gatewayTarget,
    changeOrigin: true,
    secure: false,
    timeout: 0,
    proxyTimeout: 0,
    on: {
      proxyReq: (proxyReq: any) => {
        proxyReq.setHeader("Connection", "keep-alive");
        proxyReq.setHeader("Cache-Control", "no-cache");
      },
    },
  },
  "/api/preview/stream": {
    target: gatewayTarget,
    changeOrigin: true,
    secure: false,
    timeout: 0,
    proxyTimeout: 0,
    on: {
      proxyReq: (proxyReq: any) => {
        proxyReq.setHeader("Connection", "keep-alive");
        proxyReq.setHeader("Cache-Control", "no-cache");
      },
    },
  },
  "/api": {
    target: gatewayTarget,
    changeOrigin: true,
    secure: false,
    timeout: 0,
    proxyTimeout: 0,
    ws: true,
    on: {
      proxyReq: (proxyReq: any, req: any, _res: any) => {
        if (req.headers.accept?.includes("text/event-stream")) {
          proxyReq.setHeader("Connection", "keep-alive");
          proxyReq.setHeader("Cache-Control", "no-cache");
        }
      },
      proxyRes: (proxyRes: any, req: any, _res: any) => {
        if (
          req.headers.accept?.includes("text/event-stream") ||
          (proxyRes.headers["content-type"] || "").includes("text/event-stream")
        ) {
          proxyRes.headers["cache-control"] = "no-cache";
          proxyRes.headers["x-accel-buffering"] = "no";
        }
      },
      error: (_err: any, _req: any, res: any) => {
        if (!res.headersSent) {
          res.writeHead(502, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ error: "proxy_error" }));
        }
      },
    },
  },
  "/v1": {
    target: gatewayTarget,
    changeOrigin: true,
    ws: true,
  },
  // Keep aligned with electron/desktop-protocol.cjs BACKEND_ROUTE_PREFIXES;
  // the bootstrap overlay polls /readyz same-origin relative in dev too.
  "/readyz": {
    target: gatewayTarget,
    changeOrigin: true,
  },
  "/livez": {
    target: gatewayTarget,
    changeOrigin: true,
  },
  "/media": {
    target: gatewayTarget,
    changeOrigin: true,
  },
  "/.well-known": {
    target: gatewayTarget,
    changeOrigin: true,
  },
  "/.a2a": {
    target: gatewayTarget,
    changeOrigin: true,
  },
};

function buildTracePlugin() {
  const tracePath = path.resolve("vite-transform-trace.log");
  return {
    name: "octopus-build-trace",
    buildStart() {
      fs.writeFileSync(tracePath, "");
    },
    transform(_code: string, id: string) {
      fs.appendFileSync(tracePath, `${id}\n`);
      return null;
    },
  };
}

export default defineConfig({
  base: "./",
  define: {
    __VITE_VERSION__: JSON.stringify(vitePackage.version),
  },
  plugins: [
    omitDuplicatePetAssetsFromWebBuild(),
    ...(process.env.OCTOPUS_BUILD_TRACE === "1" ? [buildTracePlugin()] : []),
    react(),
    // Build-size audit capability. Gated behind an env var so ordinary
    // `pnpm build` output is unaffected. Run a report with:
    //   OCTOPUS_VISUALIZER=1 pnpm build
    // and open `dist/stats.html` (or `--report` for rollup console output).
    ...(process.env.OCTOPUS_VISUALIZER === "1"
      ? [
          visualizer({
            filename: "dist/stats.html",
            gzipSize: true,
            brotliSize: true,
          }),
        ]
      : []),
  ],
  resolve: {
    alias: [
      {
        find: "@",
        replacement: fileURLToPath(new URL("./src", import.meta.url)),
      },
      {
        find: "motion/react",
        replacement: fileURLToPath(
          new URL("./src/lib/motion-shim.tsx", import.meta.url),
        ),
      },
      {
        find: "mermaid-real",
        replacement: fileURLToPath(
          new URL(
            "./node_modules/mermaid/dist/mermaid.esm.min.mjs",
            import.meta.url,
          ),
        ),
      },
      // ``mermaid`` is aliased to a local shim because the upstream
      // package ships a large ESM bundle with worker-based parsing
      // we don't need in the workspace UI. ``resolve.alias`` covers
      // both dev and build; no pre-resolve plugin required.
      {
        find: "mermaid",
        replacement: fileURLToPath(
          new URL("./src/lib/mermaid-shim.ts", import.meta.url),
        ),
      },
      // ``shiki`` (bare specifier only — subpaths like "shiki/langs/*"
      // must keep resolving to the real package) is aliased to a local
      // shim that swaps the full bundle (~200 language chunks + the
      // Oniguruma WASM engine) for a JS-regex-engine core highlighter
      // with a curated language whitelist. See src/lib/shiki-shim.ts.
      {
        find: /^shiki$/,
        replacement: fileURLToPath(
          new URL("./src/lib/shiki-shim.ts", import.meta.url),
        ),
      },
    ],
  },
  server: {
    // PORT is honoured so a supervisor that assigns a free port (the IDE
    // preview pane) can run alongside a dev server already holding 3000.
    // FRONTEND_PORT stays the explicit override and wins.
    port: parseInt(process.env.FRONTEND_PORT || process.env.PORT || "3888"),
    host: "0.0.0.0",
    proxy: proxyConfig,
  },
  preview: {
    port: parseInt(process.env.FRONTEND_PORT || process.env.PORT || "3888"),
    host: "0.0.0.0",
    proxy: proxyConfig,
  },
  build: {
    outDir: "dist",
    sourcemap: process.env.OCTOPUS_SOURCEMAP === "1" ? "hidden" : false,
    reportCompressedSize: true,
    // Most heavy engines are split below 800 KB. Mermaid's
    // architectureDiagram implementation is a single upstream lazy chunk
    // (~1.35 MB minified, ~350 KB gzip), so keep the warning threshold just
    // above that known on-demand boundary while still catching larger chunks.
    chunkSizeWarningLimit: 1400,
    rollupOptions: {
      output: {
        // Rollup otherwise emits hundreds of sub-kilobyte shared chunks for
        // icons and small helpers. Merge safe automatic fragments while the
        // explicit heavy-engine boundaries below remain intact.
        experimentalMinChunkSize: 4_000,
        manualChunks(id) {
          // Vite's preload helper is imported by the entry and every dynamic
          // boundary. Without a stable home Rollup can attach it to a large
          // lazy feature chunk, which then makes that feature an accidental
          // entry preload (Markdown, CodeMirror and Mermaid have all been
          // observed here). Keep the tiny runtime independent.
          if (id === "\0vite/preload-helper.js") {
            return "vite-runtime";
          }

          const pkg = packageNameFromNodeModule(id);

          if (
            id.includes("node_modules/react-dom") ||
            id.includes("node_modules/react/") ||
            id.includes("node_modules/react-router-dom")
          ) {
            return "react-vendor";
          }
          if (id.includes("node_modules/@radix-ui/")) {
            return "ui-radix";
          }
          // These tiny, shell-wide UI dependencies otherwise become dozens
          // of shared icon/helper chunks across lazy routes. Keeping them in
          // one modest foundation chunk also prevents a dynamic renderer's
          // manual chunk from claiming shared class-name helpers and turning
          // itself into an entry dependency.
          if (
            pkg === "lucide-react" ||
            pkg === "class-variance-authority" ||
            pkg === "clsx" ||
            pkg === "tailwind-merge"
          ) {
            return "ui-foundation";
          }

          if (id.includes("node_modules/@tanstack/")) {
            return "query-virtual";
          }
          if (pkg === "lodash-es") {
            return "lodash-es";
          }
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}", "vite.config.test.ts"],
    exclude: [
      "node_modules/**",
      "dist/**",
      "release/**",
      "e2e/**",
      "src/**/_tmp_*.test.{ts,tsx}",
    ],
    coverage: {
      provider: "v8",
      // Ratchet thresholds — set slightly below current levels to prevent
      // regression while allowing incremental improvement over time.
      // Goal: ratchet up until we reach 80/75/80/80.
      // Current actual (2026-08-03): lines 51.03 / branches 48.59 /
      // functions 38.29 / statements 50.01.
      thresholds: {
        lines: 51,
        branches: 48,
        functions: 38,
        statements: 50,
      },
    },
  },
});
