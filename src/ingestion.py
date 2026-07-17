"""
ingestion.py

Day 1 deliverable: load documents from PDF, Markdown, and web pages into
a single consistent format that the rest of the pipeline can consume.

Design notes (write these into your README later):
- Every loader returns a Document dict with the SAME shape, regardless of
  source type. This is what lets chunking.py stay source-agnostic.
- We fail loudly per-file (log + skip) rather than crashing the whole
  ingestion run — one bad PDF shouldn't kill ingestion of the other 4 docs.
- We keep raw text as close to "clean prose" as possible here. Chunking
  is a separate concern and shouldn't have to also fight with HTML tags
  or PDF layout artifacts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class Document:
    """A single ingested document, before chunking."""
    source: str                 # file path or URL
    text: str                   # cleaned raw text
    doc_type: str                # "pdf" | "markdown" | "web"
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Individual loaders
# ---------------------------------------------------------------------------

def load_pdf(path: str | Path) -> Optional[Document]:
    """Extract text from a PDF, page by page, preserving page numbers in metadata."""
    path = Path(path)
    try:
        reader = PdfReader(str(path))
        pages_text = []
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            page_text = page_text.strip()
            if page_text:
                # Keep a lightweight page marker — useful later for citations.
                pages_text.append(f"[page {i + 1}]\n{page_text}")

        full_text = "\n\n".join(pages_text)
        if not full_text.strip():
            logger.warning("No extractable text found in %s (likely a scanned PDF).", path)
            return None

        return Document(
            source=str(path),
            text=full_text,
            doc_type="pdf",
            metadata={"num_pages": len(reader.pages), "filename": path.name},
        )
    except Exception as e:
        logger.error("Failed to load PDF %s: %s", path, e)
        return None


def load_markdown(path: str | Path) -> Optional[Document]:
    """Load a markdown file as plain text. We keep markdown syntax intact —
    headers are useful signal for chunking boundaries later."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            logger.warning("Markdown file %s is empty.", path)
            return None

        return Document(
            source=str(path),
            text=text,
            doc_type="markdown",
            metadata={"filename": path.name},
        )
    except Exception as e:
        logger.error("Failed to load markdown %s: %s", path, e)
        return None


def load_webpage(url: str, timeout: int = 10) -> Optional[Document]:
    """Fetch a web page and extract visible text, stripping nav/script/style noise."""
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "rag-ingestion-bot/1.0"})
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Strip non-content elements before extracting text.
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        # Collapse excessive blank lines left behind by stripped tags.
        lines = [line.strip() for line in text.splitlines()]
        clean_text = "\n".join(line for line in lines if line)

        if not clean_text:
            logger.warning("No text extracted from %s", url)
            return None

        title = soup.title.string.strip() if soup.title and soup.title.string else url

        return Document(
            source=url,
            text=clean_text,
            doc_type="web",
            metadata={"title": title},
        )
    except Exception as e:
        logger.error("Failed to load webpage %s: %s", url, e)
        return None


# ---------------------------------------------------------------------------
# Batch loader
# ---------------------------------------------------------------------------

def load_documents_from_dir(directory: str | Path) -> list[Document]:
    """
    Walk a directory and load every .pdf and .md file found.
    Web pages aren't auto-discovered — pass URLs to load_webpage() explicitly,
    or extend this function to read a urls.txt file if you want that later.
    """
    directory = Path(directory)
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    documents: list[Document] = []

    pdf_files = sorted(directory.glob("*.pdf"))
    md_files = sorted(directory.glob("*.md"))

    logger.info("Found %d PDF(s) and %d markdown file(s) in %s", len(pdf_files), len(md_files), directory)

    for f in pdf_files:
        doc = load_pdf(f)
        if doc:
            documents.append(doc)

    for f in md_files:
        doc = load_markdown(f)
        if doc:
            documents.append(doc)

    logger.info("Successfully loaded %d/%d documents.", len(documents), len(pdf_files) + len(md_files))
    return documents


def load_documents_from_urls(urls: list[str]) -> list[Document]:
    """Load a list of web page URLs into Documents."""
    documents: list[Document] = []
    for url in urls:
        doc = load_webpage(url)
        if doc:
            documents.append(doc)
    logger.info("Successfully loaded %d/%d web pages.", len(documents), len(urls))
    return documents


if __name__ == "__main__":
    # Quick manual smoke test — run `python src/ingestion.py` from repo root.
    docs = load_documents_from_dir(r"C:\Users\man45\OneDrive\Documents")
    for d in docs:
        print(f"--- {d.source} ({d.doc_type}) ---")
        print(f"Length: {len(d.text)} chars")
        print(d.text[:300].replace("\n", " "))
        print()