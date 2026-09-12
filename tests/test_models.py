"""Tests for models.py: validation and derived properties."""

import pytest

from homework_agent.models import Assignment, GradedSheet, Question, Submission


def make_question(**overrides):
    base = dict(
        id="Q1",
        subject="math",
        prompt="1+1?",
        question_type="numeric",
        correct_answer="2",
        correct_explanation="1+1=2.",
    )
    base.update(overrides)
    return Question(**base)


def test_question_rejects_bad_subject():
    with pytest.raises(ValueError, match="Unsupported subject"):
        make_question(subject="history")


def test_question_rejects_bad_type():
    with pytest.raises(ValueError, match="Unsupported question type"):
        make_question(question_type="essay")


def test_assignment_get_question_missing(math_assignment):
    with pytest.raises(KeyError):
        math_assignment.get_question("Q99")


def test_assignment_max_points(math_assignment):
    assert math_assignment.max_points == pytest.approx(6.0)


def test_submission_rejects_bad_format():
    with pytest.raises(ValueError, match="Unsupported submission format"):
        Submission("A", "a@x.edu", "math-fractions-01", "docx", "blob")


def test_image_submission_without_transcription_uses_ocr():
    """No transcribed_text -> allowed; OCR runs at extract time."""
    sub = Submission("A", "a@x.edu", "sci-water-cycle-01", "image", "/tmp/x.png")
    assert sub.transcribed_text is None


def test_graded_sheet_aggregates(math_assignment):
    from homework_agent.grading import grade_question

    evals = [grade_question(q, q.correct_answer) for q in math_assignment.questions]
    sheet = GradedSheet(math_assignment, "S", "s@x.edu", evals)
    assert sheet.total_earned == pytest.approx(sheet.total_possible)
    assert sheet.percentage == pytest.approx(100.0)
    assert sheet.correct_count == len(evals)


def test_graded_sheet_empty_percentage(math_assignment):
    sheet = GradedSheet(math_assignment, "S", "s@x.edu", [])
    assert sheet.percentage == 0.0
    assert sheet.total_earned == 0.0
