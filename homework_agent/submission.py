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


def _pdf_text(path: str) -> str:
    """Raw text of a PDF: embedded text layer, or Docling OCR for scans."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"PDF submission not found: {path}")
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is in requirements.txt
        raise ImportError("pypdf is required to parse PDF submissions") from exc
    reader = PdfReader(path)
    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if len(re.sub(r"\s+", "", full_text)) >= _SCANNED_PDF_THRESHOLD:
        return full_text
    # Scanned PDF: no usable text layer -> Docling OCR.
    return _ocr.extract_printed(path)


def parse_pdf(path: str) -> Dict[str, str]:
    """Extract answers from a PDF.

    Reads the embedded text layer with pypdf first (fast, offline). If the
    text layer is empty or suspiciously short the PDF is treated as scanned
    and re-processed with Docling OCR.
    """
    return parse_text(_pdf_text(path))


def _image_text(
    path: str,
    transcribed_text: Optional[str] = None,
    *,
    ocr_mode: Optional[str] = None,
) -> str:
    """Raw transcription of a photo/scan of handwritten homework."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image submission not found: {path}")
    text = transcribed_text
    if not text or not text.strip():
        text = _ocr.transcribe_image(path, mode=ocr_mode)
    return text


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
    return parse_text(_image_text(path, transcribed_text, ocr_mode=ocr_mode))


def _raw_text(submission: Submission, *, ocr_mode: Optional[str] = None) -> str:
    """The submission's raw text, before answer-line parsing."""
    if submission.format == "text":
        return submission.content
    if submission.format == "pdf":
        return _pdf_text(submission.content)
    if submission.format == "image":
        return _image_text(
            submission.content, submission.transcribed_text, ocr_mode=ocr_mode
        )
    raise ValueError(f"Unsupported submission format: {submission.format!r}")


def extract_answers(
    submission: Submission,
    *,
    ocr_mode: Optional[str] = None,
    fallback_question_id: Optional[str] = None,
) -> Dict[str, str]:
    """Dispatch to the right parser based on submission.format.

    ``fallback_question_id``: when the assignment has exactly one question,
    the student's whole response belongs to that question even when OCR
    mislabels the question number (e.g. the VLM reads "Q1" as "Q17:") or
    finds no ``"Q<n>:"`` label at all. With several questions there is no
    way to attribute the text, so the fallback never applies.
    """
    text = _raw_text(submission, ocr_mode=ocr_mode)
    answers = parse_text(text)
    if fallback_question_id and not answers.get(fallback_question_id, "").strip():
        # Single-question assignment whose expected id is missing or blank:
        # prefer any parsed answer text (the number was misread), else the
        # raw text, instead of scoring a certain zero.
        others = " ".join(
            value.strip()
            for qid, value in answers.items()
            if qid != fallback_question_id and value.strip()
        )
        replacement = others or text.strip()
        if replacement:
            answers = {fallback_question_id: replacement}
    return answers
