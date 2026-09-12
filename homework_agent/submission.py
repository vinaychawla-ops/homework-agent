"""Parsers that turn a raw submission (text / PDF / image) into structured answers.

Accepted answer layout for text and PDF sources, one per line:

    Q1: 3/4
    Q2: x = 4

Question ids are case-insensitive ("q1" works too). Lines that do not match the
"Q<n>:" pattern are ignored, and unanswered questions simply end up missing
from the returned dict (the grader marks them wrong with 0 points).

OCR: image submissions are transcribed with Docling (see ``ocr.py``) unless
the caller supplies ``transcribed_text`` (deterministic demo/test path).
Scanned PDFs with no usable text layer fall back to Docling OCR as well.
"""

from __future__ import annotations

import os
import re
from typing import Dict, Optional

from . import ocr as _ocr
from .models import Submission

_ANSWER_LINE = re.compile(r"^\s*(Q\s*\d+)\s*[:.)\-]\s*(.+?)\s*$", re.IGNORECASE)
# Zero-width split before every "Q<n>:" marker, so transcriptions that put
# several answers on one line ("Q1: b Q2: x = 4") still parse.
_Q_SPLIT = re.compile(r"(?=(Q\s*\d+)\s*[:.)\-])", re.IGNORECASE)

#: A PDF text layer shorter than this (non-whitespace chars) is treated as a
#: scanned PDF and re-processed with Docling OCR.
_SCANNED_PDF_THRESHOLD = 30


def parse_text(text: str) -> Dict[str, str]:
    """Extract {question_id: answer} from plain text."""
    answers: Dict[str, str] = {}
    for line in text.splitlines():
        for segment in _Q_SPLIT.split(line):
            segment = segment.strip()
            if not segment:
                continue
            match = _ANSWER_LINE.match(segment)
            if match:
                qid = re.sub(r"\s+", "", match.group(1)).upper()
                answers[qid] = match.group(2).strip()
    return answers


def parse_pdf(path: str) -> Dict[str, str]:
    """Extract answers from a PDF.

    Reads the embedded text layer with pypdf first (fast, offline). If the
    text layer is empty or suspiciously short the PDF is treated as scanned
    and re-processed with Docling OCR.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"PDF submission not found: {path}")
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is in requirements.txt
        raise ImportError("pypdf is required to parse PDF submissions") from exc
    reader = PdfReader(path)
    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if len(re.sub(r"\s+", "", full_text)) >= _SCANNED_PDF_THRESHOLD:
        return parse_text(full_text)
    # Scanned PDF: no usable text layer -> Docling OCR.
    return parse_text(_ocr.extract_printed(path))


def parse_image(
    path: str,
    transcribed_text: Optional[str] = None,
    *,
    ocr_mode: Optional[str] = None,
) -> Dict[str, str]:
    """Parse a photo/scan of handwritten homework.

    If ``transcribed_text`` is supplied it is used directly (deterministic
    path for demos and tests). Otherwise the image is transcribed with
    Docling: the VLM/handwriting path (OpenRouter + Gemma) when an API key is
    configured, else the standard local OCR pipeline. ``ocr_mode`` forces
    ``"auto"`` | ``"docling"`` | ``"vlm"``.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image submission not found: {path}")
    text = transcribed_text
    if not text or not text.strip():
        text = _ocr.transcribe_image(path, mode=ocr_mode)
    return parse_text(text)


def extract_answers(
    submission: Submission, *, ocr_mode: Optional[str] = None
) -> Dict[str, str]:
    """Dispatch to the right parser based on submission.format."""
    if submission.format == "text":
        return parse_text(submission.content)
    if submission.format == "pdf":
        return parse_pdf(submission.content)
    if submission.format == "image":
        return parse_image(
            submission.content, submission.transcribed_text, ocr_mode=ocr_mode
        )
    raise ValueError(f"Unsupported submission format: {submission.format!r}")
