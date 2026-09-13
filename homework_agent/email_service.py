"""Mock email service used for the local demo.

In production this is replaced with a real provider (Gmail API, SMTP, ...).
Every sent message is recorded in an in-memory outbox and appended to a JSON
log file so tests and demos can inspect exactly what would have been emailed.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


@dataclass
class EmailMessage:
    to: str
    subject: str
    body: str
    cc: List[str] = field(default_factory=list)
    attachments: List[str] = field(default_factory=list)  # filenames / descriptions
    sent_at: str = ""


class MockEmailService:
    """A fake mailer that records messages instead of delivering them."""

    def __init__(self, log_path: Optional[str] = None) -> None:
        self.outbox: List[EmailMessage] = []
        self.log_path = log_path

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        attachments: Optional[List[str]] = None,
    ) -> EmailMessage:
        if not to or "@" not in to:
            raise ValueError(f"Refusing to send email: invalid recipient {to!r}")
        msg = EmailMessage(
            to=to,
            subject=subject,
            body=body,
            cc=cc or [],
            attachments=attachments or [],
            sent_at=datetime.now(timezone.utc).isoformat(),
        )
        self.outbox.append(msg)
        if self.log_path:
            os.makedirs(os.path.dirname(os.path.abspath(self.log_path)), exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(msg)) + "\n")
        return msg

    def sent_to(self, address: str) -> List[EmailMessage]:
        return [m for m in self.outbox if m.to == address]

    def clear(self) -> None:
        self.outbox.clear()


class SmtpEmailService:
    """Real email delivery via SMTP (e.g. Gmail with an App Password).

    ``sender`` is the From address shown on every message. Credentials are
    passed explicitly so they never live in code — on Modal they come from
    a Modal secret, locally from environment variables.
    """

    def __init__(
        self,
        sender: str,
        username: str,
        password: str,
        host: str = "smtp.gmail.com",
        port: int = 587,
    ) -> None:
        if not sender or "@" not in sender:
            raise ValueError(f"Invalid sender address {sender!r}")
        if not password:
            raise ValueError("SMTP password is required")
        self.sender = sender
        self.username = username or sender
        self.password = password
        self.host = host
        self.port = port
        self.outbox: List[EmailMessage] = []

    def send(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        attachments: Optional[List[str]] = None,
    ) -> EmailMessage:
        if not to or "@" not in to:
            raise ValueError(f"Refusing to send email: invalid recipient {to!r}")
        import smtplib
        from email.message import EmailMessage as PyEmailMessage

        msg = PyEmailMessage()
        msg["From"] = self.sender
        msg["To"] = to
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        msg.set_content(body)
        recipients = [to] + list(cc or [])
        with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(self.username, self.password)
            smtp.send_message(msg, from_addr=self.sender, to_addrs=recipients)
        sent = EmailMessage(
            to=to,
            subject=subject,
            body=body,
            cc=cc or [],
            attachments=attachments or [],
            sent_at=datetime.now(timezone.utc).isoformat(),
        )
        self.outbox.append(sent)
        return sent

    def sent_to(self, address: str) -> List[EmailMessage]:
        return [m for m in self.outbox if m.to == address]

    def clear(self) -> None:
        self.outbox.clear()


def make_email_service() -> MockEmailService | SmtpEmailService:
    """Build the configured mailer: real SMTP when credentials are set.

    Reads GMAIL_SENDER and GMAIL_APP_PASSWORD from the environment (Modal
    secret on the deployment). Falls back to the mock mailer so local
    development and tests never send real email by accident.
    """
    sender = os.environ.get("GMAIL_SENDER", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if sender and password:
        return SmtpEmailService(sender=sender, username=sender, password=password)
    return MockEmailService()
