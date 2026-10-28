# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import json


project = Path(SPECPATH).resolve().parent
desktop = project / "desktop"
package = json.loads((project / "package.json").read_text(encoding="utf-8"))
exe_name = f"dsh-pet-gujiguji-{package['version']}"

a = Analysis(
    [str(desktop / "pet-window.pyw")],
    pathex=[str(project), str(desktop)],
    binaries=[],
    datas=[
        (
            str(project / "assets"),
            "assets",
        ),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name=exe_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
