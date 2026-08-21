# Desktop build bridge (legacy shell retired)

`frontend/electron/` is the only supported Electron shell and
`packaging/desktop/build.yml` is the only release configuration. The former
`extras/desktop/electron/` implementation remains only as archived source; no
package script or CI workflow publishes it.

This directory retains `build-backend-win.cjs`, the Windows PyInstaller helper.
It writes the fixed backend expected by the canonical package to:

```text
extras/desktop/build/backend/octopus-backend.exe
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
packaged backend with `Get-AuthenticodeSignature` before uploading SHA-bound
artifacts and `SHA256SUMS`.

For compatibility, `pnpm --dir extras/desktop electron:build:win` delegates to
those canonical frontend build scripts after generating the backend. It never
invokes the retired Electron entry point.

The Windows installer is self-contained at runtime: packaged mode starts only
`resources/backend/octopus-backend.exe`. Missing executables fail closed; the
application does not fall back to system Python/uv or download dependencies on
first launch. CI additionally starts the executable from `win-unpacked` and
requires `/readyz` before uploading artifacts.

macOS and Linux release commands intentionally fail until equivalent bundled
backends and smoke tests exist.
