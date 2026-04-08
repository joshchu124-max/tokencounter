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
import sys
import tiktoken_ext.openai_public  # noqa: F401 — needed to find data files
import tiktoken

# Find tiktoken's cached encoding files
tiktoken_cache = os.path.dirname(tiktoken_ext.openai_public.__file__)

# Also include the user's tiktoken cache (downloaded .tiktoken files)
# Prefer the project-local tiktoken_cache directory, then env var, then default
project_cache = os.path.join(os.path.dirname(os.path.abspath(SPEC)), "tiktoken_cache")
user_cache = os.environ.get(
    "TIKTOKEN_CACHE_DIR",
    os.path.join(os.path.expanduser("~"), ".tiktoken_cache"),
)
cache_dir = project_cache if os.path.isdir(project_cache) else user_cache

datas = []

# Bundle the tiktoken_ext package (contains encoding registry)
datas.append((tiktoken_cache, "tiktoken_ext/openai_public"))

# Bundle any cached tiktoken files (both hash-named and .tiktoken/.bin files)
if os.path.isdir(cache_dir):
    for f in os.listdir(cache_dir):
        datas.append((os.path.join(cache_dir, f), "tiktoken_cache"))

# Bundle the assets directory (icon)
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
    console=False,  # Windowed (no console)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join("assets", "icon.ico") if os.path.isfile(os.path.join("assets", "icon.ico")) else None,
)
