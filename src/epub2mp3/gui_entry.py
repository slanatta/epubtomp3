"""Frozen-application entry point for the windowed GUI.

PyInstaller wants a plain script rather than a package, and a windowed build has
no console, so an early crash would otherwise vanish silently. Anything that
escapes is written to a log file and shown in a message box.
"""
import os
import sys
import traceback
from pathlib import Path

if getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(sys.executable).parent))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _crash_log() -> Path:
    try:
        from epub2mp3.models import app_data_dir
        folder = app_data_dir()
    except Exception:
        folder = Path(os.environ.get("TEMP", ".")) / "EpubToMP3"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "error.log"


def main() -> int:
    try:
        from epub2mp3.app import main as gui_main
        return gui_main()
    except SystemExit:
        raise
    except BaseException:
        report = traceback.format_exc()
        path = _crash_log()
        try:
            path.write_text(report, encoding="utf-8")
        except Exception:
            path = None
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "EPUB to MP3 could not start",
                "%s\n\n%s" % (report.strip().splitlines()[-1],
                              ("Details saved to:\n%s" % path) if path else ""))
        except Exception:
            sys.stderr.write(report)
        return 1


if __name__ == "__main__":
    sys.exit(main())
