"""Teacher-uploaded answer keys: file ingestion, parsing, and type inference.

A teacher creates a new assignment by uploading an answer key as an
image (photo/scan of a handwritten or printed key), PDF, Word document
(.docx), or plain text. This module:

1. extracts raw text from the uploaded file (reusing the submission OCR
   pipeline: VLM handwriting for images, pypdf/Docling for PDFs),
2. parses ``Q1: <answer>`` lines into structured key questions,
3. infers a question type per answer (the teacher reviews/overrides these
   in the web UI before the assignment is saved),
4. renders the key in a small editable text format used by the UI.

Text format (one question per line; ``#`` comments and blanks ignored)::

    Title: Fractions Quiz
    Subject: math
    Teacher: Jane Doe <jane@school.edu>

    Q1 [numeric] Simplify 6/8 || 3/4 || Divide top and bottom by 2
    Q2 [multiple_choice] Which is 2^3? (a) 6 (b) 8 (c) 9 || b
    Q3 || x^2 + 5x + 6 || || points: 2

``[type]`` and the prompt are optional; a missing type is inferred from the
answer and always shown back in brackets so the teacher can correct it.
Segments after ``||`` are: answer (required), explanation (optional),
``key: value`` extras (optional; ``points:`` and ``concepts:``).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import submission
from .grading import _as_number  # numeric answer detection shared with grading


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
TEXT_EXTENSIONS = (".txt", ".md", ".text")

_HEADER_RE = re.compile(r"^(title|subject|teacher)\s*:\s*(.+)$", re.IGNORECASE)
_QUESTION_RE = re.compile(
    r"^(Q\s*\d+)\s*(?:\[\s*([a-z_]+)\s*\])?\s*(.*?)\s*(?:\|\|(.*))?$",
    re.IGNORECASE | re.DOTALL,
)
_TEACHER_RE = re.compile(r"^(.*?)\s*<([^<>@\s]+@[^<>@\s]+)>\s*$")
_POINTS_RE = re.compile(r"points\s*:\s*([\d.]+)", re.IGNORECASE)
_CONCEPTS_RE = re.compile(r"concepts\s*:\s*(.+)$", re.IGNORECASE)


@dataclass
class KeyQuestion:
    """One parsed answer-key entry before it becomes a Question."""

    qid: str
    answer: str
    question_type: str
    prompt: str = ""
    explanation: str = ""
    key_concepts: List[str] = field(default_factory=list)
    points: float = 1.0
    type_inferred: bool = False


def extract_key_text(path: str, filename: str = "") -> str:
    """Extract raw text from an uploaded answer-key file.

    Images go through the OCR transcription pipeline (VLM handwriting when
    an OpenRouter key is configured, else the local pipeline); PDFs use the
    embedded text layer with Docling OCR fallback for scans; .docx is read
    with python-docx; plain text is read directly.
    """
    name = (filename or os.path.basename(path)).lower()
    if name.endswith(IMAGE_EXTENSIONS):
        text = submission._image_text(path, None, ocr_mode=None)
        if not text.strip():
            raise ValueError("No text could be read from the uploaded image.")
        return text
    if name.endswith(".pdf"):
        return submission._pdf_text(path)
    if name.endswith(".docx"):
        try:
            from docx import Document
        except ImportError as exc:
            raise ImportError(
                "python-docx is required to read .docx answer keys"
            ) from exc
        doc = Document(path)
        text = "\n".join(p.text for p in doc.paragraphs)
        if not text.strip():
            raise ValueError("The .docx file contains no readable text.")
        return text
    if name.endswith(".doc"):
        raise ValueError(
            "Legacy .doc files are not supported. Please re-save the answer "
            "key as .docx or PDF and upload that instead."
        )
    if name.endswith(TEXT_EXTENSIONS) or True:  # default: try plain text
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            raise ValueError(f"Could not read the uploaded file: {exc}") from exc
        if not text.strip():
            raise ValueError("The uploaded file contains no text.")
        return text


def infer_question_type(answer: str) -> str:
    """Infer a question type from the shape of the answer key's answer."""
    a = answer.strip()
    if re.fullmatch(r"\(?[a-eA-E]\)?", a):
        return "multiple_choice"
    if _as_number(a) is not None:
        return "numeric"
    if re.search(r"[a-zA-Z]", a) and re.search(r"[+\-*/^=]", a):
        return "expression"
    return "short_answer"


def _default_concepts(answer: str) -> List[str]:
    """Content words from the answer, used as key concepts when none given."""
    words = re.findall(r"[a-zA-Z]{4,}", answer)
    seen: List[str] = []
    for word in words:
        low = word.lower()
        if low not in seen:
            seen.append(low)
    return seen


def parse_key_text(text: str) -> Tuple[Dict[str, str], List[KeyQuestion]]:
    """Parse answer-key text into (headers, key questions).

    Headers come from ``Title:``/``Subject:``/``Teacher:`` lines. Questions
    come from the ``Q1 || answer`` line format; when the text has no such
    lines, plain ``Q1: answer`` lines (e.g. from an OCR transcription) are
    parsed instead with inferred types.
    """
    headers: Dict[str, str] = {}
    keyed: List[KeyQuestion] = []
    structured = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        header = _HEADER_RE.match(line)
        if header and not line.upper().startswith("Q"):
            headers[header.group(1).lower()] = header.group(2).strip()
            continue
        match = _QUESTION_RE.match(line)
        if match and "||" in line:
            structured = True
            qid = re.sub(r"\s+", "", match.group(1)).upper()
            qtype = (match.group(2) or "").strip().lower()
            prompt = (match.group(3) or "").strip()
            rest = (match.group(4) or "")
            segments = [seg.strip() for seg in rest.split("||")]
            answer = segments[0] if len(segments) > 0 else ""
            explanation = segments[1] if len(segments) > 1 else ""
            extras = " || ".join(segments[2:])
            points = 1.0
            concepts: List[str] = []
            points_match = _POINTS_RE.search(extras)
            if points_match:
                points = float(points_match.group(1))
            concepts_match = _CONCEPTS_RE.search(extras)
            if concepts_match:
                concepts = [
                    c.strip() for c in concepts_match.group(1).split(",") if c.strip()
                ]
            if not answer:
                raise ValueError(f"{qid}: the answer after '||' must not be empty.")
            inferred = False
            if not qtype:
                qtype = infer_question_type(answer)
                inferred = True
            keyed.append(
                KeyQuestion(
                    qid=qid,
                    answer=answer,
                    question_type=qtype,
                    prompt=prompt,
                    explanation=explanation
                    or f"The correct answer is {answer}.",
                    key_concepts=concepts
                    or (_default_concepts(answer) if qtype == "short_answer" else []),
                    points=points,
                    type_inferred=inferred,
                )
            )
    if not structured:
        # No structured lines: treat the whole text as a plain answer key
        # (e.g. fresh OCR output) with one answer per "Q1: ..." line.
        answers = submission.parse_text(text)
        for qid, answer in answers.items():
            qtype = infer_question_type(answer)
            keyed.append(
                KeyQuestion(
                    qid=qid,
                    answer=answer,
                    question_type=qtype,
                    key_concepts=_default_concepts(answer)
                    if qtype == "short_answer"
                    else [],
                    explanation=f"The correct answer is {answer}.",
                    type_inferred=True,
                )
            )
    # Preserve question order by numeric id.
    def _qid_sort(kq: KeyQuestion) -> Tuple[int, str]:
        num = re.search(r"\d+", kq.qid)
        return (int(num.group()) if num else 0, kq.qid)

    keyed.sort(key=_qid_sort)
    return headers, keyed


def render_key_text(
    headers: Dict[str, str], questions: List[KeyQuestion]
) -> str:
    """Render headers + questions in the editable answer-key text format."""
    lines: List[str] = []
    if headers.get("title"):
        lines.append(f"Title: {headers['title']}")
    if headers.get("subject"):
        lines.append(f"Subject: {headers['subject']}")
    if headers.get("teacher"):
        lines.append(f"Teacher: {headers['teacher']}")
    if lines:
        lines.append("")
    for kq in questions:
        line = f"{kq.qid} [{kq.question_type}]"
        if kq.prompt:
            line += f" {kq.prompt}"
        line += f" || {kq.answer}"
        extras: List[str] = []
        if kq.explanation and kq.explanation != f"The correct answer is {kq.answer}.":
            line += f" || {kq.explanation}"
        elif kq.explanation:
            line += " ||"
        if kq.points != 1.0:
            extras.append(f"points: {kq.points:g}")
        if kq.key_concepts:
            extras.append(f"concepts: {', '.join(kq.key_concepts)}")
        if extras:
            line += f" || {' || '.join(extras)}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def validate_key(
    headers: Dict[str, str], questions: List[KeyQuestion], subject: str = ""
) -> List[str]:
    """Return a list of validation error messages (empty when valid)."""
    errors: List[str] = []
    title = (headers.get("title") or "").strip()
    if not title:
        errors.append("The answer key needs a Title (add a 'Title: ...' line).")
    subj = (subject or headers.get("subject") or "").strip().lower()
    if subj not in ("math", "science"):
        errors.append(
            "Subject must be 'math' or 'science' "
            f"(got {headers.get('subject', subject)!r})."
        )
    if not questions:
        errors.append("No questions found: add lines like 'Q1 || 3/4'.")
    seen = set()
    for kq in questions:
        if kq.qid in seen:
            errors.append(f"Duplicate question id {kq.qid}.")
        seen.add(kq.qid)
        if kq.question_type not in (
            "numeric",
            "expression",
            "multiple_choice",
            "short_answer",
        ):
            errors.append(
                f"{kq.qid}: unknown type {kq.question_type!r}; expected one of "
                "numeric, expression, multiple_choice, short_answer."
            )
        if not kq.answer.strip():
            errors.append(f"{kq.qid}: answer must not be empty.")
    return errors


def parse_teacher_header(value: str) -> Tuple[str, str]:
    """Split 'Jane Doe <jane@school.edu>' into (name, email)."""
    match = _TEACHER_RE.match((value or "").strip())
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return (value or "").strip(), ""
