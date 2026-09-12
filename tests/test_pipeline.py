"""End-to-end pipeline tests: parse -> grade -> report -> mock email."""

from homework_agent import assignments
from homework_agent.email_service import MockEmailService
from homework_agent.pipeline import run_pipeline

from conftest import sample_path


def _read(name: str) -> str:
    with open(sample_path(name), encoding="utf-8") as f:
        return f.read()


def test_pipeline_text_all_correct():
    mailer = MockEmailService()
    sheet, emails = run_pipeline(
        assignments.get_assignment("math-fractions-01"),
        "Alex Kumar", "alex.student@example.edu", "text",
        _read("math_homework_alex.txt"), email_service=mailer,
    )
    assert sheet.percentage == 100.0
    assert len(emails) == 2
    assert emails[0].to == "alex.student@example.edu"
    assert emails[1].to == "rivera.teacher@example.edu"
    assert emails[1].cc == ["alex.student@example.edu"]


def test_pipeline_pdf_all_wrong_gets_explanations():
    mailer = MockEmailService()
    sheet, emails = run_pipeline(
        assignments.get_assignment("math-fractions-01"),
        "Ben Carter", "ben.student@example.edu", "pdf",
        sample_path("math_homework.pdf"), email_service=mailer,
    )
    assert sheet.correct_count == 0
    assert all(e.explanation for e in sheet.evaluations)
    assert all(e.correct_explanation for e in sheet.evaluations)
    assert len(mailer.outbox) == 2


def test_pipeline_image_with_transcription():
    mailer = MockEmailService()
    sheet, _ = run_pipeline(
        assignments.get_assignment("sci-water-cycle-01"),
        "Priya Nair", "priya.student@example.edu", "image",
        sample_path("science_homework.png"),
        transcribed_text=_read("science_homework_priya.txt"),
        email_service=mailer,
    )
    assert sheet.correct_count == 4
    assert len(mailer.outbox) == 2


def test_pipeline_image_without_transcription_runs_ocr(monkeypatch):
    monkeypatch.setattr(
        "homework_agent.ocr.transcribe_image",
        lambda path, mode=None: _read("science_homework_priya.txt"),
    )
    mailer = MockEmailService()
    sheet, _ = run_pipeline(
        assignments.get_assignment("sci-water-cycle-01"),
        "Priya Nair", "priya.student@example.edu", "image",
        sample_path("science_homework.png"),
        email_service=mailer,
    )
    assert sheet.correct_count == 4
    assert len(mailer.outbox) == 2


def test_pipeline_emails_contain_score_and_sheet():
    mailer = MockEmailService()
    sheet, (student_msg, teacher_msg) = run_pipeline(
        assignments.get_assignment("math-fractions-01"),
        "Alex Kumar", "alex.student@example.edu", "text",
        _read("math_homework_alex.txt"), email_service=mailer,
    )
    assert "100%" in student_msg.subject
    assert "Graded Homework" in student_msg.body
    assert "Alex Kumar" in teacher_msg.subject
    assert student_msg.attachments and teacher_msg.attachments


def test_pipeline_unknown_assignment():
    import pytest

    with pytest.raises(KeyError):
        assignments.get_assignment("nope-01")
