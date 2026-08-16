"""
engine.py - Text chunking, Kokoro synthesis and MP3 encoding.

Kept free of any GUI imports so it can be driven from a worker thread or from
the command line.
"""
from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence

import numpy as np

SAMPLE_RATE = 24000

# Kokoro's context window is 510 phonemes. Phonemes are usually a little
# shorter than the source text, so ~420 characters keeps every chunk safely
# inside a single pass while still giving useful progress granularity.
TARGET_CHUNK = 420
MAX_CHUNK = 600

_SENTENCE_END = re.compile(r"(?<=[.!?\"'’])\s+(?=[\"'“(\[A-Z0-9])")
_SOFT_SPLIT = re.compile(r"(?<=[,;:])\s+")


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #
@dataclass
class Chunk:
    text: str
    gap: float = 0.0     # seconds of silence to append after this chunk


def _hard_wrap(sentence: str, limit: int) -> List[str]:
    """Split an over-long sentence without cutting words in half."""
    pieces: List[str] = []
    for part in _SOFT_SPLIT.split(sentence):
        if not part:
            continue
        if len(part) <= limit:
            pieces.append(part)
            continue
        words, cur = part.split(" "), ""
        for word in words:
            if cur and len(cur) + len(word) + 1 > limit:
                pieces.append(cur)
                cur = word
            else:
                cur = (cur + " " + word).strip()
        if cur:
            pieces.append(cur)
    return pieces or [sentence[:limit]]


def chunk_text(text: str, target: int = TARGET_CHUNK,
               paragraph_gap: float = 0.45,
               sentence_gap: float = 0.0) -> List[Chunk]:
    """Split chapter text into synthesis-sized chunks on sentence boundaries."""
    chunks: List[Chunk] = []

    for para in [p.strip() for p in text.split("\n\n") if p.strip()]:
        sentences: List[str] = []
        for sentence in _SENTENCE_END.split(para.replace("\n", " ")):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > MAX_CHUNK:
                sentences.extend(_hard_wrap(sentence, target))
            else:
                sentences.append(sentence)

        current = ""
        para_chunks: List[Chunk] = []
        for sentence in sentences:
            if current and len(current) + len(sentence) + 1 > target:
                para_chunks.append(Chunk(current, sentence_gap))
                current = sentence
            else:
                current = (current + " " + sentence).strip()
        if current:
            para_chunks.append(Chunk(current, sentence_gap))

        if para_chunks:
            para_chunks[-1].gap = paragraph_gap
            chunks.extend(para_chunks)

    if chunks:
        chunks[-1].gap = max(chunks[-1].gap, 0.7)
    return chunks


# --------------------------------------------------------------------------- #
# Filenames
# --------------------------------------------------------------------------- #
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "con", "prn", "aux", "nul",
    *("com%d" % i for i in range(1, 10)),
    *("lpt%d" % i for i in range(1, 10)),
}


def safe_filename(name: str, fallback: str = "untitled", max_len: int = 70) -> str:
    """Make a string safe for a Windows filename."""
    name = _BAD_CHARS.sub("", name).replace("\n", " ").strip()
    name = re.sub(r"\s+", " ", name).strip(". ")
    if len(name) > max_len:
        name = name[:max_len].rsplit(" ", 1)[0].strip(". ") or name[:max_len]
    if not name or name.lower() in _RESERVED:
        name = fallback
    return name


# --------------------------------------------------------------------------- #
# MP3 encoding
# --------------------------------------------------------------------------- #
class Mp3Writer:
    """Streaming LAME encoder: constant memory regardless of chapter length."""

    def __init__(self, path: Path, bitrate: int = 64,
                 sample_rate: int = SAMPLE_RATE, quality: int = 3):
        import lameenc

        self.path = Path(path)
        self.tmp = self.path.with_suffix(self.path.suffix + ".part")
        self.encoder = lameenc.Encoder()
        self.encoder.set_bit_rate(bitrate)
        self.encoder.set_in_sample_rate(sample_rate)
        self.encoder.set_channels(1)
        self.encoder.set_quality(quality)          # 2 = high, 7 = fast
        try:
            self.encoder.silence()                  # suppress LAME's stderr chatter
        except Exception:
            pass
        self.tmp.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.tmp, "wb")
        self.samples = 0

    def write(self, audio: np.ndarray) -> None:
        pcm = np.clip(audio, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype(np.int16)
        self.samples += pcm.size
        data = self.encoder.encode(pcm.tobytes())
        if data:
            self._fh.write(data)

    def silence(self, seconds: float) -> None:
        if seconds > 0:
            self.write(np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32))

    @property
    def duration(self) -> float:
        return self.samples / float(SAMPLE_RATE)

    def close(self) -> Path:
        data = self.encoder.flush()
        if data:
            self._fh.write(data)
        self._fh.close()
        if self.path.exists():
            self.path.unlink()
        os.replace(self.tmp, self.path)
        return self.path

    def abort(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass
        try:
            self.tmp.unlink()
        except OSError:
            pass


def tag_mp3(path: Path, *, album: str, artist: str, title: str,
            track: int, total: int, year: str = "") -> None:
    """Write audiobook-friendly ID3 tags. Never fatal."""
    try:
        from mutagen.id3 import ID3, TALB, TPE1, TIT2, TRCK, TCON, TDRC, ID3NoHeaderError
        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("TALB"); tags.delall("TPE1"); tags.delall("TIT2")
        tags.delall("TRCK"); tags.delall("TCON")
        tags.add(TALB(encoding=3, text=album))
        tags.add(TPE1(encoding=3, text=artist))
        tags.add(TIT2(encoding=3, text=title))
        tags.add(TRCK(encoding=3, text="%d/%d" % (track, total)))
        tags.add(TCON(encoding=3, text="Audiobook"))
        if year:
            tags.delall("TDRC")
            tags.add(TDRC(encoding=3, text=year))
        tags.save(str(path), v2_version=3)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Kokoro wrapper
# --------------------------------------------------------------------------- #
class Synthesizer:
    """Loads the Kokoro ONNX model once and synthesises text chunks."""

    def __init__(self, model_path: Path, voices_path: Path,
                 threads: Optional[int] = None):
        self.model_path = Path(model_path)
        self.voices_path = Path(voices_path)
        self.threads = threads or max(1, (os.cpu_count() or 2))
        self._kokoro = None

    def load(self) -> None:
        if self._kokoro is not None:
            return
        import onnxruntime as rt
        from kokoro_onnx import Kokoro

        opts = rt.SessionOptions()
        opts.intra_op_num_threads = self.threads
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = rt.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.log_severity_level = 3

        try:
            session = rt.InferenceSession(
                str(self.model_path), opts, providers=["CPUExecutionProvider"]
            )
            self._kokoro = Kokoro.from_session(session, str(self.voices_path))
        except Exception:
            # from_session relies on a private attribute; fall back if it moves.
            self._kokoro = Kokoro(str(self.model_path), str(self.voices_path))

    @property
    def voices(self) -> List[str]:
        self.load()
        try:
            return sorted(self._kokoro.voices.files)      # NpzFile
        except AttributeError:
            return sorted(self._kokoro.voices.keys())

    def say(self, text: str, voice: str, speed: float,
            lang: str = "en-us") -> np.ndarray:
        self.load()
        audio, _sr = self._kokoro.create(text, voice=voice, speed=speed, lang=lang)
        return np.asarray(audio, dtype=np.float32)


def list_voices(voices_path: Path) -> List[str]:
    """Read voice names straight from the voices file (no model load needed)."""
    try:
        with np.load(str(voices_path)) as data:
            return sorted(data.files)
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# Conversion job
# --------------------------------------------------------------------------- #
@dataclass
class Progress:
    stage: str                 # "chapter" | "done" | "error" | "cancelled"
    chapter_index: int = 0
    chapter_total: int = 0
    chapter_title: str = ""
    chars_done: int = 0
    chars_total: int = 0
    seconds_written: float = 0.0
    elapsed: float = 0.0
    message: str = ""
    output: Optional[str] = None


class Cancelled(Exception):
    pass


def convert_book(book, out_dir: Path, synth: Synthesizer, *,
                 voice: str, speed: float, bitrate: int = 64,
                 lang: str = "en-us", skip_existing: bool = True,
                 selected: Optional[Sequence[int]] = None,
                 on_progress: Optional[Callable[[Progress], None]] = None,
                 should_cancel: Optional[Callable[[], bool]] = None) -> List[Path]:
    """Convert every selected chapter to its own tagged MP3."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    chapters = [c for c in book.chapters
                if selected is None or c.index in set(selected)]
    total_chars = sum(c.char_count for c in chapters) or 1
    chars_done = 0
    started = time.time()
    written: List[Path] = []
    n_total = len(chapters)
    attempted = 0          # chunks tried
    failed = 0             # chunks the engine could not speak

    def report(**kw):
        if on_progress:
            on_progress(Progress(
                chars_done=chars_done, chars_total=total_chars,
                chapter_total=n_total, elapsed=time.time() - started, **kw
            ))

    def check_cancel():
        if should_cancel and should_cancel():
            raise Cancelled()

    for position, chapter in enumerate(chapters, start=1):
        check_cancel()
        stem = "%02d - %s" % (chapter.index,
                              safe_filename(chapter.title, "Chapter %d" % chapter.index))
        target = out_dir / (stem + ".mp3")

        if skip_existing and target.exists() and target.stat().st_size > 1024:
            chars_done += chapter.char_count
            report(stage="chapter", chapter_index=position,
                   chapter_title=chapter.title, message="skipped (already exists)")
            written.append(target)
            continue

        report(stage="chapter", chapter_index=position,
               chapter_title=chapter.title, message="starting")

        chunks = chunk_text(chapter.text)
        writer = Mp3Writer(target, bitrate=bitrate)
        chapter_chars = 0
        try:
            for chunk in chunks:
                check_cancel()
                attempted += 1
                try:
                    audio = synth.say(chunk.text, voice, speed, lang)
                except Cancelled:
                    raise
                except Exception as exc:
                    # The very first passage failing means the speech engine
                    # itself is broken - reporting "done" would be a lie.
                    if attempted == 1:
                        raise RuntimeError(
                            "The speech engine could not start: %s" % exc) from exc
                    failed += 1
                    # A few odd passages are survivable; wholesale failure is not.
                    if failed > 8 and failed > attempted * 0.25:
                        raise RuntimeError(
                            "The speech engine failed on %d of %d passages. "
                            "Last error: %s" % (failed, attempted, exc)) from exc
                    report(stage="chapter", chapter_index=position,
                           chapter_title=chapter.title,
                           message="skipped a passage (%s)" % exc)
                    audio = np.zeros(0, dtype=np.float32)
                if audio.size:
                    writer.write(audio)
                writer.silence(chunk.gap)
                chapter_chars += len(chunk.text)
                chars_done += len(chunk.text)
                report(stage="chapter", chapter_index=position,
                       chapter_title=chapter.title,
                       seconds_written=writer.duration)
            path = writer.close()
        except Cancelled:
            writer.abort()
            report(stage="cancelled", chapter_index=position,
                   chapter_title=chapter.title)
            raise
        except Exception:
            writer.abort()
            raise

        tag_mp3(path, album=book.title, artist=book.author,
                title=chapter.title, track=chapter.index,
                total=len(book.chapters))
        written.append(path)
        # Reconcile the estimate with the real character count.
        chars_done += max(0, chapter.char_count - chapter_chars)

    report(stage="done", chapter_index=n_total,
           message="%d file(s) written" % len(written),
           output=str(out_dir))
    return written
