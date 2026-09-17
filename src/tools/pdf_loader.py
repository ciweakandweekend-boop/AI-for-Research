"""Local PDF loading with stable paper IDs and page-aware chunks.

The loader never searches for papers and never asks an LLM to infer a source.
Every returned chunk carries the local path, deterministic ``paper_id``,
one-based page number, and source text needed for later evidence citations.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Any, Iterator, Mapping


class PDFLoaderError(RuntimeError):
    """Raised when a local PDF cannot be read or chunked."""


@dataclass(frozen=True)
class PaperChunk(Mapping[str, Any]):
    """A JSON-shaped, page-addressable fragment of a local paper."""

    paper_id: str
    page: int
    text: str
    source_path: str
    title: str
    chunk_id: str
    start_char: int = 0
    end_char: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "page": self.page,
            "text": self.text,
            "source_path": self.source_path,
            "title": self.title,
            "chunk_id": self.chunk_id,
            "start_char": self.start_char,
            "end_char": self.end_char,
        }

    # Mapping support keeps the loader convenient for prompt construction and
    # for callers that prefer ``chunk["page"]`` over attribute access.
    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


def _normalise_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n[ \t]+", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _split_text(text: str, chunk_size: int, overlap: int) -> list[tuple[str, int, int]]:
    """Split one page while keeping offsets relative to the extracted page."""

    if len(text) <= chunk_size:
        return [(text, 0, len(text))]
    chunks: list[tuple[str, int, int]] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            # Prefer a word boundary in the latter half of the requested span.
            boundary = text.rfind(" ", start + chunk_size // 2, end)
            if boundary > start:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            left_trim = len(text[start:end]) - len(text[start:end].lstrip())
            right_trim = len(text[start:end]) - len(text[start:end].rstrip())
            chunks.append((piece, start + left_trim, end - right_trim))
        if end >= len(text):
            break
        next_start = max(start + 1, end - overlap)
        start = next_start
    return chunks


def _read_pdf_pages(path: Path) -> list[str]:
    try:
        import PyPDF2
    except ImportError as exc:  # pragma: no cover - dependency is in requirements
        raise PDFLoaderError("PyPDF2 is required to read local PDF files") from exc

    try:
        with path.open("rb") as handle:
            reader = PyPDF2.PdfReader(handle)
            return [_normalise_text(page.extract_text()) for page in reader.pages]
    except Exception as exc:
        raise PDFLoaderError(f"Could not read PDF: {path}") from exc


def load_pdf(
    path: str | Path,
    *,
    paper_id: str = "paper_01",
    chunk_size: int = 4000,
    overlap: int = 400,
    min_text_chars: int = 20,
) -> list[PaperChunk]:
    """Read one PDF and return page-aware chunks.

    Page numbering is one-based, matching the convention used in the evidence
    contract.  Empty or image-only pages are skipped because they cannot safely
    supply a text quotation.
    """

    pdf_path = Path(path)
    if not pdf_path.exists() or not pdf_path.is_file():
        raise PDFLoaderError(f"PDF file not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise PDFLoaderError(f"Expected a PDF file: {pdf_path}")
    if not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer")
    if not isinstance(overlap, int) or overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")
    if not isinstance(min_text_chars, int) or min_text_chars < 0:
        raise ValueError("min_text_chars must be a non-negative integer")
    if not paper_id.strip():
        raise ValueError("paper_id must be non-empty")

    title = pdf_path.stem.replace("_", " ").replace("-", " ").strip()
    chunks: list[PaperChunk] = []
    for page_number, page_text in enumerate(_read_pdf_pages(pdf_path), start=1):
        if len(page_text) < min_text_chars:
            continue
        for part_number, (text, start, end) in enumerate(
            _split_text(page_text, chunk_size, overlap), start=1
        ):
            chunks.append(
                PaperChunk(
                    paper_id=paper_id,
                    page=page_number,
                    text=text,
                    source_path=str(pdf_path.resolve()),
                    title=title,
                    chunk_id=f"{paper_id}-p{page_number:04d}-c{part_number:03d}",
                    start_char=start,
                    end_char=end,
                )
            )
    return chunks


def load_papers(
    directory: str | Path,
    *,
    max_papers: int | None = None,
    chunk_size: int = 4000,
    overlap: int = 400,
    min_text_chars: int = 20,
) -> list[PaperChunk]:
    """Load PDFs in stable filename order as ``paper_01``, ``paper_02``, ..."""

    root = Path(directory)
    if not root.exists() or not root.is_dir():
        raise PDFLoaderError(f"Paper directory not found: {root}")
    pdfs = sorted(
        (item for item in root.iterdir() if item.is_file() and item.suffix.lower() == ".pdf"),
        key=lambda item: item.name.casefold(),
    )
    if max_papers is not None:
        if not isinstance(max_papers, int) or max_papers < 1:
            raise ValueError("max_papers must be a positive integer or None")
        pdfs = pdfs[:max_papers]

    chunks: list[PaperChunk] = []
    for index, pdf_path in enumerate(pdfs, start=1):
        chunks.extend(
            load_pdf(
                pdf_path,
                paper_id=f"paper_{index:02d}",
                chunk_size=chunk_size,
                overlap=overlap,
                min_text_chars=min_text_chars,
            )
        )
    return chunks


def load_pdf_pages(path: str | Path, *, paper_id: str = "paper_01") -> list[PaperChunk]:
    """Compatibility helper that returns one chunk per non-empty page."""

    return load_pdf(path, paper_id=paper_id, chunk_size=10**9, overlap=0)


__all__ = ["PDFLoaderError", "PaperChunk", "load_pdf", "load_pdf_pages", "load_papers"]
