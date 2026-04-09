# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for TokenCounter.

Build with:  pyinstaller tokencounter.spec
Output:      dist/TokenCounter.exe (single file, no console)

IMPORTANT: Before building, ensure tiktoken encoding data is cached locally.
Run this once with network access:
    python -c "import tiktoken; tiktoken.get_encoding('o200k_base'); tiktoken.get_encoding('cl100k_base')"

The spec file will bundle the cached tiktoken data into the exe.
"""

import os
import tiktoken_ext.openai_public  # noqa: F401

tiktoken_cache = os.path.dirname(tiktoken_ext.openai_public.__file__)
user_cache = os.environ.get(
    "TIKTOKEN_CACHE_DIR",
    os.path.join(os.path.expanduser("~"), ".tiktoken_cache"),
)

datas = []
datas.append((tiktoken_cache, "tiktoken_ext/openai_public"))

if os.path.isdir(user_cache):
    for f in os.listdir(user_cache):
        if f.endswith(".tiktoken") or f.endswith(".bin"):
            datas.append((os.path.join(user_cache, f), "tiktoken_cache"))

assets_dir = os.path.join(os.path.dirname(os.path.abspath(SPEC)), "assets")
if os.path.isdir(assets_dir):
    datas.append((assets_dir, "assets"))

block_cipher = None

a = Analysis(
    [os.path.join("src", "tokencounter", "__main__.py")],
    pathex=[os.path.join(os.path.dirname(os.path.abspath(SPEC)), "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "comtypes",
        "comtypes.stream",
        "comtypes.gen",
        "tiktoken_ext.openai_public",
        "tiktoken_ext",
        "win32api",
        "win32gui",
        "win32clipboard",
        "win32event",
        "win32con",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[os.path.join("scripts", "runtime_hook.py")],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="TokenCounter",
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
    icon=os.path.join("assets", "icon.ico") if os.path.isfile(os.path.join("assets", "icon.ico")) else None,
)
