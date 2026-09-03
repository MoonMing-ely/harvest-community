# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

keyring_data, keyring_binaries, keyring_hidden = collect_all("keyring")

analysis = Analysis(
    ["src/harvest/__main__.py"],
    pathex=["src"],
    binaries=keyring_binaries,
    datas=keyring_data,
    hiddenimports=keyring_hidden,
    excludes=["pytest"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="harvest",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
