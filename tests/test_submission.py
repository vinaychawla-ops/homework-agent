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


def test_parse_pdf_sample():
    answers = parse_pdf(sample_path("math_homework.pdf"))
    assert answers["Q1"] == "2/3"
    assert answers["Q2"] == "x = 5"
    assert answers["Q5"] == "3/8 is left."


def test_parse_pdf_missing_file():
    with pytest.raises(FileNotFoundError):
        parse_pdf("/nonexistent/homework.pdf")


def test_parse_image_with_transcription():
    answers = parse_image(
        sample_path("science_homework.png"),
        "Q1: b\nQ2: the water evaporates",
    )
    assert answers == {"Q1": "b", "Q2": "the water evaporates"}


def test_parse_image_missing_file():
    with pytest.raises(FileNotFoundError):
        parse_image("/nonexistent/photo.png", "Q1: b")


def test_parse_image_blank_transcription_rejected():
    with pytest.raises(ValueError, match="non-empty transcription"):
        parse_image(sample_path("science_homework.png"), "   ")


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
