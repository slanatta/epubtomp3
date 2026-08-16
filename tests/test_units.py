"""Fast checks that do not need the TTS model."""
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Scratch space. Must not be a hardcoded "/tmp" - on Windows that resolves to
# C:\tmp, which does not exist, and every file check below would fail.
TMP = Path(tempfile.gettempdir())

from epub2mp3.engine import MAX_CHUNK, chunk_text, safe_filename   # noqa: E402
from epub2mp3.epubread import clean_text, html_to_text, read_epub  # noqa: E402

failures = []


def check(name, condition, detail=""):
    if condition:
        print("  ok   %s" % name)
    else:
        print("  FAIL %s %s" % (name, detail))
        failures.append(name)


print("safe_filename")
check("strips illegal characters",
      safe_filename('a<b>c:d"e/f\\g|h?i*j') == "abcdefghij",
      safe_filename('a<b>c:d"e/f\\g|h?i*j'))
check("handles reserved device names", safe_filename("CON") == "untitled")
check("trims trailing dots", not safe_filename("Chapter 1...").endswith("."))
check("truncates on a word boundary", len(safe_filename("word " * 40)) <= 70)
check("falls back when empty", safe_filename("///") == "untitled")
check("keeps unicode", safe_filename("Café Über") == "Café Über")

print("chunk_text")
long_text = ("Sentence number one is here. " * 200)
chunks = chunk_text(long_text)
check("splits long text", len(chunks) > 5, len(chunks))
check("every chunk within limit",
      all(len(c.text) <= MAX_CHUNK for c in chunks),
      max(len(c.text) for c in chunks))
check("no text is lost",
      sum(len(c.text.replace(" ", "")) for c in chunks)
      == len(long_text.replace(" ", "")))

runon = "word " * 900        # one sentence, no punctuation at all
chunks = chunk_text(runon)
check("hard-wraps a run-on sentence",
      all(len(c.text) <= MAX_CHUNK for c in chunks),
      max(len(c.text) for c in chunks))

check("empty text yields nothing", chunk_text("") == [])
check("whitespace only yields nothing", chunk_text("   \n\n  ") == [])

para = "First para. Still first.\n\nSecond para here."
chunks = chunk_text(para)
check("paragraph break adds a gap", any(c.gap > 0 for c in chunks))

print("html_to_text")
text, heads = html_to_text(
    "<html><head><title>T</title><style>x{}</style></head><body>"
    "<h1>Title</h1><p>Hello <b>world</b>.</p>"
    "<script>bad()</script><p>Second&nbsp;line &amp; more.</p></body></html>")
check("drops script and style", "bad()" not in text and "x{}" not in text)
check("keeps prose", "Hello world." in text, text)
check("decodes entities", "Second line & more." in text, text)
check("captures headings", heads and heads[0] == "Title", heads)

text, _ = html_to_text('<p>See note<sup>12</sup> here.</p>')
check("drops numeric footnote markers", "12" not in text, text)
text, _ = html_to_text('<p>E<sup>real words kept</sup></p>')
check("keeps worded superscripts", "real words kept" in text, text)

check("normalises smart quotes", "'" in clean_text("don’t"))
check("collapses blank runs", "\n\n\n" not in clean_text("a\n\n\n\n\nb"))

print("read_epub")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_epub import build      # noqa: E402

tmp = TMP / "units.epub"
build(tmp)
book = read_epub(str(tmp))
check("reads title", book.title == "The Test Book: A Story", book.title)
check("reads author", book.author == "Ada Testwright", book.author)
check("skips the short cover page", len(book.chapters) == 3, len(book.chapters))
check("uses NCX titles",
      book.chapters[0].title == "Chapter One: The Arrival",
      book.chapters[0].title)
check("chapters are in spine order",
      [c.index for c in book.chapters] == [1, 2, 3])

bad = TMP / "not-an-epub.epub"
bad.write_bytes(b"this is not a zip file at all")
try:
    read_epub(str(bad))
    check("rejects non-EPUB input", False, "no exception raised")
except Exception as exc:
    check("rejects non-EPUB input", True, type(exc).__name__)

empty = TMP / "empty.epub"
with zipfile.ZipFile(empty, "w") as zf:
    zf.writestr("mimetype", "application/epub+zip")
try:
    result = read_epub(str(empty))
    check("empty EPUB yields no chapters", result.chapters == [])
except Exception as exc:
    check("empty EPUB raises a clear error", "EPUB" in str(exc), str(exc))

print()
if failures:
    print("%d FAILURE(S): %s" % (len(failures), ", ".join(failures)))
    sys.exit(1)
print("all unit checks passed")
