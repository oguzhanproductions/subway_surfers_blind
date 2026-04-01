# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.utils.hooks import collect_submodules

binaries = []
hiddenimports = ['accessible_output2.outputs', 'pyopenalsoft', 'pygame._sdl2.audio', 'win32com.client']
binaries += collect_dynamic_libs('pyopenalsoft')
hiddenimports += collect_submodules('accessible_output2.outputs')


def collect_project_asset_files(asset_root: str) -> list[tuple[str, str]]:
    root = Path(asset_root)
    return [
        (str(path), str(Path(asset_root) / path.relative_to(root).parent))
        for path in root.rglob('*')
        if path.is_file()
    ]


datas = [('server.json', '.')]
datas += collect_project_asset_files('assets')


a = Analysis(
    ['main.py'],
    pathex=[],
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
    a.binaries,
    a.datas,
    [],
    name='SubwaySurfersBlind',
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
)
