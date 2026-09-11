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
