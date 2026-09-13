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


def test_smtp_email_service_sends_via_smtp(monkeypatch):
    from homework_agent.email_service import SmtpEmailService

    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            sent["host"], sent["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, msg, from_addr=None, to_addrs=None):
            sent["msg"] = msg
            sent["from"] = from_addr
            sent["to"] = to_addrs

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    svc = SmtpEmailService(
        sender="grader@example.edu", username="grader@example.edu", password="secret"
    )
    out = svc.send(
        to="teacher@school.edu", subject="Graded", body="sheet", cc=["s@x.edu"]
    )
    assert sent["host"] == "smtp.gmail.com"
    assert sent["tls"] is True
    assert sent["login"] == ("grader@example.edu", "secret")
    assert sent["from"] == "grader@example.edu"
    assert sent["to"] == ["teacher@school.edu", "s@x.edu"]
    assert sent["msg"]["Subject"] == "Graded"
    assert out.to == "teacher@school.edu"
    assert svc.sent_to("teacher@school.edu") == [out]


def test_smtp_email_service_rejects_bad_sender():
    from homework_agent.email_service import SmtpEmailService

    import pytest

    with pytest.raises(ValueError):
        SmtpEmailService(sender="not-an-email", username="x", password="y")
    with pytest.raises(ValueError):
        SmtpEmailService(sender="a@b.com", username="a@b.com", password="")


def test_make_email_service_falls_back_to_mock(monkeypatch):
    from homework_agent.email_service import (
        MockEmailService,
        SmtpEmailService,
        make_email_service,
    )

    monkeypatch.delenv("GMAIL_SENDER", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    assert isinstance(make_email_service(), MockEmailService)

    monkeypatch.setenv("GMAIL_SENDER", "grader@example.edu")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "secret")
    svc = make_email_service()
    assert isinstance(svc, SmtpEmailService)
    assert svc.sender == "grader@example.edu"
