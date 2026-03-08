# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules


hiddenimports = collect_submodules("accessible_output2.outputs") + [
    "pyopenalsoft",
    "pygame._sdl2.audio",
    "win32com.client",
]
binaries = collect_dynamic_libs("pyopenalsoft")

project_root = Path(SPEC).resolve().parent
datas = [
    (str(project_root / "assets"), "assets"),
]


a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name="SubwaySurfersBlind",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SubwaySurfersBlind",
)
