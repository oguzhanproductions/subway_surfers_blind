# -*- mode: python ; coding: utf-8 -*-
import os
import struct
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.utils.hooks import collect_submodules

binaries = []
hiddenimports = ['accessible_output2.outputs', 'pyopenalsoft', 'pygame._sdl2.audio', 'win32com.client']
binaries += collect_dynamic_libs('pyopenalsoft')
hiddenimports += collect_submodules('accessible_output2.outputs')


def collect_project_asset_files(asset_root: str) -> list[tuple[str, str]]:
    root = Path(asset_root)
    if not root.is_dir():
        return []
    return [
        (str(path), str(Path(asset_root) / path.relative_to(root).parent))
        for path in root.rglob('*')
        if path.is_file()
    ]


def collect_existing_binaries(paths: list[Path], destination: str = '.') -> list[tuple[str, str]]:
    collected: list[tuple[str, str]] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.resolve()
        key = os.path.normcase(str(resolved))
        if not resolved.is_file() or key in seen:
            continue
        seen.add(key)
        collected.append((str(resolved), destination))
    return collected


def collect_python_runtime_binaries() -> list[tuple[str, str]]:
    python_root = Path(sys.base_prefix)
    runtime_candidates = [
        python_root / 'python311.dll',
        python_root / 'python3.dll',
        python_root / 'vcruntime140.dll',
        python_root / 'vcruntime140_1.dll',
        python_root / 'msvcp140.dll',
        python_root / 'msvcp140_1.dll',
        python_root / 'msvcp140_2.dll',
        python_root / 'concrt140.dll',
    ]
    return collect_existing_binaries(runtime_candidates)


def collect_ucrt_binaries() -> list[tuple[str, str]]:
    architecture = 'x64' if struct.calcsize('P') * 8 == 64 else 'x86'
    windows_kit_roots = [
        Path(r'C:\Program Files (x86)\Windows Kits\10\Redist'),
        Path(r'C:\Program Files\Windows Kits\10\Redist'),
    ]
    for root in windows_kit_roots:
        if not root.exists():
            continue
        versioned_dirs = sorted(
            (path for path in root.iterdir() if path.is_dir() and (path / 'ucrt' / 'DLLs' / architecture).is_dir()),
            reverse=True,
        )
        search_roots = versioned_dirs + [root]
        for candidate_root in search_roots:
            ucrt_dir = candidate_root / 'ucrt' / 'DLLs' / architecture
            if not ucrt_dir.is_dir():
                continue
            api_set_files = list(ucrt_dir.glob('api-ms-win-crt-*.dll'))
            if not api_set_files:
                continue
            return collect_existing_binaries([ucrt_dir / 'ucrtbase.dll', *api_set_files])
    return []


datas = [('server.json', '.')]
datas += collect_project_asset_files('assets')
datas += collect_project_asset_files('langs')
binaries += collect_python_runtime_binaries()
binaries += collect_ucrt_binaries()


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
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
