# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[('C:\\Users\\Rafael\\AppData\\Local\\Programs\\Python\\Python314\\python314.dll', '.')],
    datas=[('logo_casa_das_massas.ico', '.'), ('logo_casa_das_massas.png', '.'), ('pdv_database.db', '.')],
    hiddenimports=['pandas', 'numpy', 'win32print', 'win32ui'],
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
    name='app',
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
    icon=['logo_casa_das_massas.ico'],
)
