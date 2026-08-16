"""Frozen-application entry point for the console build."""
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(sys.executable).parent))
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from epub2mp3.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
