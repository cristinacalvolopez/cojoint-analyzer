# -*- mode: python ; coding: utf-8 -*-
"""Empaqueta Cojoint Analyzer como app de macOS (doble clic, sin terminal).

Uso: pyinstaller --noconfirm CojointAnalyzer.spec
Genera dist/Cojoint Analyzer.app.
"""
from PyInstaller.utils.hooks import collect_all

datas = [("static", "static")]
binaries = []
hiddenimports = [
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
]

# pyreadstat y statsmodels cargan submódulos de forma perezosa que
# PyInstaller no detecta por análisis estático; collect_all se trae todo
# el paquete (algo más pesado, pero evita "ModuleNotFoundError" en tiempo
# de ejecución que solo se verían abriendo el log, no en la consola).
for pkg in ("pyreadstat", "statsmodels"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CojointAnalyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CojointAnalyzer",
)
app = BUNDLE(
    coll,
    name="Cojoint Analyzer.app",
    icon=None,
    bundle_identifier="es.usal.cojoint-analyzer",
    info_plist={
        "CFBundleName": "Cojoint Analyzer",
        "CFBundleDisplayName": "Cojoint Analyzer",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
        "LSUIElement": False,
    },
)
