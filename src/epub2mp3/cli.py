"""
cli.py - Headless converter.

Mostly used for testing the pipeline without a display, but it also gives the
frozen build a scriptable mode:

    epub2mp3-cli book.epub -o out\\folder --voice af_heart --speed 1.1
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import models
from .engine import Synthesizer, convert_book, list_voices
from .epubread import read_epub


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="epub2mp3-cli",
                                     description="Convert an EPUB into MP3 files.")
    parser.add_argument("epub", nargs="?", help="path to the .epub file")
    parser.add_argument("-o", "--out", default=None, help="output folder")
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--bitrate", type=int, default=64)
    parser.add_argument("--lang", default="en-us")
    parser.add_argument("--chapters", default="",
                        help="comma separated chapter numbers, e.g. 1,2,5")
    parser.add_argument("--list-chapters", action="store_true")
    parser.add_argument("--list-voices", action="store_true")
    parser.add_argument("--download-models", action="store_true")
    args = parser.parse_args(argv)

    if args.download_models:
        def show(name, done, total):
            pct = 100 * done / total if total else 0
            sys.stdout.write("\r%s %.0f%%   " % (name, pct))
            sys.stdout.flush()
        models.download_all(on_progress=show)
        print("\nModels ready in", models.model_dir())
        return 0

    model, voices = models.find_models()

    def need_model() -> bool:
        if model and voices:
            return True
        print("Voice model not found. Run with --download-models first.",
              file=sys.stderr)
        return False

    if args.list_voices:
        if not need_model():
            return 2
        for name in list_voices(voices):
            print(name)
        return 0

    if not args.epub:
        parser.error("an EPUB file is required")

    # Reading a book needs no speech model, so inspecting one always works -
    # which also makes this a usable check that the build is sound.
    book = read_epub(args.epub)
    print("%s - %s (%d chapters, %d characters)"
          % (book.title, book.author, len(book.chapters), book.char_count))

    if args.list_chapters:
        for chapter in book.chapters:
            print("%3d  %-55s %8d chars" % (chapter.index, chapter.title[:55],
                                            chapter.char_count))
        return 0

    if not need_model():
        return 2

    out = Path(args.out or (Path.home() / "Audiobooks" / book.title))
    selected = [int(x) for x in args.chapters.split(",") if x.strip()] or None

    synth = Synthesizer(model, voices)
    started = time.time()

    def show(p):
        if p.stage == "done":
            print("\n%s" % p.message)
            return
        if p.message and "skipped" in p.message:
            print("\n  ! chapter %d: %s" % (p.chapter_index, p.message))
        pct = 100 * p.chars_done / max(1, p.chars_total)
        sys.stdout.write("\r[%5.1f%%] ch %d/%d %-40s %6.1fs audio "
                         % (pct, p.chapter_index, p.chapter_total,
                            p.chapter_title[:40], p.seconds_written))
        sys.stdout.flush()

    files = convert_book(book, out, synth, voice=args.voice, speed=args.speed,
                         bitrate=args.bitrate, lang=args.lang,
                         selected=selected, on_progress=show)
    print("Wrote %d file(s) to %s in %.1fs" % (len(files), out, time.time() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
