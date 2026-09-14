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

import difflib
import os
import re
from typing import Dict, List, Optional, Tuple

from . import ocr as _ocr
from .models import Submission

_ANSWER_LINE = re.compile(r"^\s*(Q\s*\d+)\s*[:.)\-]\s*(.+?)\s*$", re.IGNORECASE)
#: Answer labels students use instead of repeating the question:
#: "Ans:", "Answer:", or "A<n>:" ("A1: ...").
_ANSWER_LABEL = re.compile(
    r"^\s*(Ans(?:wer)?|A\s*\d+)\s*[:.)\-]\s*(.+?)\s*$", re.IGNORECASE
)
# Zero-width split before every "Q<n>:" marker (and answer label), so
# transcriptions that put several answers on one line ("Q1: b Q2: x = 4",
# "Q1: ... Ans: ...") still parse. The letter guard keeps "ans" inside
# ordinary words (e.g. "trans:") from splitting the line.
_Q_SPLIT = re.compile(
    r"(?=(?:Q\s*\d+|(?<![A-Za-z])(?:Ans(?:wer)?|A\s*\d+))\s*[:.)\-])",
    re.IGNORECASE,
)

#: A PDF text layer shorter than this (non-whitespace chars) is treated as a
#: scanned PDF and re-processed with Docling OCR.
_SCANNED_PDF_THRESHOLD = 30


def _parse_text_full(text: str) -> Tuple[Dict[str, str], List[str]]:
    """Extract ({question_id: answer}, unclaimed answer-label texts).

    Understands "Q<n>:" question markers and answer labels ("Ans:",
    "Answer:", "A<n>:"). "A<n>:" maps directly onto Q<n>; "Ans:" /
    "Answer:" attach to the most recently seen question marker. An answer
    label with no question to attach to is returned in ``unclaimed`` so the
    single-question fallback in ``extract_answers`` can still use it.
    """
    answers: Dict[str, str] = {}
    unclaimed: List[str] = []
    current_qid: Optional[str] = None
    for line in text.splitlines():
        for segment in _Q_SPLIT.split(line):
            segment = segment.strip()
            if not segment:
                continue
            qmatch = _ANSWER_LINE.match(segment)
            if qmatch:
                current_qid = re.sub(r"\s+", "", qmatch.group(1)).upper()
                answers[current_qid] = qmatch.group(2).strip()
                continue
            amatch = _ANSWER_LABEL.match(segment)
            if amatch:
                label = re.sub(r"\s+", "", amatch.group(1)).upper()
                content = amatch.group(2).strip()
                if not content:
                    continue
                number = label[1:] if label.startswith("A") else ""
                if number.isdigit():
                    answers[f"Q{number}"] = content
                elif current_qid is not None:
                    # An explicit answer label wins over whatever the
                    # "Q<n>:" line captured (often the question text itself
                    # in photo transcriptions).
                    answers[current_qid] = content
                else:
                    unclaimed.append(content)
    return answers, unclaimed


def parse_text(text: str) -> Dict[str, str]:
    """Extract {question_id: answer} from plain text."""
    answers, _ = _parse_text_full(text)
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


def _is_question_echo(answer: str, question: str) -> bool:
    """True when the 'answer' is just the question text repeated back.

    Photo transcriptions sometimes label the handwritten question line
    itself ("Q1: Q. How is ...?"), and the parser then mistakes the question
    for the student's answer. Such echoes must not be graded as answers.
    """

    def norm(s: str) -> str:
        s = s.lower()
        # Strip a leading "Q1:" / "Q." style label remnant (the delimiter is
        # required so words merely starting with "q", e.g. "quick", survive).
        s = re.sub(r"^q\s*\d*\s*[:.)\-]\s*", "", s)
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", s)).strip()

    a, q = norm(answer), norm(question)
    if not a or not q:
        return False
    if a == q:
        return True
    return difflib.SequenceMatcher(None, a, q).ratio() >= 0.9


def extract_answers(
    submission: Submission,
    *,
    ocr_mode: Optional[str] = None,
    fallback_question_id: Optional[str] = None,
    question_prompts: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Dispatch to the right parser based on submission.format.

    ``fallback_question_id``: when the assignment has exactly one question,
    the student's whole response belongs to that question even when OCR
    mislabels the question number (e.g. the VLM reads "Q1" as "Q17:") or
    finds no ``"Q<n>:"`` label at all. With several questions there is no
    way to attribute the text, so the fallback never applies.

    ``question_prompts``: {question_id: question text}; answers that merely
    repeat the question back are discarded so they grade as "no answer
    provided" instead of being scored against themselves.
    """
    text = _raw_text(submission, ocr_mode=ocr_mode)
    answers, unclaimed = _parse_text_full(text)
    if fallback_question_id and not answers.get(fallback_question_id, "").strip():
        # Single-question assignment whose expected id is missing or blank:
        # prefer any parsed answer text (the number was misread), then an
        # "Ans:"-style line with no question to attach to, then the raw
        # text, instead of scoring a certain zero.
        others = " ".join(
            value.strip()
            for qid, value in answers.items()
            if qid != fallback_question_id and value.strip()
        )
        replacement = others or " ".join(unclaimed) or text.strip()
        if replacement:
            answers = {fallback_question_id: replacement}
    if question_prompts:
        for qid in list(answers):
            prompt = question_prompts.get(qid, "")
            if prompt and _is_question_echo(answers[qid], prompt):
                del answers[qid]
    return answers
