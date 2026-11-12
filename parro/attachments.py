"""Attachments of announcements and calendar items: find them, download them, read them.

Where they live (spec: "Attachments"):
  * announcements keep them in `attachments[]`;
  * calendar items keep them in `calendarItem.attachments[]` (fix 4: never found before).
Each attachment has `entries[]`: the SOURCE file and, for images, resized variants. Every entry has
a CloudFront `url` that is unsigned: whoever has it can download the file. So:
  * the Parro Authorization header is never sent to the CDN;
  * full attachment URLs are never logged (fix 7); logs show the host only.

The parser is chosen by `contentType`, not by the entry's dtype (fix 6): a photo's SOURCE entry can
be an RAttachmentDocumentEntry. The file name is only a fallback for missing or generic types.
"""

import base64
import io
import logging
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree

from .errors import AttachmentError
from .geon import get_object_id
from .http import HttpRequest, HttpResponse

if TYPE_CHECKING:  # only for type hints: api_client does not import this module back
    from .api_client import ParroClient

log = logging.getLogger(__name__)

SOURCE_ENTRY_TYPE = "SOURCE"
PDF_TYPE = "application/pdf"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# Content types that say nothing about the format; then the file extension decides.
GENERIC_CONTENT_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream"})
PLAIN_TEXT_TYPES = frozenset({"application/json", "application/xml", "text/csv"})
PLAIN_TEXT_EXTENSIONS = frozenset({".txt", ".csv", ".md", ".json", ".xml"})
HTML_EXTENSIONS = frozenset({".html", ".htm"})

# How each format is recognised: by content type first, file extension as a fallback.
FORMAT_BY_EXTENSION = {
    ".pdf": "pdf",
    ".docx": "docx",
    **{extension: "html" for extension in HTML_EXTENSIONS},
    **{extension: "text" for extension in PLAIN_TEXT_EXTENSIONS},
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".gif": "image",
    ".webp": "image",
    ".heic": "image",
}


@dataclass(frozen=True)
class AttachmentFile:
    """The downloadable SOURCE file of one attachment."""

    attachment_id: int | None
    kind: str | None  # attachmentType, e.g. "PDF" or "IMAGE"
    filename: str | None
    content_type: str | None
    size: int | None
    url: str | None
    upload_id: str | None = None

    def cache_key(self) -> str | None:
        """'<attachment id>-<upload id>-<size>': the same key always means the same bytes."""
        if self.attachment_id is None or not self.upload_id or self.size is None:
            return None
        return f"{self.attachment_id}-{self.upload_id}-{self.size}"


def find_attachments(event: dict[str, Any]) -> list[dict[str, Any]]:
    """All attachments of an event: announcement-style and calendar-item-style (fix 4)."""
    found = [a for a in event.get("attachments") or [] if isinstance(a, dict)]
    calendar_item = event.get("calendarItem")
    if isinstance(calendar_item, dict):
        found.extend(a for a in calendar_item.get("attachments") or [] if isinstance(a, dict))
    return found


def pick_source_entry(attachment: dict[str, Any]) -> dict[str, Any]:
    """The original file among the attachment's entries: the SOURCE one, else the first."""
    entries = [entry for entry in attachment.get("entries") or [] if isinstance(entry, dict)]
    for entry in entries:
        if entry.get("type") == SOURCE_ENTRY_TYPE:
            return entry
    return entries[0] if entries else {}


def describe_attachment(attachment: dict[str, Any]) -> AttachmentFile:
    entry = pick_source_entry(attachment)
    return AttachmentFile(
        attachment_id=get_object_id(attachment),
        kind=attachment.get("attachmentType"),
        filename=entry.get("filename"),
        content_type=entry.get("contentType"),
        size=entry.get("size"),
        url=entry.get("url"),
        upload_id=attachment.get("uploadId"),
    )


def detect_format(content_type: str | None, filename: str | None) -> str | None:
    """'pdf', 'docx', 'html', 'text', 'image' or None (unknown), chosen by content type first."""
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type == PDF_TYPE:
        return "pdf"
    if media_type == DOCX_TYPE:
        return "docx"
    if media_type in ("text/html", "application/xhtml+xml"):
        return "html"
    if media_type.startswith("image/"):  # includes the non-standard image/jpg (fix 6)
        return "image"
    if media_type.startswith("text/") or media_type in PLAIN_TEXT_TYPES:
        return "text"
    if media_type not in GENERIC_CONTENT_TYPES:
        return None
    extension = _extension_of(filename)
    return FORMAT_BY_EXTENSION.get(extension) if extension else None


def can_extract_text(content_type: str | None, filename: str | None) -> bool:
    return detect_format(content_type, filename) in ("pdf", "docx", "html", "text")


def _extension_of(filename: str | None) -> str | None:
    if not filename or "." not in filename:
        return None
    return "." + filename.rsplit(".", 1)[1].lower()


# ------------------------------------------------------------------------------- download

# Below these limits a photo is passed on unchanged; above them it is downscaled (if Pillow exists).
IMAGE_BYTES_WITHOUT_RESIZE = 1_000_000
JPEG_QUALITY = 85


@dataclass(frozen=True)
class DownloadedFile:
    data: bytes = field(repr=False)
    content_type: str  # from the entry when known, else what the server sent


def download_attachment(
    client: "ParroClient", url: str, size_hint: int | None, known_content_type: str | None
) -> DownloadedFile:
    """Download one file. CDN URLs get no Parro headers at all; API-host URLs get the usual ones."""
    limit = client.settings.max_download_bytes
    if size_hint and size_hint > limit:
        raise AttachmentError(
            f"The attachment is {size_hint / 1e6:.1f} MB, more than the {limit / 1e6:.0f} MB limit "
            "(raise PARRO_MAX_DOWNLOAD to allow it)."
        )
    scheme = urllib.parse.urlsplit(url).scheme
    if scheme not in ("https", "http"):
        raise AttachmentError("Only http(s) attachment URLs can be downloaded.")
    if url.startswith(client.settings.api_base_uri + "/"):
        response = client.download_from_api_host(url)
    else:
        response = _download_from_cdn(client, url)
    if len(response.body) > limit:
        raise AttachmentError("The attachment is larger than PARRO_MAX_DOWNLOAD allows.")
    served_type = response.header("Content-Type") or ""
    content_type = known_content_type or served_type
    if (known_content_type or "").lower() in GENERIC_CONTENT_TYPES:
        content_type = served_type or (known_content_type or "")
    return DownloadedFile(response.body, content_type)


def _download_from_cdn(client: "ParroClient", url: str) -> HttpResponse:
    # The CDN link is unsigned: it needs no token, and the Parro token must never go there.
    host = urllib.parse.urlsplit(url).hostname or "?"
    log.info("downloading an attachment from %s", host)  # host only: the path is the key (fix 7)
    request = HttpRequest("GET", url, {"Accept": "*/*"}, log_label=f"GET attachment from {host}")
    response = client.transport.send(request)
    if response.status not in (200, 206):
        raise AttachmentError(
            f"Downloading the attachment from {host} failed (HTTP {response.status})."
        )
    return response


def filename_from_url(url: str | None) -> str | None:
    """The last path segment of a URL, decoded: '.../1-abc.pdf' → '1-abc.pdf'."""
    if not url:
        return None
    last_segment = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
    return urllib.parse.unquote(last_segment) or None


# ------------------------------------------------------------------------- text extraction


@dataclass(frozen=True)
class ExtractedText:
    text: str
    details: dict[str, Any]  # e.g. {"format": "pdf", "pages": 3, "engine": "pymupdf"}


def extract_text(data: bytes, content_type: str | None, filename: str | None) -> ExtractedText:
    """Plain text from a PDF, docx, HTML or text file. Images and unknown types raise."""
    file_format = detect_format(content_type, filename)
    if file_format == "pdf":
        pdf = extract_pdf_text(data)
        details = {"format": "pdf", "pages": pdf.page_count, "engine": pdf.engine}
        return ExtractedText(tidy_whitespace(pdf.text), details)
    if file_format == "docx":
        return ExtractedText(tidy_whitespace(extract_docx_text(data)), {"format": "docx"})
    if file_format == "html":
        return ExtractedText(
            tidy_whitespace(extract_html_text(decode_text(data))), {"format": "html"}
        )
    if file_format == "text":
        return ExtractedText(tidy_whitespace(decode_text(data)), {"format": "text"})
    if file_format == "image":
        raise AttachmentError(
            f"This attachment is an image ({content_type or filename}); it holds no text."
        )
    raise AttachmentError(
        f"No text reader for content type {content_type!r} (file {filename!r}). "
        "Save the file instead (CLI: --save-to)."
    )


@dataclass(frozen=True)
class PdfText:
    text: str
    page_count: int
    engine: str  # which optional library read it


def extract_pdf_text(data: bytes) -> PdfText:
    """Text of every page. Uses PyMuPDF when installed, else pypdf; both are optional."""
    try:
        import fitz  # PyMuPDF

        with fitz.open(stream=data, filetype="pdf") as document:
            page_texts = [page.get_text("text") for page in document]
        return PdfText("\n".join(page_texts), page_count=len(page_texts), engine="pymupdf")
    except ImportError:
        pass
    except Exception as failure:  # a damaged PDF: pypdf may still manage
        log.warning("PyMuPDF could not read the PDF (%s); trying pypdf", type(failure).__name__)
    try:
        from pypdf import PdfReader
    except ImportError:
        raise AttachmentError(
            "No PDF library is installed. Install one into this Python: "
            "pip install pymupdf   (or: pip install pypdf)"
        ) from None
    try:
        page_texts = [page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages]
    except Exception as failure:
        raise AttachmentError(f"This PDF could not be read: {failure}") from None
    return PdfText("\n".join(page_texts), page_count=len(page_texts), engine="pypdf")


WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# A zip bomb guard: real newsletters have a document.xml of a few MB at most.
MAX_DOCX_XML_BYTES = 100 * 1024 * 1024


def extract_docx_text(data: bytes) -> str:
    """Paragraph text of a .docx (a zip with word/document.xml), one paragraph per line."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if archive.getinfo("word/document.xml").file_size > MAX_DOCX_XML_BYTES:
                raise AttachmentError("This .docx unpacks to an unreasonably large document.")
            document = ElementTree.fromstring(archive.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as failure:
        raise AttachmentError(
            f"This .docx file could not be read ({type(failure).__name__})."
        ) from None
    lines = []
    for paragraph in document.iter(f"{WORD_NAMESPACE}p"):
        pieces = []
        for element in paragraph.iter():
            if element.tag == f"{WORD_NAMESPACE}t":
                pieces.append(element.text or "")
            elif element.tag == f"{WORD_NAMESPACE}tab":
                pieces.append("\t")
            elif element.tag in (f"{WORD_NAMESPACE}br", f"{WORD_NAMESPACE}cr"):
                pieces.append("\n")
        lines.append("".join(pieces))
    return "\n".join(lines)


class _HtmlTextCollector(HTMLParser):
    """Visible text of an HTML document; block elements become line breaks."""

    SKIPPED = frozenset({"script", "style", "head", "title"})
    LINE_BREAKING = frozenset(
        {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pieces: list[str] = []
        self._skipping_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIPPED:
            self._skipping_depth += 1
        elif tag == "br":
            self.pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIPPED and self._skipping_depth:
            self._skipping_depth -= 1
        elif tag in self.LINE_BREAKING:
            self.pieces.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skipping_depth:
            self.pieces.append(data)


def extract_html_text(html: str) -> str:
    collector = _HtmlTextCollector()
    collector.feed(html)
    collector.close()
    return "".join(collector.pieces)


def decode_text(data: bytes) -> str:
    """UTF-8 (a byte-order mark is dropped); undecodable bytes become U+FFFD."""
    return data.decode("utf-8-sig", errors="replace")


def tidy_whitespace(text: str) -> str:
    """One space between words, no trailing spaces, at most one empty line in a row."""
    tidy_lines: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        words = line.replace("\t", " ").split()
        tidy_line = " ".join(words)
        if tidy_line or (tidy_lines and tidy_lines[-1]):
            tidy_lines.append(tidy_line)
    return "\n".join(tidy_lines).strip()


# ----------------------------------------------------------------------------------- images


def shrink_image(data: bytes, content_type: str, max_pixels: int) -> tuple[bytes, str]:
    """Downscale a large photo to at most `max_pixels` on its longest side, as JPEG.

    Phone photos are several MB; as base64 that is a lot of tokens for no extra detail. Without
    Pillow (optional) the original is returned unchanged.
    """
    try:
        from PIL import Image
    except ImportError:
        return data, content_type
    try:
        with Image.open(io.BytesIO(data)) as image:
            if max(image.size) <= max_pixels and len(data) <= IMAGE_BYTES_WITHOUT_RESIZE:
                return data, content_type
            image.thumbnail((max_pixels, max_pixels))
            converted = image if image.mode in ("RGB", "L") else image.convert("RGB")
            output = io.BytesIO()
            converted.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    except Exception as failure:  # an unreadable image: better the original than nothing
        log.warning("could not downscale an image (%s); sending it as is", type(failure).__name__)
        return data, content_type
    return output.getvalue(), "image/jpeg"


# ------------------------------------------------------------------------- one attachment


@dataclass(frozen=True)
class ReadOptions:
    """How to present a downloaded attachment."""

    max_chars: int = 40_000
    include_images: bool = True  # MCP: return photos as images; CLI: never (it prints JSON)
    save_directory: Path | None = None  # CLI --save-to: also keep the original file


@dataclass(frozen=True)
class AttachmentImage:
    base64_data: str = field(repr=False)
    mime_type: str


@dataclass(frozen=True)
class AttachmentReading:
    """The outcome for one file: a JSON-ready summary and, for photos, the image itself."""

    summary: dict[str, Any]
    image: AttachmentImage | None = None


def read_attachment_file(
    client: "ParroClient",
    url: str,
    filename: str | None,
    content_type: str | None,
    size_hint: int | None,
    options: ReadOptions,
    cache_key: str | None = None,
) -> AttachmentReading:
    """Download one attachment and return its text, or the (downscaled) image for photos.

    With a `cache_key` (see AttachmentFile.cache_key) the file and its text come from the cache
    when they are there, and go into it when they are not.
    """
    downloaded = download_or_reuse(client, url, size_hint, content_type, cache_key)
    name = filename or filename_from_url(url)
    summary: dict[str, Any] = {
        "filename": name,
        "contentType": downloaded.content_type,
        "bytes": size_hint or len(downloaded.data),
    }
    if options.save_directory is not None:
        summary["saved_to"] = str(save_file(options.save_directory, name, downloaded.data))
    if detect_format(downloaded.content_type, name) == "image":
        return _read_image(client, downloaded, summary, options)
    extracted = extract_or_reuse(client, downloaded, name, cache_key)
    return AttachmentReading(_text_summary(summary, extracted, url, options.max_chars))


def download_or_reuse(
    client: "ParroClient",
    url: str,
    size_hint: int | None,
    content_type: str | None,
    cache_key: str | None,
) -> DownloadedFile:
    """The file from the cache, or downloaded (and then cached)."""
    if cache_key:
        data = client.cache.get_bytes("attachments", f"{cache_key}.bin")
        meta = client.cache.get_json("attachments", f"{cache_key}.json")
        if data is not None and isinstance(meta, dict):
            log.info("attachment taken from the cache")
            return DownloadedFile(data, str(meta.get("contentType") or content_type or ""))
    downloaded = download_attachment(client, url, size_hint, content_type)
    if cache_key:
        client.cache.put_bytes("attachments", f"{cache_key}.bin", downloaded.data)
        client.cache.put_json(
            "attachments", f"{cache_key}.json", {"contentType": downloaded.content_type}
        )
    return downloaded


def extract_or_reuse(
    client: "ParroClient", downloaded: DownloadedFile, name: str | None, cache_key: str | None
) -> ExtractedText:
    """The text from the cache, or extracted (and then cached). Always the whole text."""
    if cache_key:
        cached = client.cache.get_json("attachments", f"{cache_key}.text.json")
        if isinstance(cached, dict) and isinstance(cached.get("text"), str):
            return ExtractedText(cached["text"], dict(cached.get("details") or {}))
    extracted = extract_text(downloaded.data, downloaded.content_type, name)
    if cache_key:
        client.cache.put_json(
            "attachments",
            f"{cache_key}.text.json",
            {"text": extracted.text, "details": extracted.details},
        )
    return extracted


def _read_image(
    client: "ParroClient", downloaded: DownloadedFile, summary: dict[str, Any], options: ReadOptions
) -> AttachmentReading:
    if not options.include_images:
        summary["returned_as"] = "nothing (an image; save it with --save-to)"
        return AttachmentReading(summary)
    data, mime_type = shrink_image(
        downloaded.data, downloaded.content_type, client.settings.max_image_pixels
    )
    summary["returned_as"] = "image"
    image = AttachmentImage(base64.b64encode(data).decode("ascii"), mime_type)
    return AttachmentReading(summary, image)


def _text_summary(
    summary: dict[str, Any], extracted: ExtractedText, url: str, max_chars: int
) -> dict[str, Any]:
    text = extracted.text
    summary["chars"] = len(text)
    summary.update(extracted.details)
    if len(text) > max_chars:
        summary["truncated"] = True
        summary["shown_chars"] = max_chars
        summary["hint"] = "Raise `max_chars` to read the rest."
        text = text[:max_chars]
    if not text.strip():
        summary["warning"] = (
            "No text found. This is probably a scanned or image-only document, which would "
            "need OCR. The file itself can still be opened from its url."
        )
        summary["url"] = url  # output for the user, never logged (fix 7)
    summary["text"] = text
    return summary


def save_file(directory: Path, filename: str | None, data: bytes) -> Path:
    """Write `data` into `directory` under a safe version of `filename`, never overwriting."""
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename or "attachment").name.replace("\\", "_") or "attachment"
    target = directory / safe_name
    counter = 2
    while True:
        try:
            # "x": the name is claimed and written in one step, so a file that appears between
            # looking and writing is not overwritten either.
            with target.open("xb") as new_file:
                new_file.write(data)
            return target
        except FileExistsError:
            target = directory / f"{Path(safe_name).stem} ({counter}){Path(safe_name).suffix}"
            counter += 1
