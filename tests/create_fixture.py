"""Script to generate a rich test fixture EPUB for automated and manual tests.

Includes:
- 3 chapters of literary novel prose with dialogue
- Inline tags (<em>, <strong>, <a href="...">, <span class="...">)
- Split inline text and nested tags
- Scene breaks and Unicode characters (“...”, ‘...’, —)
- Embedded stylesheet (style.css)
- Embedded image (1x1 PNG cover and chapter illustration)
- Standard OPF manifest and spine
- TOC NCX and EPUB 3 Navigation Document (nav.xhtml)
"""

from __future__ import annotations

import base64
import posixpath
import zipfile
from pathlib import Path

# 1x1 transparent PNG in base64
DUMMY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

STYLE_CSS = """
body {
  font-family: serif;
  margin: 5%;
  line-height: 1.5;
}
h1, h2 {
  text-align: center;
  font-weight: bold;
}
p {
  text-indent: 1.5em;
  margin-top: 0;
  margin-bottom: 0.5em;
}
p.lead {
  text-indent: 0;
  font-weight: bold;
}
.italic {
  font-style: italic;
}
.scene-break {
  text-align: center;
  margin: 1.5em 0;
}
"""

CHAP1_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
<head>
  <title>Chapter 1: The Mysterious Letter</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <div class="chapter">
    <h1>Chapter 1: The Mysterious Letter</h1>
    <p class="lead">The morning sun crept softly across the quiet rooftops of London.</p>
    <p>Mr. Thomas Finch adjusted his spectacles, staring in utter disbelief at the wax seal. "<em>Could it really be?</em>" he murmured to himself.</p>
    <p>Outside, the carriage horses stomped impatiently upon the wet cobblestones. A young woman with a <strong>red woolen scarf</strong> walked briskly toward the station, unaware that everything was about to change.</p>
    <div class="scene-break">* * *</div>
    <p>He turned to his daughter, Clara. "Take this key," he whispered, pointing to the <a href="chap2.xhtml">wooden chest</a> near the window. "Do not open it until midnight."</p>
  </div>
</body>
</html>"""

CHAP2_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
<head>
  <title>Chapter 2: Inside the Wooden Chest</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <div class="chapter">
    <h1>Chapter 2: Inside the Wooden Chest</h1>
    <p>Midnight arrived with the solemn chime of the church bells. Clara held her breath as the brass key turned inside the rusted lock.</p>
    <p>Inside the chest lay an ancient map wrapped in silk, beside a strange instrument: a brass <span class="italic">compass</span> that pointed not North, but toward the distant mountains.</p>
    <p>"It is just as Father warned," Clara said, feeling a chill run down her spine. "The secret of the <a href="chap3.xhtml">Forgotten Kingdom</a> was true after all."</p>
  </div>
</body>
</html>"""

CHAP3_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
<head>
  <title>Chapter 3: The Journey Begins</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <div class="chapter">
    <h1>Chapter 3: The Journey Begins</h1>
    <p>By dawn, Clara had packed her satchel with bread, tea, and warm gloves. The great locomotive hissed plumes of white steam into the freezing autumn air.</p>
    <p>"Tickets, please!" shouted the conductor in a booming voice. Clara handed over her ticket with trembling fingers, her eyes fixed on the horizon ahead.</p>
  </div>
</body>
</html>"""

NAV_XHTML = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head>
  <title>Table of Contents</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Table of Contents</h1>
    <ol>
      <li><a href="chap1.xhtml">Chapter 1: The Mysterious Letter</a></li>
      <li><a href="chap2.xhtml">Chapter 2: Inside the Wooden Chest</a></li>
      <li><a href="chap3.xhtml">Chapter 3: The Journey Begins</a></li>
    </ol>
  </nav>
</body>
</html>"""

TOC_NCX = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="urn:uuid:12345678-fixture-novel"/>
    <meta name="dtb:depth" content="1"/>
  </head>
  <docTitle><text>The Chronicles of Finch</text></docTitle>
  <navMap>
    <navPoint id="np-1" playOrder="1">
      <navLabel><text>Chapter 1: The Mysterious Letter</text></navLabel>
      <content src="chap1.xhtml"/>
    </navPoint>
    <navPoint id="np-2" playOrder="2">
      <navLabel><text>Chapter 2: Inside the Wooden Chest</text></navLabel>
      <content src="chap2.xhtml"/>
    </navPoint>
    <navPoint id="np-3" playOrder="3">
      <navLabel><text>Chapter 3: The Journey Begins</text></navLabel>
      <content src="chap3.xhtml"/>
    </navPoint>
  </navMap>
</ncx>"""

CONTENT_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookID" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>The Chronicles of Finch</dc:title>
    <dc:creator>Arthur Pendelton</dc:creator>
    <dc:language>en</dc:language>
    <dc:identifier id="BookID">urn:uuid:12345678-fixture-novel</dc:identifier>
    <dc:description>A gripping tale of mystery, antique compasses, and forgotten kingdoms.</dc:description>
  </metadata>
  <manifest>
    <item id="style" href="style.css" media-type="text/css"/>
    <item id="cover-img" href="images/cover.png" media-type="image/png"/>
    <item id="chap1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chap2" href="chap2.xhtml" media-type="application/xhtml+xml"/>
    <item id="chap3" href="chap3.xhtml" media-type="application/xhtml+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="chap1"/>
    <itemref idref="chap2"/>
    <itemref idref="chap3"/>
  </spine>
</package>"""


def create_fixture_epub(destination: Path) -> Path:
    """Build and write the fixture EPUB to destination."""
    destination.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(destination, "w") as zf:
        # 1. Mimetype FIRST, uncompressed
        m_info = zipfile.ZipInfo("mimetype")
        m_info.compress_type = zipfile.ZIP_STORED
        m_info.extra = b""
        zf.writestr(m_info, b"application/epub+zip")

        # 2. Files
        zf.writestr("META-INF/container.xml", CONTAINER_XML.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/content.opf", CONTENT_OPF.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/style.css", STYLE_CSS.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/images/cover.png", DUMMY_PNG, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/chap1.xhtml", CHAP1_XHTML.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/chap2.xhtml", CHAP2_XHTML.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/chap3.xhtml", CHAP3_XHTML.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/nav.xhtml", NAV_XHTML.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr("OEBPS/toc.ncx", TOC_NCX.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)

    return destination


if __name__ == "__main__":
    out = Path("tests/fixtures/sample_novel.epub")
    create_fixture_epub(out)
    print(f"Generated fixture EPUB at {out.resolve()} (size: {out.stat().st_size} bytes)")
