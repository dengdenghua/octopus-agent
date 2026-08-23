# Desktop build bridge (legacy shell retired)

`frontend/electron/` is the only supported Electron shell and
`packaging/desktop/build.yml` is the only release configuration. The former
`extras/desktop/electron/` implementation remains only as archived source; no
package script or CI workflow publishes it.

This directory retains `build-backend-win.cjs`, the Windows PyInstaller helper,
and `prepare-codex-win.cjs`, which copies the exact official `@openai/codex`
Windows platform package pinned by `frontend/package.json` and
`frontend/pnpm-lock.yaml`. They write the fixed runtimes expected by the
canonical package to:

```text
extras/desktop/build/backend/octopus-backend.exe
extras/desktop/build/codex/bin/codex.exe
```

## Windows release build

From the repository root, use uv 0.11.25 to install the Python toolchain from
`uv.lock` and install the locked frontend dependencies. A production package is
never unsigned: set the exact source revision and an ephemeral/local code-signing
identity before invoking electron-builder, then run:

```powershell
pnpm --dir frontend install --frozen-lockfile
uv sync --locked --python 3.11.9 --extra desktop-core --extra desktop-build
$env:PYTHON_EXE = (Resolve-Path ".venv\Scripts\python.exe").Path
pnpm --dir extras/desktop backend:build:win
pnpm --dir frontend codex:prepare:win
pnpm --dir frontend build
$env:GITHUB_SHA = (git rev-parse HEAD)
$env:CSC_LINK = "<base64 PKCS#12 code-signing certificate>"
$env:CSC_KEY_PASSWORD = "<certificate password>"
pnpm --dir frontend electron:build:win
```

Do not put those values in the repository or a shell profile. Formal builds use
the protected GitHub Environment `windows-code-signing`; the workflow fails
before dependency setup when either required secret is absent. It requires an
RFC3161 timestamp and validates the installer, unpacked `Octopus.exe`, and
packaged backend, and packaged Codex with `Get-AuthenticodeSignature` before
uploading SHA-bound artifacts and `SHA256SUMS`. The proof covers `codex.exe`,
the code-mode host, command runner, sandbox setup helper, and bundled
`rg.exe`; it records each post-signing SHA-256, publisher, and trusted
timestamp identity.

For compatibility, `pnpm --dir extras/desktop electron:build:win` delegates to
those canonical frontend build scripts after generating the backend. It never
invokes the retired Electron entry point.

The Windows x64 installer is self-contained at runtime: packaged mode starts only
`resources/backend/octopus-backend.exe` and passes the absolute bundled
`resources/codex/bin/codex.exe` path to that backend. Missing executables fail
closed; the application does not fall back to system Python/uv/Codex, PATH, or
download dependencies on first launch. CI runs the bundled Codex App Server
help command, starts the backend from `win-unpacked`, and requires `/readyz`
before uploading artifacts. The prepared runtime also contains the exact Codex
0.149.0 LICENSE/NOTICE, component-specific `cargo-about 0.9.2` reports for the
Windows normal-runtime Rust dependency graphs, the Ratatui 0.30.2 MIT license,
and a separate `pcre2`-enabled report plus project license texts for ripgrep
15.2.0. A companion native provenance manifest and notice bundle cover the
reviewed vendored C/C++ sources, the pinned rusty_v8/V8 static archive, and
embedded ICU data that Cargo metadata alone cannot prove. Every shipped notice
is pinned in `octopus-codex-bundle.json` by SHA-256 and is checked again before
the packaged backend starts. Maintainers can reproduce or verify the Rust
reports with `extras/desktop/generate-codex-third-party-licenses.py` and the
native/data bundle with `extras/desktop/generate-codex-native-notices.py`
against the reviewed source commits and artifacts.

macOS and Linux release commands intentionally fail until equivalent bundled
backends and smoke tests exist.
