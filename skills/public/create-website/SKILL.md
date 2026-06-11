---
name: create-website
description: |
  Build real, multi-file web projects the user can open, run, and extend.

  **Capabilities**:
  1. **Vanilla trio** (HTML + CSS + JS, 3 files, no build step) — the default
     for small standalone pages that don't need a package manager.
  2. **Vite + TypeScript** — when the user wants a "real" app, multiple
     components, hot-reload, or anything with obvious state/routing.

  **When to use**:
  - User requests a new website, webpage, app, landing page, dashboard, etc.
  - Keywords: "create website", "build website", "做个网页", "写个应用",
    "做一个 to-do 应用", "钢琴网页", "计算器", "dashboard", "landing page"

  **Not for**:
  - One-line bug fixes to an existing file (use `read_file` / `str_replace`)
  - Pure research / explanation (use the research workflow)

enabled: true
---

# Create Website / Web App

Build a **real, runnable, multi-file** web project the user can open with a
browser or `pnpm run dev`. The legacy "single self-contained HTML" output is
a last-resort fallback, not the default — users expect professional project
structure.

## ⚠️ Critical Rules

1. **Multi-file by default.** Split HTML, CSS, and JS into separate files.
   A piano app is not an 800-line `index.html`. A calculator is not an
   800-line `index.html`. Each concern in its own file.
2. **Copy templates verbatim.** This skill folder has ready-made templates
   under `templates/`. Do NOT re-invent `package.json` or `vite.config.ts`
   — read the template, copy it exactly, then fill in the app-specific
   files (components, styles, logic).
3. **Output to `/mnt/user-data/outputs/<project-name>/`.** Never scatter
   loose files at the root. The user should be able to `cd
   /mnt/user-data/outputs/<project-name> && pnpm install && pnpm dev`.
4. **Single-file HTML is opt-in only.** Use it only if the user explicitly
   says "一个文件 / single file / self-contained HTML" OR the task is
   genuinely trivial (a 20-line hello-world page). When in doubt, use the
   vanilla trio.

## Decision tree

```
User asks for a website / web app
    │
    ├── Task involves state, routing, multiple views,
    │   components, or the word "app" / "应用" / "dashboard"
    │        ↓
    │    USE: templates/vite-ts  (TypeScript + Vite + hot-reload)
    │
    ├── Static page or small widget, no build step wanted
    │        ↓
    │    USE: templates/vanilla-trio  (HTML + CSS + JS, three files)
    │
    └── User explicitly asked for one file
             ↓
         USE: inline single HTML (rare)
```

## Workflow

### Step 1 — Plan via `write_todos`

ALWAYS start with a `write_todos` call listing 5+ concrete steps covering:
scaffold → core modules → UI → interactions → verification. Mark the first
step `in_progress`, the rest `pending`. (See the global planning contract
in the main system prompt — this is not optional.)

### Step 2 — Pick the template and read it

```text
ls /mnt/skills/public/create-website/templates/vanilla-trio    ← or vite-ts
read_file  each file in the template
```

### Step 3 — Scaffold the project by copying template files verbatim

For each template file, `write_file` into
`/mnt/user-data/outputs/<project-name>/<same-path>` with the EXACT template
content. Rename placeholders (`{{APP_NAME}}`, `{{APP_TITLE}}`,
`{{YEAR}}`) to project-specific values. Do NOT skip `package.json`, do NOT
skip config files. The project must install cleanly.

Between scaffold and app code, re-call `write_todos` to flip "scaffold"
→ completed, "core module" → in_progress. Mirror this pattern after every
step — the user is watching the plan panel tick forward.

### Step 4 — Write the app-specific files

These are the files that differ per project — components, styles that
aren't reset CSS, business logic. Keep each file small and focused. If
you're writing a single file over 400 lines, split it.

### Step 5 — Verify & auto-launch the live preview

If the template is **vite-ts** (or any project with a ``package.json``):

1. Call ``dev_server_start`` with the project path you wrote to. It runs
   ``pnpm install && pnpm run dev`` (falls back to npm / yarn based on
   which lockfile is present, and which PM is on PATH), allocates a
   port in the 5173-range, and blocks until the dev server is reachable.
2. The tool's response includes ``preview_url``. The frontend's Code
   mode watches tool results for this field and auto-pipes it into the
   live-preview iframe, so the user sees their running app the moment
   it boots — no manual refresh.
3. If the tool returns ``{"error": "..."}``, surface the error message
   to the user and point them at the ``log_path`` it returned.

If the template is **vanilla-trio** (no ``package.json``), the existing
``preview_start`` tool is enough — it serves the static files on a local
HTTP port and returns the same ``preview_url`` shape. Call it with
``file_path=".../index.html"``.

Then report to the user: "built at ``<path>``, dev server live at
``<preview_url>``". Do NOT tell the user to run pnpm themselves — you
just did.

## Template inventory

```text
templates/
├── vanilla-trio/        ← index.html + style.css + script.js
│   ├── index.html
│   ├── style.css
│   └── script.js
└── vite-ts/             ← pnpm + vite + TS, modular components
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── index.html
    ├── README.md
    └── src/
        ├── main.ts
        └── style.css
```

Both are minimal but working. Add your app's files alongside them.

## Output format

| Template    | Deliverable                                      |
|-------------|--------------------------------------------------|
| vanilla-trio | Folder with `index.html`, `style.css`, `script.js` (optional extras) |
| vite-ts      | Folder with full Vite project structure, ready for `pnpm install && pnpm dev` |
| inline HTML  | Single `index.html` — only if user asked for it  |

After writing all files, call `present_files` so the user sees the deliverable.
