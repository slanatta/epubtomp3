"""
epubread.py - Minimal, dependency-free EPUB reader.

Uses only the standard library (zipfile / xml.etree / html.parser) so that the
frozen Windows executable has no extra moving parts to package.

Public API:
    book = read_epub(path)   -> Book(title, author, chapters=[Chapter, ...])
"""
from __future__ import annotations

import posixpath
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

CONTAINER = "META-INF/container.xml"

NS = {
    "cnt": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "xhtml": "http://www.w3.org/1999/xhtml",
}

# Tags whose text content should never be spoken.
SKIP_CONTENT = {"script", "style", "head", "title", "noscript", "svg", "math"}

# Tags that end a line when closed.
LINE_BREAK = {
    "p", "div", "br", "li", "tr", "td", "th", "blockquote", "pre",
    "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "figcaption",
    "dt", "dd", "hr", "table", "ul", "ol",
}

# Tags that start a new paragraph (double newline).
PARAGRAPH = {
    "p", "div", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "li", "tr", "pre",
}

HEADING_TAGS = ("h1", "h2", "h3", "h4", "title")

_WS = re.compile(r"[ \t\r\f\v  -​]+")
_BLANKS = re.compile(r"\n{3,}")
_NUMERIC = re.compile(r"^[\s\d\[\]().,*†‡§¶ivxlcdmIVXLCDM-]+$")


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Chapter:
    index: int              # 1-based position in the spine (documents only)
    title: str
    text: str
    href: str

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass
class Book:
    title: str
    author: str
    chapters: List[Chapter] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(c.char_count for c in self.chapters)


# --------------------------------------------------------------------------- #
# HTML -> text
# --------------------------------------------------------------------------- #
class _TextExtractor(HTMLParser):
    """Turns XHTML content into plain text suitable for speech."""

    def __init__(self, drop_footnote_refs: bool = True):
        super().__init__(convert_charrefs=True)
        self.drop_footnote_refs = drop_footnote_refs
        self.parts: List[str] = []
        self.headings: List[str] = []
        self._skip_depth = 0
        self._sup_buf: Optional[List[str]] = None
        self._heading_buf: Optional[List[str]] = None
        self._in_body = False
        self._saw_body = False

    # -- helpers ----------------------------------------------------------- #
    def _emit(self, text: str) -> None:
        if self._sup_buf is not None:
            self._sup_buf.append(text)
            return
        if self._heading_buf is not None:
            self._heading_buf.append(text)
        self.parts.append(text)

    # -- handlers ---------------------------------------------------------- #
    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "body":
            self._in_body = True
            self._saw_body = True
        if tag in SKIP_CONTENT:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        adict = {k.lower(): (v or "") for k, v in attrs}
        etype = adict.get("epub:type", "") + " " + adict.get("role", "")

        # Footnote / endnote reference markers read aloud as stray numbers.
        if self.drop_footnote_refs and (
            tag == "sup" or "noteref" in etype or "doc-noteref" in etype
        ):
            self._sup_buf = []
            return

        if tag == "br":
            self._emit("\n")
        elif tag in PARAGRAPH:
            self._emit("\n\n")
        elif tag in LINE_BREAK:
            self._emit("\n")

        if tag in HEADING_TAGS and self._heading_buf is None:
            self._heading_buf = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP_CONTENT:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return

        if self._sup_buf is not None and (tag == "sup" or tag == "a"):
            buf = "".join(self._sup_buf).strip()
            self._sup_buf = None
            # Keep the content if it is real words rather than a marker.
            if buf and not _NUMERIC.match(buf):
                self._emit(" " + buf + " ")
            return

        if tag in HEADING_TAGS and self._heading_buf is not None:
            head = _WS.sub(" ", "".join(self._heading_buf)).strip()
            if head:
                self.headings.append(head)
            self._heading_buf = None

        if tag in PARAGRAPH:
            self._emit("\n\n")
        elif tag in LINE_BREAK:
            self._emit("\n")

    def handle_data(self, data):
        if self._skip_depth or not data:
            return
        self._emit(data)

    def get_text(self) -> str:
        return clean_text("".join(self.parts))


def clean_text(raw: str) -> str:
    """Normalise whitespace and typography for a TTS engine."""
    text = unicodedata.normalize("NFKC", raw)
    # Characters that espeak either mispronounces or reads as noise.
    text = (
        text.replace("‘", "'").replace("’", "'")
        .replace("“", '"').replace("”", '"')
        .replace("—", " - ").replace("–", " - ")
        .replace("…", "... ").replace("﻿", "")
        .replace("­", "")
    )
    text = "".join(ch for ch in text if ch == "\n" or ch >= " " or ch == "\t")
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANKS.sub("\n\n", text)
    return text.strip()


def html_to_text(html: str, drop_footnote_refs: bool = True) -> Tuple[str, List[str]]:
    parser = _TextExtractor(drop_footnote_refs)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        # Malformed markup: fall back to a crude tag strip rather than failing.
        stripped = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
        stripped = re.sub(r"(?s)<[^>]+>", "\n", stripped)
        return clean_text(stripped), []
    return parser.get_text(), parser.headings


# --------------------------------------------------------------------------- #
# EPUB container parsing
# --------------------------------------------------------------------------- #
def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _findall_local(elem, name: str):
    """Namespace-agnostic descendant search (EPUBs are wildly inconsistent)."""
    for node in elem.iter():
        if _localname(node.tag) == name:
            yield node


def _read(zf: zipfile.ZipFile, name: str) -> bytes:
    try:
        return zf.read(name)
    except KeyError:
        # Some EPUBs use different casing than the manifest declares.
        lowered = name.lower()
        for info in zf.infolist():
            if info.filename.lower() == lowered:
                return zf.read(info.filename)
        raise


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _toc_titles(zf: zipfile.ZipFile, opf_dir: str, manifest: Dict[str, dict],
                toc_id: Optional[str]) -> Dict[str, str]:
    """Map spine href -> human readable title from the NCX or EPUB3 nav doc."""
    import xml.etree.ElementTree as ET

    titles: Dict[str, str] = {}

    def add(href: str, label: str) -> None:
        href = posixpath.normpath(href.split("#", 1)[0])
        label = _WS.sub(" ", label).strip()
        if href and label and href not in titles:
            titles[href] = label

    # -- EPUB 2: NCX ------------------------------------------------------- #
    ncx = manifest.get(toc_id or "")
    if ncx is None:
        for item in manifest.values():
            if item["media_type"] == "application/x-dtbncx+xml":
                ncx = item
                break
    if ncx is not None:
        try:
            root = ET.fromstring(_read(zf, ncx["path"]))
            base = posixpath.dirname(ncx["path"])
            for point in _findall_local(root, "navpoint"):
                label = ""
                for text_el in _findall_local(point, "text"):
                    label = text_el.text or ""
                    break
                src = ""
                for content in _findall_local(point, "content"):
                    src = content.get("src", "")
                    break
                if src:
                    add(posixpath.join(base, src) if base else src, label)
        except Exception:
            pass

    # -- EPUB 3: nav document ---------------------------------------------- #
    for item in manifest.values():
        if "nav" not in item["properties"].split():
            continue
        try:
            html = _decode(_read(zf, item["path"]))
            base = posixpath.dirname(item["path"])
            for m in re.finditer(
                r'(?is)<a\b[^>]*href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', html
            ):
                href, inner = m.group(1), re.sub(r"(?s)<[^>]+>", " ", m.group(2))
                add(posixpath.join(base, href) if base else href, inner)
        except Exception:
            pass

    return titles


def read_epub(path: str, min_chars: int = 200,
              drop_footnote_refs: bool = True) -> Book:
    """Parse an EPUB into ordered chapters of plain text."""
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as zf:
        # 1. Locate the OPF package document.
        try:
            container = ET.fromstring(_read(zf, CONTAINER))
            opf_path = ""
            for rf in _findall_local(container, "rootfile"):
                opf_path = rf.get("full-path", "")
                if opf_path:
                    break
        except Exception:
            opf_path = ""
        if not opf_path:
            candidates = [n for n in zf.namelist() if n.lower().endswith(".opf")]
            if not candidates:
                raise ValueError("Not a valid EPUB: no package document found.")
            opf_path = sorted(candidates, key=len)[0]

        opf_dir = posixpath.dirname(opf_path)
        opf = ET.fromstring(_read(zf, opf_path))

        # 2. Metadata.
        title, author = "", ""
        for node in _findall_local(opf, "title"):
            title = (node.text or "").strip()
            break
        for node in _findall_local(opf, "creator"):
            author = (node.text or "").strip()
            break

        # 3. Manifest.
        manifest: Dict[str, dict] = {}
        for item in _findall_local(opf, "item"):
            iid = item.get("id")
            href = item.get("href")
            if not iid or not href:
                continue
            full = posixpath.normpath(
                posixpath.join(opf_dir, href) if opf_dir else href
            )
            manifest[iid] = {
                "path": full,
                "media_type": (item.get("media-type") or "").lower(),
                "properties": item.get("properties") or "",
            }

        # 4. Spine order.
        spine_ids: List[str] = []
        toc_id = None
        for spine in _findall_local(opf, "spine"):
            toc_id = spine.get("toc")
            for ref in _findall_local(spine, "itemref"):
                idref = ref.get("idref")
                if idref:
                    spine_ids.append(idref)
            break

        if not spine_ids:  # Damaged spine: fall back to manifest order.
            spine_ids = [
                iid for iid, it in manifest.items()
                if "html" in it["media_type"]
            ]

        titles = _toc_titles(zf, opf_dir, manifest, toc_id)

        # 5. Extract text per document.
        chapters: List[Chapter] = []
        seen = set()
        for iid in spine_ids:
            item = manifest.get(iid)
            if item is None or "html" not in item["media_type"]:
                continue
            if "nav" in item["properties"].split():
                continue  # table of contents, not prose
            if item["path"] in seen:
                continue
            seen.add(item["path"])

            try:
                html = _decode(_read(zf, item["path"]))
            except Exception:
                continue

            text, headings = html_to_text(html, drop_footnote_refs)
            if len(text) < min_chars:
                continue  # cover art, blank pages, copyright stubs

            name = titles.get(item["path"]) or (headings[0] if headings else "")
            if not name:
                name = "Chapter %d" % (len(chapters) + 1)
            chapters.append(
                Chapter(index=len(chapters) + 1, title=name[:120],
                        text=text, href=item["path"])
            )

    if not title:
        import os
        title = os.path.splitext(os.path.basename(path))[0]

    return Book(title=title, author=author or "Unknown", chapters=chapters)
