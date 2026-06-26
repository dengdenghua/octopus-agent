# Frontend i18n extraction + cleanup — handoff plan

Self-contained task spec. You (the executing agent) have **no prior context**;
everything you need is below. Work in `frontend/`. Node 22, pnpm/npm.

## Goal

The frontend's primary language is Chinese. Many components hardcode Chinese
UI text directly in JSX instead of going through the i18n system, so
**English / Japanese / Korean users see raw Chinese** in those components.
Extract the hardcoded strings into the i18n system so every visible string
resolves through `t.*`.

## How i18n works here

- Hook: `const { t } = useI18n();` from `@/core/i18n/hooks`. Use strings as
  `t.<section>.<key>` (e.g. `t.mcpSettings.title`). Functions for
  interpolation: `t.x.foo(name)`.
- Shape (the TypeScript contract every locale must satisfy):
  `src/core/i18n/locales/types.ts`
- Four locale files implement that shape:
  - `src/core/i18n/locales/en-US.ts` — English
  - `src/core/i18n/locales/zh-CN.ts` — Chinese (the source of truth here)
  - `src/core/i18n/locales/ja-JP.ts` — Japanese (currently ~English stub)
  - `src/core/i18n/locales/ko-KR.ts` — Korean (currently ~English stub)
- **`tsc --noEmit` enforces completeness**: if you add a key to `types.ts`
  you MUST add it to all four locales or typecheck fails. This is your safety
  net — let it catch missing keys.

## The per-string procedure (do this for each hardcoded Chinese string)

1. Pick a `section` (reuse an existing one that fits the component, or add a
   new section object to `types.ts` + all four locales).
2. Add the key:
   - `types.ts`: `myKey: string;` (or `myKey: (n: string) => string;` if it
     interpolates).
   - `zh-CN.ts`: `myKey: "<the original Chinese text>",`
   - `en-US.ts`: `myKey: "<English translation>",`
   - `ja-JP.ts` / `ko-KR.ts`: English is acceptable as a fallback (these
     locales are already mostly English) — DO NOT machine-translate to
     low-quality Japanese/Korean. Leave English; real translation is a
     separate task (see below).
3. In the component: replace the literal with `t.<section>.<myKey>`. Add
   `const { t } = useI18n();` if the component doesn't already have it
   (import from `@/core/i18n/hooks`).
4. Only extract **UI-visible** strings: JSX text nodes, and string props like
   `placeholder=`, `title=`, `aria-label=`, `label=`, toast/alert messages,
   `aria-label`. **Do NOT touch**: code comments, console.* messages, test
   files, technical identifiers, CSS class names.

### Worked example

Before (`knowledge-graph-panel.tsx`):
```tsx
<Link to="/workspace/realtime/new">开始一次任务</Link>
...
<div className="text-sm font-medium">没有匹配的实体</div>
```
After:
```tsx
const { t } = useI18n();
...
<Link to="/workspace/realtime/new">{t.knowledgeGraph.startTask}</Link>
...
<div className="text-sm font-medium">{t.knowledgeGraph.noMatchingEntities}</div>
```
types.ts → `knowledgeGraph: { startTask: string; noMatchingEntities: string; ... }`
zh-CN → `startTask: "开始一次任务", noMatchingEntities: "没有匹配的实体",`
en-US → `startTask: "Start a task", noMatchingEntities: "No matching entities",`
ja/ko → same English strings (fallback).

## Scope — worst offenders (extract in this order, highest count first)

Counts are approximate hardcoded-Chinese UI strings per file (from an audit;
re-check with the find command below). ~30+ files, a few hundred strings total.

| count | file (under `src/`) |
|------:|---------------------|
| 67 | `components/browser/browser-home.tsx` |
| 47 | `components/workspace/agent-workbench-pages.tsx` |
| 44 | `components/browser/copilot-panel.tsx` |
| 38 | `components/workspace/evolution-dashboard/index.tsx` |
| 37 | `components/browser/extension-marketplace.tsx` |
| 35 | `components/workspace/agent-workbench-panel.tsx` |
| 34 | `components/workspace/intelligence-panel.tsx` |
| 34 | `components/workspace/agents/agent-role-profile-dialog.tsx` |
| 33 | `components/workspace/collab/team-tasks-panel.tsx` |
| 24 | `components/workspace/gene-lock-badge.tsx` |
| 23 | `components/browser/webview-tab.tsx` |
| 22 | `components/workspace/browser-preview-panel.tsx` |
| 14 | `components/workspace/live-tool-timeline.tsx` |
| 12 | `components/store/store-utils.tsx` |
| 11 | `components/store/local-skill-directory-panel.tsx` |

Find the full list + per-file lines yourself:
```bash
cd frontend
# files with hardcoded Chinese UI strings (excludes comments, locales, tests):
grep -rlE "[一-鿿]" src/components --include="*.tsx" | grep -vE "locales|\.test\."
# lines in one file (skip // and * comment lines):
grep -nE "[一-鿿]" src/components/<file>.tsx | grep -vE "^\s*[0-9]+:\s*(//|\*)"
```

## Verification (run after EACH file, before committing)

```bash
cd frontend
npm run typecheck   # MUST pass — proves all 4 locales have every new key
npm run lint        # no new errors (warnings ok)
npm test            # 866 tests must stay green (vitest run)
```

## Commit discipline

- The shared working tree may have concurrent edits. Commit with an explicit
  pathspec, e.g. `git commit -- <component> src/core/i18n/locales/*`.
- Commit per file or small batch (don't accumulate hundreds of edits in one
  commit). Suggested message: `i18n(frontend): extract hardcoded strings in <component>`.
- End commit bodies with: `Co-Authored-By: <your model>`.

## Out of scope / already handled — DO NOT redo

- **Accessibility (icon-button aria-labels)**: DONE. 12 unlabeled icon buttons
  were fixed. Don't re-audit.
- **Error UX (console.error → toast)**: audited and intentionally NOT changed —
  the remaining `console.error` calls are in infra / error-boundaries / already
  have other feedback. Adding toasts there causes double-toasts/noise. Leave them.
- **ja/ko full translation (~5500 strings each)**: SEPARATE task. Do NOT
  machine-translate inline — it pollutes the locale files with low quality.
  Route through a real translation service/pass once the keys exist.

## Optional quick wins (low value, do only if time permits)

- Dead code: `src/components/browser/browser-home.tsx` has ~14 unused
  imports/vars (`PlugIcon`, `CopyIcon`, `CheckCircle2`, `GripVertical`,
  `authHeaders`, `jsonAuthHeaders`, `copyTextToClipboard`, `BROWSER_HOME_URL`,
  `DESKTOP_WIDGETS`, ...) + 1 in `webview-tab.tsx` (`BrowserDesktopHome`).
  Removing genuinely-unused **imports** is safe; be cautious with local
  consts/state that may be half-wired features — verify with `npm run lint`.
- One `consistent-type-imports` warning is `eslint --fix`-able.

## Definition of done

- `grep -rlE "[一-鿿]" src/components --include="*.tsx" | grep -vE "locales|\.test\."`
  returns only files whose Chinese is in comments (no UI-string hits).
- `npm run typecheck` + `npm test` green.
- en-US users see English everywhere; zh-CN unchanged.
