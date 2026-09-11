"""Tests for report.py and email_service.py."""

import pytest

from homework_agent import report
from homework_agent.email_service import MockEmailService
from homework_agent.grading import grade_submission


@pytest.fixture()
def graded(math_assignment):
    sheet = grade_submission(math_assignment, {"Q1": "3/4", "Q2": "5", "Q3": "b"})
    sheet.student_name = "Alex Kumar"
    sheet.student_email = "alex.student@example.edu"
    return sheet


def test_markdown_report_marks_and_score(graded):
    md = report.render_markdown(graded)
    assert "Fractions & Basic Algebra" in md
    assert "Q1 - Correct" in md
    assert "Q2 - Incorrect" in md
    assert "Why it's wrong" in md
    assert "Correct answer:" in md
    assert "Score:" in md


def test_plain_text_report(graded):
    text = report.render_plain_text(graded)
    assert "[CORRECT]" in text
    assert "[INCORRECT]" in text
    assert "alex.student@example.edu" in text


def test_subject_lines(graded):
    assert "Fractions & Basic Algebra" in report.student_subject(graded)
    assert "Alex Kumar" in report.teacher_subject(graded)


def test_mock_email_records_message():
    mailer = MockEmailService()
    msg = mailer.send("a@x.edu", "Hi", "body", attachments=["sheet.md"])
    assert mailer.outbox == [msg]
    assert msg.to == "a@x.edu"
    assert msg.attachments == ["sheet.md"]
    assert msg.sent_at != ""


def test_mock_email_rejects_bad_recipient():
    mailer = MockEmailService()
    with pytest.raises(ValueError, match="invalid recipient"):
        mailer.send("not-an-email", "Hi", "body")


def test_mock_email_sent_to_filter():
    mailer = MockEmailService()
    mailer.send("a@x.edu", "s1", "b1")
    mailer.send("b@x.edu", "s2", "b2")
    assert len(mailer.sent_to("a@x.edu")) == 1
    assert mailer.sent_to("nobody@x.edu") == []


def test_mock_email_json_log(tmp_path):
    log = str(tmp_path / "outbox.jsonl")
    mailer = MockEmailService(log_path=log)
    mailer.send("a@x.edu", "Hi", "body")
    with open(log, encoding="utf-8") as f:
        line = f.readline()
    assert '"to": "a@x.edu"' in line
