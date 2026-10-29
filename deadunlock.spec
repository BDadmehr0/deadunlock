# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller configuration for the Linux GUI executable."""

from pathlib import Path

project_root = Path.cwd()

a = Analysis(
    ['launcher.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=[('version.txt', '.'), ('img/deadunlock_icon.png', 'img')],
    hiddenimports=['Xlib.ext.xtest'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='deadunlock',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
