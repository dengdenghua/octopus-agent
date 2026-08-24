# -*- mode: python ; coding: utf-8 -*-
# Linux PyInstaller spec. Mirrors packaging/macos/octopus-backend.spec.
# Differences from the macOS spec:
#   - entry script is the same platform-neutral `runtime.cli.main` entry
#   - UPX is kept disabled for consistency with the macOS backend (the Linux
#     backend is a glibc ELF bundle consumed inside Electron; enabling UPX here
#     is a size optimization that can be revisited without affecting packaging
#     stability)

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


repo_root = Path(SPECPATH).parents[1]
entry = repo_root / "packaging" / "windows" / "octopus_backend_entry.py"

hiddenimports = collect_submodules("runtime") + [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "multipart",
    "python_multipart",
]

datas = collect_data_files("runtime", include_py_files=False)
reflex_rules = repo_root / "data" / "reflex_rules.yaml"
if reflex_rules.exists():
    datas.append((str(reflex_rules), "data"))

a = Analysis(
    [str(entry)],
    pathex=[str(repo_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "tests",
        "frontend",
        "torch",
        "torchvision",
        "torchaudio",
        "transformers",
        "diffusers",
        "accelerate",
        "scipy",
        "sklearn",
        "scikit-learn",
        "pandas",
        "onnxruntime",
        "onnx",
        "tensorboard",
        "tensorflow",
        "keras",
        "matplotlib",
        "seaborn",
        "statsmodels",
        "sympy",
        "nltk",
        "spacy",
        "gensim",
        "xgboost",
        "lightgbm",
        "catboost",
        "cv2",
        "opencv-python",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="octopus-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)