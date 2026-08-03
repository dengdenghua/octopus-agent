# Frontend Build-Size Baseline

Captured 2026-08-03 with `pnpm build:report` (Vite 7.3.3, `rollup-plugin-visualizer` 7.0.1).
This is the reference baseline for the "前端构建体积可观测" requirement
(`.trae/specs/codex-parity-optimization/spec.md`) and the comparison point
against the Codex 14.9 MB main-bundle pain point.

## How to regenerate

```bash
cd frontend
pnpm build:report        # runs vite build with OCTOPUS_VISUALIZER=1
# open dist/stats.html for the interactive treemap
```

`rollup-plugin-visualizer` is a devDependency and is gated behind the
`OCTOPUS_VISUALIZER=1` env var, so ordinary `pnpm build` output is unaffected.

## Summary

- 5231 modules transformed, 639 JS chunks emitted.
- Total JS (minified): ≈ 19.96 MB across all chunks.
- **No chunk exceeds `chunkSizeWarningLimit` (1400 kB).** Largest is
  `codemirror-core` at 857.57 kB (gzip 281.73 kB).
- Initial entry chunk `index-*.js` = 372.77 kB (gzip 131.10 kB).
- Heavy engines are code-split into lazy chunks and only fetched on demand
  when their route is visited (see Lazy-loading note below).

## Largest chunks (top 30, minified / gzip)

| Size (kB) | gzip (kB) | Chunk |
|---|---|---|
| 857.57 | 281.73 | codemirror-core |
| 779.85 | 196.03 | emacs-lisp |
| 706.72 | 192.46 | page (knowledge/3D) * |
| 626.08 | 44.82 | cpp |
| 622.34 | 230.29 | wasm |
| 574.39 | 145.32 | page (three) |
| 520.36 | 121.07 | mermaid-chunk |
| 467.73 | 149.43 | mermaid-chunk |
| 372.77 | 131.10 | index (entry) |
| 353.07 | 115.17 | ja-JP (locale) |
| 332.55 | 100.19 | markdown-plugins |
| 320.03 | 110.28 | ko-KR (locale) |
| 300.39 | 96.08 | markdown-streamdown |
| 298.38 | 89.83 | message-list |
| 275.82 | 108.29 | zh-CN (locale) |
| 270.22 | 79.23 | mermaid-katex |
| 262.39 | 77.14 | wolfram (shiki) |
| 258.80 | 76.91 | katex |
| 231.33 | 74.14 | react-vendor |
| 218.92 | 32.74 | mermaid-chunk |
| 190.22 | 18.07 | vue-vine (shiki) |
| 183.82 | 16.63 | angular-ts (shiki) |
| 181.08 | 16.04 | typescript (shiki) |
| 177.79 | 16.61 | jsx (shiki) |
| 175.54 | 16.51 | tsx (shiki) |
| 174.83 | 16.51 | javascript (shiki) |
| 171.97 | 30.62 | objective-cpp (shiki) |
| 152.67 | 43.50 | mermaid-architectureDiagram |
| 146.38 | 33.55 | page |
| 138.17 | 43.53 | ui-radix |

\* chunk filenames contain a content hash and change between builds; the
identity is stable by logical name.

## Chunks over the 1400 kB warning limit

None. All chunks are below `chunkSizeWarningLimit`.

## Lazy-loading verification (heavy deps on demand)

All routes in `frontend/src/router.tsx` are already wrapped in
`React.lazy` + `Suspense`. Verification against the built artifacts:

- **three** — NOT in the entry chunk. Bundled into the knowledge-page chunk
  (under `page-*.js`, ≈ 574 kB) and is only fetched when navigating to the
  `/workspace/knowledge` route. Confirmed via `WebGLRenderer` symbol scan.
- **@xyflow/react** — not imported anywhere in `src` (dead dependency; no
  chunk emitted for it).
- **mermaid** — split into many on-demand chunks (`mermaid-*`). The core
  mermaid runtime is `modulepreload`-ed in the entry HTML because chat
  messages render mermaid blocks via `MermaidBlock`, which `import()`s
  `mermaid-real` lazily (a core first-run feature, not a route).
- **mermaid-shim** — aliased `mermaid` → `src/lib/mermaid-shim.ts` to avoid
  pulling the full upstream ESM bundle into the workspace UI.

## Comparison vs Codex 14.9 MB main bundle

Initial load (raw, minified) of the entry module graph is ≈ 2.0 MB
(index + react-vendor + query-virtual + ui-radix + katex + markdown-plugins +
markdown-streamdown + mermaid core), far below the 14.9 MB single-bundle
pain point Codex exhibits. The remaining ~18 MB is composed of hundreds of
lazy route/chunk files that are only fetched on demand (mostly shiki syntax
highlighter grammars and codemirror languages).