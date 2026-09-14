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


def test_pipeline_single_question_fallback_grades_unlabeled_prose():
    # Vin's rainbow homework: prose with no parseable "Q1:" label still
    # grades against the single-question assignment instead of scoring zero.
    assignment = assignments.get_assignment("sci-rainbows-01")
    sheet, _emails = run_pipeline(
        assignment,
        "Test Kid",
        "kid@example.edu",
        "text",
        "When you have rain and shine at the same time; "
        "sunlight passes through rain drops and create rainbow.",
    )
    ev = sheet.evaluations[0]
    assert ev.is_correct
    assert ev.points_earned == ev.points_possible


def test_pipeline_multi_question_no_fallback():
    assignment = assignments.get_assignment("sci-water-cycle-01")
    sheet, _emails = run_pipeline(
        assignment, "Test Kid", "kid@example.edu", "text", "some unlabeled prose"
    )
    assert all(e.points_earned == 0 for e in sheet.evaluations)


def test_pipeline_single_question_mislabeled_number_still_grades():
    # Production 2026-09-13: the VLM transcribed Vin's rainbow photo with the
    # question number misread as "Q17:", which parsed to {"Q17": ...} and
    # scored Q1 as "(no answer provided)". The whole response must grade.
    mailer = MockEmailService()
    sheet, _ = run_pipeline(
        assignments.get_assignment("sci-rainbows-01"),
        "T", "t@e.edu", "image", sample_path("science_homework.png"),
        transcribed_text=(
            "Q17: When you have rain and shine at the same time, "
            "sunlight passes through rain drops and creates a rainbow."
        ),
        email_service=mailer,
    )
    assert sheet.percentage == 100.0
    assert sheet.evaluations[0].student_answer != "(no answer provided)"


def test_pipeline_teacher_email_override():
    mailer = MockEmailService()
    _, emails = run_pipeline(
        assignments.get_assignment("sci-rainbows-01"),
        "Alex Kumar", "alex.student@example.edu", "text",
        "A rainbow is created when sunlight shines through rain drops.",
        email_service=mailer,
        teacher_email="real.teacher@school.edu",
    )
    assert emails[1].to == "real.teacher@school.edu"


def test_pipeline_teacher_email_defaults_to_assignment():
    mailer = MockEmailService()
    _, emails = run_pipeline(
        assignments.get_assignment("sci-rainbows-01"),
        "Alex Kumar", "alex.student@example.edu", "text",
        "A rainbow is created when sunlight shines through rain drops.",
        email_service=mailer,
    )
    assert emails[1].to == "chen.teacher@example.edu"


def test_pipeline_photo_ans_label_shows_student_response():
    # Regression (production 2026-09-14): a photo transcribed as
    # "Q1: Q. How is Rainbow created in the sky?\nAns: Due to rain." showed
    # the question text as the student answer in the emailed sheet.
    mailer = MockEmailService()
    sheet, emails = run_pipeline(
        assignments.get_assignment("sci-rainbows-01"),
        "Vin Test", "vin.test@example.edu", "image",
        sample_path("science_homework.png"),
        transcribed_text=(
            "Q1: Q. How is Rainbow created in the sky?\nAns: Due to rain."
        ),
        email_service=mailer,
        teacher_email="teacher@example.edu",
    )
    ev = sheet.evaluations[0]
    assert ev.student_answer == "Due to rain."
    assert "Due to rain." in emails[0].body
    assert "Student answer: Q. How is Rainbow" not in emails[0].body


def test_pipeline_question_only_transcription_is_no_answer():
    # When the transcription holds only the question, the sheet reports
    # "(no answer provided)" instead of grading the question against itself.
    mailer = MockEmailService()
    sheet, _ = run_pipeline(
        assignments.get_assignment("sci-rainbows-01"),
        "Vin Test", "vin.test@example.edu", "image",
        sample_path("science_homework.png"),
        transcribed_text="Q. How is Rainbow created in the sky?",
        email_service=mailer,
        teacher_email="teacher@example.edu",
    )
    ev = sheet.evaluations[0]
    assert ev.student_answer == "(no answer provided)"
    assert ev.points_earned == 0
