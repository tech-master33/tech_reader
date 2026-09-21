# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for TechReader (onedir, windowed, fast build: no UPX).
#
# Bundled alongside the code:
#   start.wav / exit.wav                      -> _internal/  (SRC_DIR lookups)
#   techreader_keyboard.dll                   -> _internal/native/
# comtypes.gen.UIAutomationClient is generated at runtime on dev machines,
# so it is listed as a hidden import to guarantee it is frozen.

a = Analysis(
    ['src\\main.py'],
    pathex=[],
    binaries=[
        ('src\\native\\techreader_keyboard.dll', 'native'),
    ],
    datas=[
        ('src\\start.wav', '.'),
        ('src\\exit.wav', '.'),
    ],
    hiddenimports=[
        'comtypes',
        'comtypes.client',
        'comtypes.gen.UIAutomationClient',
        'pythoncom',
        'keyboard',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'pydoc_data',
        'test',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='screenreader',
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
    name='screenreader',
)
