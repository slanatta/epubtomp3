"""
models.py - Locating and downloading the Kokoro model files.

The two files total roughly 330 MB and are downloaded once, on first run, into
the user's per-user application data folder. Nothing here needs admin rights,
so the installer can be a plain per-user install.
"""
from __future__ import annotations

import os
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, List, Optional, Tuple

APP_NAME = "EpubToMP3"

MODEL_FILE = "kokoro-v1.0.onnx"
VOICES_FILE = "voices-v1.0.bin"

# Approximate sizes, used only for the progress bar before the server replies.
EXPECTED_SIZE = {MODEL_FILE: 310_000_000, VOICES_FILE: 27_000_000}

# Primary source is the kokoro-onnx project; the second is an identical mirror.
SOURCES = {
    MODEL_FILE: [
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
        "https://github.com/nazdridoy/kokoro-tts/releases/download/v1.0.0/kokoro-v1.0.onnx",
    ],
    VOICES_FILE: [
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
        "https://github.com/nazdridoy/kokoro-tts/releases/download/v1.0.0/voices-v1.0.bin",
    ],
}

# A file smaller than this is certainly a truncated download or an error page.
MIN_SIZE = {MODEL_FILE: 100_000_000, VOICES_FILE: 5_000_000}


class DownloadCancelled(Exception):
    pass


def app_data_dir() -> Path:
    """Per-user writable folder for models and logs."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / APP_NAME


def model_dir() -> Path:
    override = os.environ.get("KOKORO_MODEL_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return app_data_dir() / "models"


def search_dirs() -> List[Path]:
    """Places a model pair might already exist, best first."""
    dirs = [model_dir()]
    override = os.environ.get("KOKORO_MODEL_DIR", "").strip()
    if override:
        dirs.append(Path(override).expanduser())
    # Alongside the executable, so the folder can be copied to another PC.
    exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) \
        else Path(__file__).resolve().parent
    dirs += [exe_dir / "models", exe_dir]
    dirs += [
        Path.home() / "kokoro-models",
        Path.home() / ".cache" / "kokoro",
        Path.home() / "kokoro-tts",
    ]
    seen, unique = set(), []
    for d in dirs:
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


def find_models() -> Tuple[Optional[Path], Optional[Path]]:
    """Return (model_path, voices_path) if a usable pair is found."""
    for d in search_dirs():
        if not d.is_dir():
            continue
        model = d / MODEL_FILE
        voices = d / VOICES_FILE
        if not model.is_file():
            found = sorted(d.glob("kokoro*.onnx"))
            model = found[0] if found else model
        if not voices.is_file():
            found = sorted(d.glob("voices*.bin"))
            voices = found[0] if found else voices
        if model.is_file() and voices.is_file():
            if model.stat().st_size > MIN_SIZE[MODEL_FILE] and \
               voices.stat().st_size > MIN_SIZE[VOICES_FILE]:
                return model, voices
    return None, None


def missing_files() -> List[str]:
    model, voices = find_models()
    if model and voices:
        return []
    return [MODEL_FILE, VOICES_FILE]


def free_space(path: Path) -> int:
    try:
        target = path
        while not target.exists() and target.parent != target:
            target = target.parent
        return shutil.disk_usage(str(target)).free
    except Exception:
        return 1 << 62


def download_file(name: str, dest_dir: Path,
                  on_progress: Optional[Callable[[str, int, int], None]] = None,
                  should_cancel: Optional[Callable[[], bool]] = None) -> Path:
    """Download one model file with resume-safe temp naming."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / name
    tmp = dest_dir / (name + ".part")
    last_error: Optional[Exception] = None

    for url in SOURCES[name]:
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "EpubToMP3/1.0"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                total = int(response.headers.get("Content-Length") or
                            EXPECTED_SIZE.get(name, 0))
                done = 0
                with open(tmp, "wb") as fh:
                    while True:
                        if should_cancel and should_cancel():
                            raise DownloadCancelled()
                        block = response.read(1 << 20)
                        if not block:
                            break
                        fh.write(block)
                        done += len(block)
                        if on_progress:
                            on_progress(name, done, total)
            if tmp.stat().st_size < MIN_SIZE.get(name, 1):
                raise IOError("download was incomplete (%d bytes)" % tmp.stat().st_size)
            if final.exists():
                final.unlink()
            os.replace(tmp, final)
            return final
        except DownloadCancelled:
            tmp.unlink(missing_ok=True)
            raise
        except Exception as exc:
            last_error = exc
            tmp.unlink(missing_ok=True)
            continue

    raise IOError("Could not download %s: %s" % (name, last_error))


def download_all(dest_dir: Optional[Path] = None,
                 on_progress: Optional[Callable[[str, int, int], None]] = None,
                 should_cancel: Optional[Callable[[], bool]] = None) -> Tuple[Path, Path]:
    dest = Path(dest_dir) if dest_dir else model_dir()
    needed = EXPECTED_SIZE[MODEL_FILE] + EXPECTED_SIZE[VOICES_FILE]
    if free_space(dest) < needed * 1.15:
        raise IOError(
            "Not enough free disk space in %s - about 400 MB is needed." % dest
        )
    model = dest / MODEL_FILE
    voices = dest / VOICES_FILE
    if not (model.is_file() and model.stat().st_size > MIN_SIZE[MODEL_FILE]):
        model = download_file(MODEL_FILE, dest, on_progress, should_cancel)
    if not (voices.is_file() and voices.stat().st_size > MIN_SIZE[VOICES_FILE]):
        voices = download_file(VOICES_FILE, dest, on_progress, should_cancel)
    return model, voices
