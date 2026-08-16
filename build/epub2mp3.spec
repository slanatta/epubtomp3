# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for EPUB to MP3.

Produces a one-folder build containing two executables that share a single set
of DLLs and data files:

    EpubToMP3.exe        the windowed GUI
    EpubToMP3-cli.exe    a console version, handy for troubleshooting

Build with:  pyinstaller build\\epub2mp3.spec --noconfirm --clean
"""
import glob
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all, collect_data_files, collect_dynamic_libs, collect_submodules,
    copy_metadata,
)

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent
SRC = ROOT / "src"
ICON = SPEC_DIR / "app.ico"

IS_WINDOWS = sys.platform.startswith("win")

# --------------------------------------------------------------------------- #
# Data files, DLLs and metadata that PyInstaller cannot infer on its own
# --------------------------------------------------------------------------- #
datas = []
binaries = []
hiddenimports = []

# kokoro_onnx ships config.json (the phoneme vocabulary) and reads its own
# version through importlib.metadata at import time - both are required.
datas += collect_data_files("kokoro_onnx")
datas += copy_metadata("kokoro-onnx")
hiddenimports += collect_submodules("kokoro_onnx")

# phonemizer-fork reads its version from package metadata on import and needs
# the files under phonemizer/share.
datas += collect_data_files("phonemizer")
datas += copy_metadata("phonemizer-fork")
hiddenimports += [
    "phonemizer",
    "phonemizer.backend",
    "phonemizer.backend.espeak",
    "phonemizer.backend.espeak.espeak",
    "phonemizer.backend.espeak.wrapper",
    "phonemizer.separator",
    "phonemizer.punctuation",
]

# espeakng-loader carries the espeak-ng shared library plus its data folder,
# and resolves them relative to its own __file__, so they must keep that layout.
datas += collect_data_files("espeakng_loader", include_py_files=False)
binaries += collect_dynamic_libs("espeakng_loader")

import espeakng_loader  # noqa: E402
_pkg = Path(espeakng_loader.__file__).parent
for pattern in ("espeak-ng*.dll", "libespeak-ng*.so*", "libespeak-ng*.dylib"):
    for found in glob.glob(str(_pkg / pattern)):
        binaries.append((found, "espeakng_loader"))

# onnxruntime: the native runtime DLLs plus its capi package.
datas += collect_data_files("onnxruntime")
binaries += collect_dynamic_libs("onnxruntime")
hiddenimports += ["onnxruntime", "onnxruntime.capi", "onnxruntime.capi._pybind_state"]

# phonemizer.backend imports its 'segments' backend unconditionally, even though
# we only ever use espeak. That pulls in segments -> csvw -> language_tags, all
# of which read JSON data files at import time. Miss any of them and the app
# builds cleanly but dies the moment it tries to speak.
for _pkg in ("segments", "csvw", "language_tags", "jsonschema",
             "jsonschema_specifications", "referencing", "rdflib", "isodate",
             "rfc3986", "uritemplate", "colorama", "clldutils", "attr", "attrs"):
    try:
        _datas, _binaries, _hidden = collect_all(_pkg)
        datas += _datas
        binaries += _binaries
        hiddenimports += _hidden
    except Exception:
        pass
    try:
        datas += copy_metadata(_pkg)
    except Exception:
        pass

hiddenimports += ["lameenc", "numpy", "mutagen", "mutagen.mp3", "mutagen.id3"]

if ICON.exists():
    datas.append((str(ICON), "."))

# Trim the obvious dead weight. onnxruntime drags in a lot of optional extras.
excludes = [
    "matplotlib", "scipy", "pandas", "PIL", "IPython", "notebook", "jupyter",
    "pytest", "setuptools", "pip", "wheel", "sympy", "torch", "tensorflow",
    "sounddevice", "soundfile", "test", "unittest", "pydoc_data",
    "tkinter.test", "lib2to3", "distutils",
]

block_cipher = None

# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
gui_a = Analysis(
    [str(SRC / "epub2mp3" / "gui_entry.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    cipher=block_cipher,
)

cli_a = Analysis(
    [str(SRC / "epub2mp3" / "cli_entry.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    cipher=block_cipher,
)

# The CLI's native dependencies are a subset of the GUI's, so both executables
# share one _internal folder: only the small pure-Python archive is duplicated.
gui_pyz = PYZ(gui_a.pure, gui_a.zipped_data, cipher=block_cipher)
cli_pyz = PYZ(cli_a.pure, cli_a.zipped_data, cipher=block_cipher)

gui_exe = EXE(
    gui_pyz,
    gui_a.scripts,
    [],
    exclude_binaries=True,
    name="EpubToMP3",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX is a magnet for antivirus false positives
    console=False,             # windowed application
    disable_windowed_traceback=False,
    icon=str(ICON) if ICON.exists() else None,
    version=str(SPEC_DIR / "version_info.txt")
    if (SPEC_DIR / "version_info.txt").exists() and IS_WINDOWS else None,
)

cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    [],
    exclude_binaries=True,
    name="EpubToMP3-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(ICON) if ICON.exists() else None,
)

coll = COLLECT(
    gui_exe,
    cli_exe,
    gui_a.binaries,
    gui_a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="EpubToMP3",
)
