# Octopus Desktop Shell · Optional Electron Wrapper

> The desktop shell is **opt-in**. The web frontend (`frontend/`) is the canonical UI; this wrapper just bundles it into a desktop installer for users who want a self-contained app.

## When to use this

- You want a single-file installer (`.exe` / `.dmg` / `.AppImage`) for end users
- You want auto-update via GitHub Releases
- You want Octopus to feel like a desktop app rather than a browser tab

## When **not** to use this

- You're running Octopus self-hosted on a server — use `frontend/` directly
- You're a developer hacking on Octopus — use `pnpm --dir ../../frontend dev`
- You're worried about install size — desktop bundle is ~200MB; web frontend is ~30MB

## Build

```bash
cd extras/desktop
pnpm install
pnpm electron:build:win    # or :mac / :linux
```

The build pipeline:
1. Generates icons (`generate-icons.cjs`)
2. Stages bundled agents (`prepare-desktop-agents.cjs`)
3. (Windows only) PyInstaller-bundles the Python backend (`build-backend-win.cjs`)
4. Builds the Vite frontend in `../../frontend/dist/`
5. Wraps everything with electron-builder into `release/`

## Develop

```bash
cd extras/desktop
pnpm install
pnpm electron:dev           # Backend + Vite + Electron, hot-reload
```

## Files

| File | Purpose |
|---|---|
| `electron/main.cjs` | Electron main process — window, IPC, updater |
| `electron/preload.cjs` | Renderer-side API bridge |
| `generate-icons.cjs` | Generates `.ico` / `.icns` / `.png` from one source |
| `prepare-desktop-agents.cjs` | Stages the bundled agent skill packs |
| `build-backend-win.cjs` | Wraps the Python backend with PyInstaller (Windows) |
| `package.json` | Desktop-only deps: `electron`, `electron-builder`, `electron-updater` |
| `build/` | electron-builder build resources (icons, backend exe) |

## Why was this moved out of `frontend/`?

Before this split, `pnpm install` in `frontend/` always pulled `electron` (~150MB) and `electron-builder` (~50MB), even for users who only wanted the web UI or were running on a CI runner. Moving the desktop wrapper to `extras/desktop/` keeps the web frontend lean while preserving the option to ship a native installer.
