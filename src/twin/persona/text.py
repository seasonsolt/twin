"""File-to-text extraction; no model calls or OCR."""

from __future__ import annotations

import io
import posixpath
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
from xml.etree import ElementTree

MAX_FILE_BYTES = 50 * 1024 * 1024
SUPPORTED_SUFFIXES = frozenset(
    {".pdf", ".docx", ".epub", ".html", ".htm", ".txt", ".md", ".csv", ".json", ".srt", ".vtt"}
)


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        if not self.hidden and tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "section"}:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "section"}:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _html_text(markup: str) -> str:
    parser = _HTMLText()
    parser.feed(markup)
    return "".join(parser.parts).strip()


def _epub_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        # A small archive can expand enormously; refuse books that would not fit the upload limit unpacked.
        if sum(info.file_size for info in book.infolist()) > 4 * MAX_FILE_BYTES:
            raise ValueError("电子书解压后太大")
        container = ElementTree.fromstring(book.read("META-INF/container.xml"))
        rootfile = next(e for e in container.iter() if e.tag.endswith("rootfile")).attrib["full-path"]
        package = ElementTree.fromstring(book.read(rootfile))
        base = posixpath.dirname(rootfile)
        manifest = {
            item.attrib["id"]: item.attrib
            for item in package.iter()
            if item.tag.endswith("}item") and "id" in item.attrib and "href" in item.attrib
        }
        chapters = []
        for ref in package.iter():
            if not ref.tag.endswith("}itemref") or ref.attrib.get("idref") not in manifest:
                continue
            item = manifest[ref.attrib["idref"]]
            if "html" not in item.get("media-type", ""):
                continue
            path = posixpath.normpath(posixpath.join(base, unquote(item["href"].split("#", 1)[0])))
            if PurePosixPath(path).is_absolute() or path.startswith(".."):
                continue
            chapter = _html_text(book.read(path).decode("utf-8", errors="replace"))
            if chapter:
                chapters.append(chapter)
    return "\n\n".join(chapters)


def extract_text(name: str, data: bytes) -> str:
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("每个文件最多 50 MB")
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("不支持的文件类型")
    if suffix == ".pdf":
        from pypdf import PdfReader

        try:
            text = "\n\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages).strip()
        except Exception:
            raise ValueError("无法读取 PDF，请检查文件是否损坏或加密") from None
        if not text:
            raise ValueError("这个 PDF 没有可提取的文字（可能是扫描件）")
        return text
    if suffix == ".docx":
        from docx import Document

        try:
            document = Document(io.BytesIO(data))
            return "\n\n".join(
                [p.text for p in document.paragraphs]
                + ["\t".join(c.text for c in row.cells) for table in document.tables for row in table.rows]
            ).strip()
        except Exception:
            raise ValueError("无法读取 Word，请检查文件是否损坏") from None
    if suffix == ".epub":
        try:
            text = _epub_text(data)
        except ValueError:
            raise
        except Exception:
            raise ValueError("无法读取电子书，请检查文件是否损坏或加密") from None
        if not text:
            raise ValueError("这本电子书没有可提取的文字")
        return text
    from charset_normalizer import from_bytes

    # Prefer the common Chinese export encodings; short GBK samples otherwise look like Korean/Japanese.
    match = from_bytes(data, cp_isolation=["utf_8", "gb18030", "utf_16", "utf_32"]).best() or from_bytes(data).best()
    if match is None:
        raise ValueError("无法识别文字编码")
    text = str(match).lstrip("\ufeff")
    if suffix in {".html", ".htm"}:
        return _html_text(text)
    return text
