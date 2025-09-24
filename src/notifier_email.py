"""Email notification helpers."""
from __future__ import annotations

import logging
import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, Optional

from zoneinfo import ZoneInfo

from .config import Config
from .utils import (
    now_tz,
    record_success_email_sent,
    should_send_success_email,
)

logger = logging.getLogger(__name__)


class EmailNotifier:
    def __init__(self, config: Config, tz: ZoneInfo) -> None:
        self._config = config
        self._tz = tz

    @property
    def enabled(self) -> bool:
        return self._config.notify.enable_email and self._config.notify.smtp is not None

    def _build_message(
        self,
        subject: str,
        body: str,
        *,
        attachments: Optional[Iterable[Path]] = None,
    ) -> EmailMessage:
        smtp = self._config.notify.smtp
        if smtp is None:
            raise RuntimeError("SMTP configuration missing")
        if not smtp.recipients:
            raise RuntimeError("SMTP recipients list is empty")
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = smtp.sender or smtp.username or "bot@example.com"
        msg["To"] = ", ".join(smtp.recipients)
        msg.set_content(body)
        for attachment in attachments or []:
            if not attachment or not attachment.exists():
                continue
            mime_type, _ = mimetypes.guess_type(attachment.name)
            maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
            with attachment.open("rb") as fh:
                msg.add_attachment(
                    fh.read(),
                    maintype=maintype,
                    subtype=subtype,
                    filename=attachment.name,
                )
        return msg

    def _send(self, message: EmailMessage) -> None:
        smtp = self._config.notify.smtp
        if smtp is None:
            raise RuntimeError("SMTP configuration missing")
        if smtp.use_ssl:
            smtp_cls = smtplib.SMTP_SSL
        else:
            smtp_cls = smtplib.SMTP
        with smtp_cls(smtp.host, smtp.port, timeout=30) as client:
            client.ehlo()
            if smtp.use_starttls and not smtp.use_ssl:
                client.starttls()
                client.ehlo()
            if smtp.username:
                client.login(smtp.username, smtp.password or "")
            client.send_message(message)

    def send_success(
        self,
        subject: str,
        body: str,
    ) -> bool:
        if not self.enabled:
            return False
        now = now_tz(self._tz)
        if (
            self._config.notify.success_email_once_per_day
            and not should_send_success_email(self._config.meta_dir, now)
        ):
            return False
        message = self._build_message(subject, body)
        try:
            self._send(message)
        except (smtplib.SMTPException, OSError):
            logger.exception("Failed to send success notification email")
            return False
        if self._config.notify.success_email_once_per_day:
            record_success_email_sent(self._config.meta_dir, now)
        return True

    def send_failure(
        self,
        subject: str,
        body: str,
        *,
        attachments: Optional[Iterable[Path]] = None,
    ) -> bool:
        if not self.enabled or not self._config.notify.email_on_failure_always:
            return False
        message = self._build_message(subject, body, attachments=attachments)
        try:
            self._send(message)
        except (smtplib.SMTPException, OSError):
            logger.exception("Failed to send failure notification email")
            return False
        return True
