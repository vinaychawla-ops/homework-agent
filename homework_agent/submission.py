"""Parsers that turn a raw submission (text / PDF / image) into structured answers.

Accepted answer layout for text and PDF sources, one per line:

    Q1: 3/4
    Q2: x = 4

Question ids are case-insensitive ("q1" works too). Lines that do not match the
"Q<n>:" pattern are ignored, and unanswered questions simply end up missing
from the returned dict (the grader marks them wrong with 0 points).
"""

from __future__ import annotations

import os
import re
from typing import Dict

from .models import Submission

_ANSWER_LINE = re.compile(r"^\s*(Q\s*\d+)\s*[:.)\-]\s*(.+?)\s*$", re.IGNORECASE)


def parse_text(text: str) -> Dict[str, str]:
    """Extract {question_id: answer} from plain text."""
    answers: Dict[str, str] = {}
    for line in text.splitlines():
        match = _ANSWER_LINE.match(line)
        if match:
            qid = re.sub(r"\s+", "", match.group(1)).upper()
            answers[qid] = match.group(2).strip()
    return answers


def parse_pdf(path: str) -> Dict[str, str]:
    """Extract answers from a PDF by reading its text layer with pypdf."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"PDF submission not found: {path}")
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is in requirements.txt
        raise ImportError("pypdf is required to parse PDF submissions") from exc
    reader = PdfReader(path)
    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return parse_text(full_text)


def parse_image(path: str, transcribed_text: str) -> Dict[str, str]:
    """Parse a photo/scan of handwritten homework.

    Demo mode: handwriting OCR is out of scope for an offline demo, so the
    caller supplies the transcription (what a vision model would return).
    Production: replace the body with a call to a vision/OCR model and feed
    its output into parse_text().
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Image submission not found: {path}")
    if not transcribed_text or not transcribed_text.strip():
        raise ValueError("Image submissions require a non-empty transcription.")
    return parse_text(transcribed_text)


def extract_answers(submission: Submission) -> Dict[str, str]:
    """Dispatch to the right parser based on submission.format."""
    if submission.format == "text":
        return parse_text(submission.content)
    if submission.format == "pdf":
        return parse_pdf(submission.content)
    if submission.format == "image":
        return parse_image(submission.content, submission.transcribed_text or "")
    raise ValueError(f"Unsupported submission format: {submission.format!r}")
