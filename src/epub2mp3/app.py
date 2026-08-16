"""
app.py - Tkinter front end for the EPUB to MP3 converter.

Everything heavy happens on worker threads; the GUI thread only drains a queue
on a timer, so the window never freezes during a long conversion.
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from pathlib import Path
from typing import List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import models
from .epubread import Book, read_epub
from .engine import Progress, Synthesizer, convert_book, list_voices, safe_filename

APP_TITLE = "EPUB to MP3"
VERSION = "1.0.0"

CHARS_PER_SECOND = 14.5      # rough speech rate, for duration estimates
IS_WINDOWS = sys.platform.startswith("win")

CHECKED, UNCHECKED = "☑", "☐"

# Friendly labels for the common Kokoro voices; anything else shows its raw id.
VOICE_LABELS = {
    "af_heart": "Heart - US female (warm)",
    "af_bella": "Bella - US female",
    "af_nicole": "Nicole - US female (soft)",
    "af_sarah": "Sarah - US female",
    "af_sky": "Sky - US female",
    "af_nova": "Nova - US female",
    "af_aoede": "Aoede - US female",
    "af_kore": "Kore - US female",
    "af_jessica": "Jessica - US female",
    "af_river": "River - US female",
    "af_alloy": "Alloy - US female",
    "am_adam": "Adam - US male",
    "am_michael": "Michael - US male",
    "am_echo": "Echo - US male",
    "am_eric": "Eric - US male",
    "am_liam": "Liam - US male",
    "am_onyx": "Onyx - US male (deep)",
    "am_puck": "Puck - US male",
    "am_fenrir": "Fenrir - US male",
    "bf_emma": "Emma - UK female",
    "bf_alice": "Alice - UK female",
    "bf_isabella": "Isabella - UK female",
    "bf_lily": "Lily - UK female",
    "bm_george": "George - UK male",
    "bm_lewis": "Lewis - UK male",
    "bm_daniel": "Daniel - UK male",
    "bm_fable": "Fable - UK male",
}

LANGS = [
    ("English (US)", "en-us"),
    ("English (UK)", "en-gb"),
    ("French", "fr-fr"),
    ("Italian", "it"),
    ("Spanish", "es"),
    ("Portuguese (BR)", "pt-br"),
    ("Hindi", "hi"),
    ("Japanese", "ja"),
    ("Chinese", "cmn"),
]


def human_time(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return "%dh %02dm" % (hours, minutes)
    if minutes:
        return "%dm %02ds" % (minutes, secs)
    return "%ds" % secs


def open_folder(path: str) -> None:
    try:
        if IS_WINDOWS:
            os.startfile(path)                     # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        webbrowser.open("file://" + str(path))


# --------------------------------------------------------------------------- #
# First-run model download dialog
# --------------------------------------------------------------------------- #
class DownloadDialog(tk.Toplevel):
    """Modal, cancellable download of the two Kokoro model files."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.title("First-time setup")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self.ok = False
        self._cancelled = False
        self._queue: "queue.Queue[tuple]" = queue.Queue()

        frame = ttk.Frame(self, padding=18)
        frame.grid(sticky="nsew")

        ttk.Label(
            frame, font=("Segoe UI", 11, "bold"),
            text="Downloading the speech model",
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            frame, wraplength=430, justify="left", foreground="#444",
            text=("%s needs two voice model files (about 330 MB in total). "
                  "This happens once - afterwards the program works completely "
                  "offline.\n\nSaving to: %s" % (APP_TITLE, models.model_dir())),
        ).grid(row=1, column=0, sticky="w", pady=(6, 14))

        self.bar = ttk.Progressbar(frame, length=440, mode="determinate", maximum=1000)
        self.bar.grid(row=2, column=0, sticky="ew")

        self.detail = ttk.Label(frame, text="Connecting...", foreground="#555")
        self.detail.grid(row=3, column=0, sticky="w", pady=(6, 12))

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, sticky="e")
        self.cancel_btn = ttk.Button(buttons, text="Cancel", command=self._cancel)
        self.cancel_btn.grid(row=0, column=0)

        self.update_idletasks()
        self._centre(parent)

        threading.Thread(target=self._worker, daemon=True).start()
        self.after(100, self._drain)

    def _centre(self, parent: tk.Misc) -> None:
        try:
            x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
            self.geometry("+%d+%d" % (max(0, x), max(0, y)))
        except Exception:
            pass

    def _worker(self) -> None:
        def progress(name, done, total):
            self._queue.put(("progress", name, done, total))
        try:
            models.download_all(on_progress=progress,
                                should_cancel=lambda: self._cancelled)
            self._queue.put(("done", None, 0, 0))
        except models.DownloadCancelled:
            self._queue.put(("cancelled", None, 0, 0))
        except Exception as exc:
            self._queue.put(("error", str(exc), 0, 0))

    def _drain(self) -> None:
        try:
            while True:
                kind, name, done, total = self._queue.get_nowait()
                if kind == "progress":
                    pct = (done / total) if total else 0
                    self.bar["value"] = pct * 1000
                    self.detail.config(
                        text="%s - %.0f MB of %.0f MB (%.0f%%)"
                             % (name, done / 1e6, total / 1e6, pct * 100)
                    )
                elif kind == "done":
                    self.ok = True
                    self.destroy()
                    return
                elif kind == "cancelled":
                    self.destroy()
                    return
                elif kind == "error":
                    messagebox.showerror(
                        "Download failed",
                        "%s\n\nCheck your internet connection and try again, or "
                        "download the two files manually and point the program at "
                        "them with the Model folder button." % name,
                        parent=self,
                    )
                    self.destroy()
                    return
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def _cancel(self) -> None:
        self._cancelled = True
        self.cancel_btn.config(state="disabled")
        self.detail.config(text="Cancelling...")


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("%s %s" % (APP_TITLE, VERSION))
        root.minsize(760, 620)

        self.book: Optional[Book] = None
        self.epub_path = tk.StringVar()
        self.out_dir = tk.StringVar(value=str(Path.home() / "Audiobooks"))
        self.out_dir_is_auto = True      # replaced per book until the user picks one
        self.voice = tk.StringVar()
        self.lang = tk.StringVar(value="English (US)")
        self.speed = tk.DoubleVar(value=1.0)
        self.bitrate = tk.StringVar(value="64 kbps (recommended)")
        self.skip_existing = tk.BooleanVar(value=True)

        self.model_path: Optional[Path] = None
        self.voices_path: Optional[Path] = None
        self.synth: Optional[Synthesizer] = None

        self.worker: Optional[threading.Thread] = None
        self.cancel_flag = False
        self.running = False
        self.checked: set = set()
        self.queue: "queue.Queue[tuple]" = queue.Queue()

        self._build()
        self.root.after(60, self._drain)
        self.root.after(200, self._startup)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def open_path(self, path: str) -> None:
        """Load a book handed to us on the command line (Explorer right-click)."""
        self.epub_path.set(path)
        self.root.after(400, lambda: self._load_book(path))

    # -- layout ------------------------------------------------------------ #
    def _build(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("vista" if IS_WINDOWS else style.theme_use())
        except tk.TclError:
            pass

        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)

        # --- files --------------------------------------------------------- #
        files = ttk.LabelFrame(outer, text="Book", padding=10)
        files.grid(row=0, column=0, sticky="ew")
        files.columnconfigure(1, weight=1)

        ttk.Label(files, text="EPUB file").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.epub_entry = ttk.Entry(files, textvariable=self.epub_path)
        self.epub_entry.grid(row=0, column=1, sticky="ew")
        self.epub_btn = ttk.Button(files, text="Choose...", command=self._pick_epub,
                                   width=12)
        self.epub_btn.grid(row=0, column=2, padx=(8, 0))

        ttk.Label(files, text="Save MP3s to").grid(row=1, column=0, sticky="w",
                                                   padx=(0, 8), pady=(8, 0))
        self.out_entry = ttk.Entry(files, textvariable=self.out_dir)
        self.out_entry.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        self.out_btn = ttk.Button(files, text="Choose...", command=self._pick_out,
                                  width=12)
        self.out_btn.grid(row=1, column=2, padx=(8, 0), pady=(8, 0))

        self.book_label = ttk.Label(files, text="No book loaded.", foreground="#555")
        self.book_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))

        # --- chapters ------------------------------------------------------ #
        chapters = ttk.LabelFrame(outer, text="Chapters", padding=10)
        chapters.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        outer.rowconfigure(1, weight=1)
        chapters.columnconfigure(0, weight=1)
        chapters.rowconfigure(0, weight=1)

        columns = ("sel", "num", "title", "len", "est")
        self.tree = ttk.Treeview(chapters, columns=columns, show="headings",
                                 selectmode="browse", height=9)
        for key, text, width, anchor in (
            ("sel", "", 34, "center"),
            ("num", "#", 42, "center"),
            ("title", "Chapter", 380, "w"),
            ("len", "Words", 80, "e"),
            ("est", "Approx. length", 120, "e"),
        ):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key == "title"))
        self.tree.grid(row=0, column=0, sticky="nsew")

        bar = ttk.Scrollbar(chapters, orient="vertical", command=self.tree.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.bind("<Button-1>", self._toggle_click)
        self.tree.bind("<space>", self._toggle_selected)

        row = ttk.Frame(chapters)
        row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(row, text="Select all", command=lambda: self._set_all(True),
                   width=12).pack(side="left")
        ttk.Button(row, text="Select none", command=lambda: self._set_all(False),
                   width=12).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(row, text="Skip chapters already converted",
                        variable=self.skip_existing).pack(side="left", padx=(16, 0))

        # --- voice --------------------------------------------------------- #
        voice_box = ttk.LabelFrame(outer, text="Narration", padding=10)
        voice_box.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        voice_box.columnconfigure(1, weight=1)
        voice_box.columnconfigure(4, weight=1)

        ttk.Label(voice_box, text="Voice").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.voice_box = ttk.Combobox(voice_box, textvariable=self.voice,
                                      state="readonly", width=30)
        self.voice_box.grid(row=0, column=1, sticky="w")
        self.preview_btn = ttk.Button(voice_box, text="Preview", width=10,
                                      command=self._preview)
        self.preview_btn.grid(row=0, column=2, padx=(8, 0))

        ttk.Label(voice_box, text="Language").grid(row=0, column=3, sticky="e",
                                                   padx=(18, 8))
        ttk.Combobox(voice_box, textvariable=self.lang, state="readonly", width=16,
                     values=[name for name, _ in LANGS]).grid(row=0, column=4,
                                                              sticky="w")

        ttk.Label(voice_box, text="Speed").grid(row=1, column=0, sticky="w",
                                                padx=(0, 8), pady=(10, 0))
        scale = ttk.Scale(voice_box, from_=0.5, to=2.0, variable=self.speed,
                          orient="horizontal", length=220, command=self._speed_moved)
        scale.grid(row=1, column=1, sticky="w", pady=(10, 0))
        self.speed_label = ttk.Label(voice_box, text="1.00x", width=6)
        self.speed_label.grid(row=1, column=2, sticky="w", padx=(8, 0), pady=(10, 0))

        ttk.Label(voice_box, text="Quality").grid(row=1, column=3, sticky="e",
                                                  padx=(18, 8), pady=(10, 0))
        ttk.Combobox(voice_box, textvariable=self.bitrate, state="readonly", width=22,
                     values=["32 kbps (smallest)", "48 kbps",
                             "64 kbps (recommended)", "96 kbps (best)"]
                     ).grid(row=1, column=4, sticky="w", pady=(10, 0))

        # --- action -------------------------------------------------------- #
        action = ttk.Frame(outer)
        action.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        action.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(action, mode="determinate", maximum=1000)
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        self.convert_btn = ttk.Button(action, text="Convert to MP3", width=18,
                                      command=self._start)
        self.convert_btn.grid(row=0, column=1)
        self.open_btn = ttk.Button(action, text="Open folder", width=13,
                                   command=lambda: open_folder(self.out_dir.get()))
        self.open_btn.grid(row=0, column=2, padx=(8, 0))

        self.status = ttk.Label(outer, text="Starting up...", foreground="#555",
                                anchor="w")
        self.status.grid(row=4, column=0, sticky="ew", pady=(8, 0))

        self.log = tk.Text(outer, height=5, wrap="word", state="disabled",
                           background="#f7f7f7", relief="flat", font=("Consolas", 9))
        self.log.grid(row=5, column=0, sticky="ew", pady=(6, 0))

        footer = ttk.Frame(outer)
        footer.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(footer, text="Model folder...", command=self._pick_models,
                   width=16).pack(side="right")

    # -- small helpers ------------------------------------------------------ #
    def _log(self, message: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _set_status(self, text: str, colour: str = "#555") -> None:
        self.status.config(text=text, foreground=colour)

    def _lock_inputs(self, locked: bool) -> None:
        """Stop the book being swapped out from under a running conversion."""
        state = "disabled" if locked else "normal"
        for widget in (self.epub_entry, self.out_entry, self.epub_btn,
                       self.out_btn, self.preview_btn):
            try:
                widget.config(state=state)
            except tk.TclError:
                pass

    def _speed_moved(self, _value=None) -> None:
        self.speed_label.config(text="%.2fx" % self.speed.get())

    def _bitrate_value(self) -> int:
        return int(self.bitrate.get().split()[0])

    def _lang_code(self) -> str:
        return dict(LANGS).get(self.lang.get(), "en-us")

    def _voice_id(self) -> str:
        label = self.voice.get()
        for vid, text in VOICE_LABELS.items():
            if text == label:
                return vid
        return label.split(" ")[0]

    # -- startup ------------------------------------------------------------ #
    def _startup(self) -> None:
        model, voices = models.find_models()
        if not (model and voices):
            self._set_status("Voice model not installed yet.", "#a60")
            dialog = DownloadDialog(self.root)
            self.root.wait_window(dialog)
            model, voices = models.find_models()
            if not (model and voices):
                self._set_status(
                    "Voice model missing - the program cannot convert until it is "
                    "downloaded. Use 'Model folder...' if you already have the files.",
                    "#a00")
                self.convert_btn.config(state="disabled")
                return

        self.model_path, self.voices_path = model, voices
        self.synth = Synthesizer(model, voices)
        self._load_voice_list()
        self._set_status("Ready. Choose an EPUB file to begin.", "#060")
        self._log("Voice model: %s" % model.parent)

    def _load_voice_list(self) -> None:
        ids = list_voices(self.voices_path) if self.voices_path else []
        if not ids:
            ids = sorted(VOICE_LABELS)
        labels = [VOICE_LABELS.get(v, v) for v in ids]
        self.voice_box["values"] = labels
        preferred = VOICE_LABELS.get("af_heart") if "af_heart" in ids else None
        self.voice.set(preferred or labels[0])

    def _pick_models(self) -> None:
        folder = filedialog.askdirectory(title="Folder containing the Kokoro model files")
        if not folder:
            return
        os.environ["KOKORO_MODEL_DIR"] = folder
        model, voices = models.find_models()
        if not (model and voices):
            messagebox.showerror(
                "Not found",
                "That folder does not contain both %s and %s."
                % (models.MODEL_FILE, models.VOICES_FILE))
            return
        self.model_path, self.voices_path = model, voices
        self.synth = Synthesizer(model, voices)
        self._load_voice_list()
        self.convert_btn.config(state="normal")
        self._set_status("Voice model loaded from %s" % folder, "#060")

    # -- file pickers -------------------------------------------------------- #
    def _pick_epub(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose an EPUB file",
            filetypes=[("EPUB books", "*.epub"), ("All files", "*.*")])
        if path:
            self.epub_path.set(path)
            self._load_book(path)

    def _pick_out(self) -> None:
        path = filedialog.askdirectory(title="Where should the MP3 files go?")
        if path:
            self.out_dir.set(path)
            self.out_dir_is_auto = False

    # -- book loading -------------------------------------------------------- #
    def _load_book(self, path: str) -> None:
        self._set_status("Reading book...")
        self.tree.delete(*self.tree.get_children())

        def work():
            try:
                book = read_epub(path)
                self.queue.put(("book", book))
            except Exception as exc:
                self.queue.put(("book_error", "%s" % exc))

        threading.Thread(target=work, daemon=True).start()

    def _show_book(self, book: Book) -> None:
        self.book = book
        self.tree.delete(*self.tree.get_children())
        self.checked = {c.index for c in book.chapters}

        for chapter in book.chapters:
            words = max(1, len(chapter.text.split()))
            est = chapter.char_count / CHARS_PER_SECOND
            self.tree.insert(
                "", "end", iid=str(chapter.index),
                values=(CHECKED, chapter.index, chapter.title,
                        "{:,}".format(words), human_time(est)))

        total = human_time(book.char_count / CHARS_PER_SECOND)
        self.book_label.config(
            text="%s - %s   |   %d chapters   |   about %s of audio"
                 % (book.title, book.author, len(book.chapters), total),
            foreground="#222")

        if not book.chapters:
            self._set_status("No readable text found in that EPUB.", "#a00")
            return

        self._set_status("Ready to convert.", "#060")
        # Give each book its own subfolder, but never overrule a folder the
        # user chose themselves.
        if self.out_dir_is_auto:
            base = Path(self.out_dir.get())
            if base.name.lower() != "audiobooks" and base.parent != base:
                base = base.parent          # replace the previous book's folder
            self.out_dir.set(str(base / safe_filename(book.title, "Audiobook")))

    # -- chapter checkboxes --------------------------------------------------- #
    def _toggle(self, iid: str) -> None:
        index = int(iid)
        if index in self.checked:
            self.checked.discard(index)
            self.tree.set(iid, "sel", UNCHECKED)
        else:
            self.checked.add(index)
            self.tree.set(iid, "sel", CHECKED)

    def _toggle_click(self, event) -> None:
        if self.running or self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.identify_column(event.x) != "#1":
            return
        iid = self.tree.identify_row(event.y)
        if iid:
            self._toggle(iid)

    def _toggle_selected(self, _event=None) -> str:
        for iid in self.tree.selection():
            self._toggle(iid)
        return "break"

    def _set_all(self, value: bool) -> None:
        if self.running:
            return
        for iid in self.tree.get_children():
            index = int(iid)
            self.checked.add(index) if value else self.checked.discard(index)
            self.tree.set(iid, "sel", CHECKED if value else UNCHECKED)

    # -- preview -------------------------------------------------------------- #
    def _preview(self) -> None:
        if not self.synth or self.running:
            return
        self.preview_btn.config(state="disabled")
        self._set_status("Generating a preview...")
        voice, speed, lang = self._voice_id(), self.speed.get(), self._lang_code()

        def work():
            try:
                import wave
                import tempfile
                import numpy as np

                audio = self.synth.say(
                    "This is how your audiobook will sound. "
                    "Chapter one. It was a bright cold day in April.",
                    voice, speed, lang)
                pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
                tmp = Path(tempfile.gettempdir()) / "epub2mp3_preview.wav"
                with wave.open(str(tmp), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(24000)
                    wav.writeframes(pcm.tobytes())
                self.queue.put(("preview", str(tmp)))
            except Exception as exc:
                self.queue.put(("preview_error", "%s" % exc))

        threading.Thread(target=work, daemon=True).start()

    def _play(self, path: str) -> None:
        try:
            if IS_WINDOWS:
                import winsound
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                open_folder(path)
        except Exception:
            open_folder(path)

    # -- conversion ------------------------------------------------------------ #
    def _start(self) -> None:
        if self.running:
            self.cancel_flag = True
            self.convert_btn.config(state="disabled", text="Stopping...")
            return

        if not self.book or not self.book.chapters:
            messagebox.showwarning("No book", "Choose an EPUB file first.")
            return
        if not self.checked:
            messagebox.showwarning("Nothing selected", "Tick at least one chapter.")
            return
        if not self.synth:
            messagebox.showerror("Not ready", "The voice model is not loaded.")
            return

        out_dir = Path(self.out_dir.get().strip() or (Path.home() / "Audiobooks"))
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("Cannot write there", "%s" % exc)
            return

        self.running = True
        self.cancel_flag = False
        self.convert_btn.config(text="Stop")
        self._lock_inputs(True)
        self.progress["value"] = 0
        selected = sorted(self.checked)
        self._log("Converting %d chapter(s) with %s at %.2fx"
                  % (len(selected), self._voice_id(), self.speed.get()))

        args = dict(voice=self._voice_id(), speed=round(self.speed.get(), 2),
                    bitrate=self._bitrate_value(), lang=self._lang_code(),
                    skip_existing=self.skip_existing.get(), selected=selected)

        def work():
            try:
                convert_book(
                    self.book, out_dir, self.synth,
                    on_progress=lambda p: self.queue.put(("progress", p)),
                    should_cancel=lambda: self.cancel_flag, **args)
            except Exception as exc:
                if exc.__class__.__name__ == "Cancelled":
                    self.queue.put(("cancelled", str(out_dir)))
                else:
                    self.queue.put(("error", traceback.format_exc(limit=3)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _finish(self, message: str, colour: str = "#060") -> None:
        self.running = False
        self.cancel_flag = False
        self.convert_btn.config(text="Convert to MP3", state="normal")
        self._lock_inputs(False)
        self._set_status(message, colour)

    # -- queue pump -------------------------------------------------------------- #
    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()

                if kind == "book":
                    self._show_book(payload)
                elif kind == "book_error":
                    self._set_status("Could not read that EPUB.", "#a00")
                    messagebox.showerror("Could not read EPUB", payload)
                elif kind == "preview":
                    self.preview_btn.config(state="normal")
                    self._set_status("Preview ready.", "#060")
                    self._play(payload)
                elif kind == "preview_error":
                    self.preview_btn.config(state="normal")
                    self._set_status("Preview failed: %s" % payload, "#a00")
                elif kind == "progress":
                    self._on_progress(payload)
                elif kind == "cancelled":
                    self._finish("Stopped. Finished chapters were kept.", "#a60")
                elif kind == "error":
                    self._finish("Conversion failed.", "#a00")
                    self._log(payload)
                    messagebox.showerror("Conversion failed", payload)
        except queue.Empty:
            pass
        self.root.after(60, self._drain)

    def _on_progress(self, p: Progress) -> None:
        if p.stage == "done":
            self.progress["value"] = 1000
            self._finish("Finished - %s in %s." % (p.message, human_time(p.elapsed)))
            self._log("Saved to %s" % p.output)
            if messagebox.askyesno(
                "Conversion complete",
                "%s.\n\nOpen the folder now?" % p.message.capitalize()):
                open_folder(p.output or self.out_dir.get())
            return

        if p.stage == "cancelled":
            self._finish("Stopped. Finished chapters were kept.", "#a60")
            return

        fraction = p.chars_done / max(1, p.chars_total)
        self.progress["value"] = min(1000, fraction * 1000)

        eta = ""
        if fraction > 0.01 and p.elapsed > 5:
            remaining = p.elapsed / fraction - p.elapsed
            eta = "  |  about %s left" % human_time(remaining)

        self._set_status(
            "Chapter %d of %d - %s   (%.0f%%)%s"
            % (p.chapter_index, p.chapter_total, p.chapter_title, fraction * 100, eta))

        if p.message:
            self._log("Chapter %d: %s - %s"
                      % (p.chapter_index, p.chapter_title, p.message))

    # -- shutdown ---------------------------------------------------------------- #
    def _on_close(self) -> None:
        if self.running:
            if not messagebox.askyesno(
                "Stop converting?",
                "A conversion is still running. Stop it and close?"):
                return
            self.cancel_flag = True
        self.root.destroy()


def _enable_dpi_awareness() -> None:
    """Stop Windows from bitmap-scaling the window into a blurry mess."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)   # per-monitor aware
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main() -> int:
    _enable_dpi_awareness()
    root = tk.Tk()
    try:
        scaling = root.winfo_fpixels("1i") / 72.0
        if scaling > 1.2:
            root.tk.call("tk", "scaling", scaling)
    except Exception:
        pass
    try:
        icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "app.ico"
        if icon.exists() and IS_WINDOWS:
            root.iconbitmap(str(icon))
    except Exception:
        pass
    app = App(root)

    # Windows passes the file path when the app is launched from Explorer.
    for arg in sys.argv[1:]:
        if arg.lower().endswith(".epub") and Path(arg).is_file():
            app.open_path(arg)
            break

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
