"""Build a small but realistically-messy EPUB for testing."""
import sys
import zipfile
from pathlib import Path

CHAPTERS = [
    ("Chapter One: The Arrival",
     "<p>It was a bright cold day in April, and the clocks were striking "
     "thirteen.<sup><a href=\"#fn1\" epub:type=\"noteref\">1</a></sup> Winston "
     "Smith, his chin nuzzled into his breast in an effort to escape the vile "
     "wind, slipped quickly through the glass doors.</p>"
     "<p>Dr.&#160;Smith arrived at 3:45&nbsp;p.m. &mdash; late, as usual &mdash; "
     "carrying nothing but a battered leather case.</p>"
     "<blockquote><p>&ldquo;You&rsquo;re late,&rdquo; she said. &ldquo;Again.&rdquo;"
     "</p></blockquote>"),
    ("Chapter Two: A Very Long Sentence",
     "<p>" + ("The corridor smelled of boiled cabbage and old rag mats, and it "
              "wound on and on past doors that had not been opened in years, "
              "past windows that looked out on nothing at all, ") * 6 +
     "and at the end of it there was a single lamp.</p>"
     "<ul><li>First item in a list.</li><li>Second item.</li>"
     "<li>Third item, with a number: 1,234.</li></ul>"),
    ("Chapter Three: Bad Markup",
     "<p>This chapter has <b>unclosed <i>tags and &amp; stray entities &lt;"
     "<p>and a paragraph inside a paragraph, which parsers hate."
     "<script>var x = 'this should never be spoken';</script>"
     "<style>p { color: red }</style>"
     "<p>But the text should still come through cleanly, all one thousand "
     "characters of it. " + ("Filler sentence for length. " * 20) + "</p>"),
]


def build(path: Path) -> None:
    docs = []
    for i, (title, body) in enumerate(CHAPTERS, 1):
        docs.append((
            "OEBPS/ch%d.xhtml" % i,
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
            '<title>%s</title><style>body{margin:0}</style></head>'
            '<body><h1>%s</h1>%s</body></html>' % (title, title, body)
        ))

    manifest = "\n".join(
        '<item id="ch%d" href="ch%d.xhtml" media-type="application/xhtml+xml"/>'
        % (i, i) for i in range(1, len(CHAPTERS) + 1))
    spine = "\n".join('<itemref idref="ch%d"/>' % i
                      for i in range(1, len(CHAPTERS) + 1))
    navpoints = "\n".join(
        '<navPoint id="np%d" playOrder="%d"><navLabel><text>%s</text></navLabel>'
        '<content src="ch%d.xhtml"/></navPoint>'
        % (i, i, title, i) for i, (title, _) in enumerate(CHAPTERS, 1))

    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:title>The Test Book: A Story</dc:title>
<dc:creator>Ada Testwright</dc:creator>
<dc:identifier id="id">urn:uuid:test-0001</dc:identifier>
<dc:language>en</dc:language>
</metadata>
<manifest>
<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>
%s
</manifest>
<spine toc="ncx">
<itemref idref="cover"/>
%s
</spine>
</package>""" % (manifest, spine)

    ncx = """<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
<docTitle><text>The Test Book</text></docTitle>
<navMap>%s</navMap></ncx>""" % navpoints

    container = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OEBPS/content.opf"
media-type="application/oebps-package+xml"/></rootfiles></container>"""

    cover = ('<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org'
             '/1999/xhtml"><body><p>Cover</p></body></html>')

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip",
                    compress_type=zipfile.ZIP_STORED)
        zf.writestr(container, "") if False else None
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/toc.ncx", ncx)
        zf.writestr("OEBPS/cover.xhtml", cover)
        for name, data in docs:
            zf.writestr(name, data)
    print("wrote", path)


if __name__ == "__main__":
    build(Path(sys.argv[1] if len(sys.argv) > 1 else "test.epub"))
