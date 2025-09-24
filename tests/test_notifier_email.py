from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path
from typing import List

import pytest

from src.config import (
    Config,
    LoggingConfig,
    NotifyConfig,
    RunConfig,
    ScheduleConfig,
    SelectorConfig,
    SiteConfig,
    SMTPConfig,
)
from src.notifier_email import EmailNotifier


@pytest.fixture
def config_with_email(tmp_path: Path) -> Config:
    smtp = SMTPConfig(
        host="smtp.example.com",
        port=465,
        use_ssl=True,
        username="bot",
        password="secret",
        sender="bot@example.com",
        recipients=("ops@example.com",),
    )
    return Config(
        timezone="UTC",
        schedule=ScheduleConfig(),
        notify=NotifyConfig(enable_email=True, smtp=smtp),
        run=RunConfig(),
        selectors=SelectorConfig(),
        site=SiteConfig(base_url="https://example.com", checkin_url="https://example.com/checkin"),
        logging=LoggingConfig(log_file=tmp_path / "logs.jsonl"),
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        history_file=tmp_path / "data" / "history.csv",
        screenshots_dir=tmp_path / "screenshots",
        userdata_dir=tmp_path / "userdata",
        meta_dir=tmp_path / "meta",
    )


class SendRecorder:
    def __init__(self) -> None:
        self.sent: List[EmailMessage] = []

    def __call__(self, message: EmailMessage) -> None:
        self.sent.append(message)


def test_send_success_dispatches_and_records(config_with_email, monkeypatch) -> None:
    notifier = EmailNotifier(config_with_email, tz=None)

    monkeypatch.setattr("src.notifier_email.should_send_success_email", lambda *_: True)
    recorded: List[Path] = []
    monkeypatch.setattr("src.notifier_email.record_success_email_sent", lambda meta_dir, now: recorded.append(meta_dir))
    sender = SendRecorder()
    monkeypatch.setattr(EmailNotifier, "_send", lambda self, message: sender(message))

    result = notifier.send_success("Subject", "Body")

    assert result is True
    assert len(sender.sent) == 1
    message = sender.sent[0]
    assert message["Subject"] == "Subject"
    assert "ops@example.com" in message["To"]
    assert recorded == [config_with_email.meta_dir]


def test_send_success_skips_when_disabled(config_with_email) -> None:
    notifier = EmailNotifier(config_with_email, tz=None)
    notifier._config.notify.enable_email = False
    assert notifier.send_success("Subject", "Body") is False


def test_send_success_respects_daily_limit(config_with_email, monkeypatch) -> None:
    notifier = EmailNotifier(config_with_email, tz=None)
    monkeypatch.setattr("src.notifier_email.should_send_success_email", lambda *_: False)
    monkeypatch.setattr(EmailNotifier, "_send", lambda self, message: (_ for _ in ()).throw(RuntimeError("should not send")))
    assert notifier.send_success("Subject", "Body") is False


def test_send_failure_with_attachments(config_with_email, tmp_path, monkeypatch) -> None:
    notifier = EmailNotifier(config_with_email, tz=None)
    attachment = tmp_path / "failure.png"
    attachment.write_bytes(b"content")

    sender = SendRecorder()
    monkeypatch.setattr(EmailNotifier, "_send", lambda self, message: sender(message))

    result = notifier.send_failure("Subject", "Body", attachments=[attachment])

    assert result is True
    assert len(sender.sent) == 1
    message = sender.sent[0]
    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "failure.png"


def test_send_failure_skips_when_disabled(config_with_email) -> None:
    notifier = EmailNotifier(config_with_email, tz=None)
    notifier._config.notify.email_on_failure_always = False
    assert notifier.send_failure("Subject", "Body") is False
