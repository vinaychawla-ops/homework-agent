"""Tests for submission.py: text / PDF / image answer extraction."""

import pytest

from homework_agent.models import Submission
from homework_agent.submission import extract_answers, parse_image, parse_pdf, parse_text

from conftest import sample_path


def test_parse_text_basic():
    answers = parse_text("Q1: 3/4\nQ2: x = 4\nQ3: b")
    assert answers == {"Q1": "3/4", "Q2": "x = 4", "Q3": "b"}


def test_parse_text_case_insensitive_and_separators():
    answers = parse_text("q1 - 3/4\nQ2) hello world\n  Q3.  (b)  ")
    assert answers == {"Q1": "3/4", "Q2": "hello world", "Q3": "(b)"}


def test_parse_text_ignores_noise_lines():
    answers = parse_text("Name: Alex\nDate: today\nQ1: 42\nsome random note")
    assert answers == {"Q1": "42"}


def test_parse_text_empty():
    assert parse_text("") == {}
    assert parse_text("no answers here") == {}


def test_parse_text_multiple_answers_on_one_line():
    # VLM transcriptions sometimes run answers together on one line.
    answers = parse_text("Q1: b Q2: x = 4 Q3: (c)")
    assert answers == {"Q1": "b", "Q2": "x = 4", "Q3": "(c)"}


def test_parse_text_single_line_vlm_style():
    answers = parse_text(
        "Q1: b Q2: The sun heats the puddle Q3: condensation Q4: a"
    )
    assert answers["Q1"] == "b"
    assert answers["Q2"] == "The sun heats the puddle"
    assert answers["Q3"] == "condensation"
    assert answers["Q4"] == "a"


def test_parse_text_noise_after_last_answer_ignored():
    assert parse_text("Q1: 42\nsome random note") == {"Q1": "42"}


def test_parse_pdf_sample():
    answers = parse_pdf(sample_path("math_homework.pdf"))
    assert answers["Q1"] == "2/3"
    assert answers["Q2"] == "x = 5"
    assert answers["Q5"] == "3/8 is left."


def test_parse_pdf_missing_file():
    with pytest.raises(FileNotFoundError):
        parse_pdf("/nonexistent/homework.pdf")


def test_parse_pdf_text_layer_skips_ocr(monkeypatch):
    def _fail(path):
        raise AssertionError("Docling OCR should not run when the text layer works")

    monkeypatch.setattr("homework_agent.ocr.extract_printed", _fail)
    answers = parse_pdf(sample_path("math_homework.pdf"))
    assert answers["Q1"] == "2/3"


def test_parse_pdf_scanned_falls_back_to_docling_ocr(monkeypatch, tmp_path):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    pdf_path = str(tmp_path / "scan.pdf")
    with open(pdf_path, "wb") as f:
        writer.write(f)

    monkeypatch.setattr(
        "homework_agent.ocr.extract_printed", lambda path: "Q1: 7"
    )
    assert parse_pdf(pdf_path) == {"Q1": "7"}


def test_parse_image_with_transcription():
    answers = parse_image(
        sample_path("science_homework.png"),
        "Q1: b\nQ2: the water evaporates",
    )
    assert answers == {"Q1": "b", "Q2": "the water evaporates"}


def test_parse_image_missing_file():
    with pytest.raises(FileNotFoundError):
        parse_image("/nonexistent/photo.png", "Q1: b")


def test_parse_image_blank_transcription_runs_ocr(monkeypatch):
    """Blank transcription -> Docling OCR path (mocked, no network)."""
    monkeypatch.setattr(
        "homework_agent.ocr.transcribe_image",
        lambda path, mode=None: "Q1: b\nQ2: x = 4",
    )
    answers = parse_image(sample_path("science_homework.png"), "   ")
    assert answers == {"Q1": "b", "Q2": "x = 4"}


def test_parse_image_without_transcription_runs_ocr(monkeypatch):
    monkeypatch.setattr(
        "homework_agent.ocr.transcribe_image",
        lambda path, mode=None: "Q3: c",
    )
    answers = parse_image(sample_path("science_homework.png"))
    assert answers == {"Q3": "c"}


def test_parse_image_supplied_transcription_skips_ocr(monkeypatch):
    def _fail(*a, **k):
        raise AssertionError("OCR should not run when transcription is supplied")

    monkeypatch.setattr("homework_agent.ocr.transcribe_image", _fail)
    answers = parse_image(sample_path("science_homework.png"), "Q1: b")
    assert answers == {"Q1": "b"}


def test_parse_image_ocr_mode_forwarded(monkeypatch):
    seen = {}

    def _fake(path, mode=None):
        seen["mode"] = mode
        return "Q1: a"

    monkeypatch.setattr("homework_agent.ocr.transcribe_image", _fake)
    parse_image(sample_path("science_homework.png"), ocr_mode="vlm")
    assert seen["mode"] == "vlm"


def test_extract_answers_dispatches_text():
    sub = Submission("A", "a@x.edu", "math-fractions-01", "text", "Q1: 1")
    assert extract_answers(sub) == {"Q1": "1"}


def test_extract_answers_dispatches_pdf():
    sub = Submission("B", "b@x.edu", "math-fractions-01", "pdf", sample_path("math_homework.pdf"))
    assert extract_answers(sub)["Q3"] == "a"


def test_extract_answers_dispatches_image():
    sub = Submission(
        "P", "p@x.edu", "sci-water-cycle-01", "image",
        sample_path("science_homework.png"), transcribed_text="Q4: a",
    )
    assert extract_answers(sub) == {"Q4": "a"}


def test_extract_answers_fallback_single_question_unlabeled_text():
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text",
                     "A rainbow forms when sunlight shines through rain drops.")
    assert extract_answers(sub, fallback_question_id="Q1") == {
        "Q1": "A rainbow forms when sunlight shines through rain drops."}


def test_extract_answers_fallback_not_used_when_labels_parse():
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text", "Q1: b")
    assert extract_answers(sub, fallback_question_id="Q1") == {"Q1": "b"}


def test_extract_answers_fallback_needs_nonblank_text():
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text", "   ")
    assert extract_answers(sub, fallback_question_id="Q1") == {}


def test_extract_answers_no_fallback_by_default():
    sub = Submission("A", "a@x.edu", "sci-rainbows-01", "text",
                     "A rainbow forms when sunlight shines through rain drops.")
    assert extract_answers(sub) == {}
