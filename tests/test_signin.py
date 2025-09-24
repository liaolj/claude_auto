from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pytest
from zoneinfo import ZoneInfo

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
from src.signin import CheckInOutcome, SignInError, main


class DummyLogger:
    def __init__(self) -> None:
        self.infos: List[tuple[str, Optional[dict]]] = []
        self.errors: List[tuple[str, Optional[dict]]] = []

    def info(self, message: str, extra: Optional[dict] = None) -> None:
        self.infos.append((message, extra))

    def error(self, message: str, extra: Optional[dict] = None) -> None:
        self.errors.append((message, extra))


class NotifierStub:
    def __init__(self) -> None:
        self.success_calls: List[tuple[str, str]] = []
        self.failure_calls: List[tuple[str, str, Optional[List[Path]]]] = []
        self.config: Optional[Config] = None

    def send_success(self, subject: str, body: str) -> bool:
        self.success_calls.append((subject, body))
        return True

    def send_failure(self, subject: str, body: str, attachments: Optional[List[Path]] = None) -> bool:
        self.failure_calls.append((subject, body, attachments))
        return True


@pytest.fixture
def base_config(tmp_path: Path) -> Config:
    smtp = SMTPConfig(
        host="smtp.example.com",
        port=465,
        use_ssl=True,
        recipients=("ops@example.com",),
    )
    return Config(
        timezone="UTC",
        schedule=ScheduleConfig(),
        notify=NotifyConfig(enable_email=True, smtp=smtp),
        run=RunConfig(max_retries=3, retry_backoff_seconds=(2.5, 5.0, 10.0)),
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


@pytest.fixture
def notifier_stub(monkeypatch) -> NotifierStub:
    stub = NotifierStub()

    def factory(config: Config, tz) -> NotifierStub:
        stub.config = config
        return stub

    monkeypatch.setattr("src.signin.EmailNotifier", factory)
    return stub


@pytest.fixture
def dummy_logger(monkeypatch) -> DummyLogger:
    logger = DummyLogger()
    monkeypatch.setattr("src.signin.setup_logging", lambda config, run_id: logger)
    return logger


@pytest.fixture
def deterministic_run(monkeypatch):
    monkeypatch.setattr("src.signin.generate_run_id", lambda: "run-123")


def configure_time(monkeypatch, timestamps: List[datetime]) -> None:
    iterator = iter(timestamps)
    monkeypatch.setattr("src.signin.now_tz", lambda tz: next(iterator))


def test_main_success_flow(tmp_path, base_config, notifier_stub, dummy_logger, deterministic_run, monkeypatch) -> None:
    config = base_config
    config.notify.success_email_once_per_day = True

    monkeypatch.setattr("src.signin.load_config", lambda: config)
    monkeypatch.setattr("src.signin.ensure_data_tree", lambda *args, **kwargs: None)

    configure_time(
        monkeypatch,
        [
            datetime(2024, 1, 1, 7, 0, tzinfo=ZoneInfo("UTC")),
            datetime(2024, 1, 1, 7, 0, 5, tzinfo=ZoneInfo("UTC")),
        ],
    )

    outcome = CheckInOutcome(status="CHECKIN_OK", notes="done", url="https://example.com/checkin")
    monkeypatch.setattr("src.signin._attempt_checkin", lambda *args, **kwargs: outcome)

    history_records: List[List[str]] = []
    monkeypatch.setattr(
        "src.signin.append_history_entry",
        lambda path, limit, row: history_records.append(row),
    )

    exit_code = main()

    assert exit_code == 0
    assert len(history_records) == 1
    assert history_records[0][3] == "CHECKIN_OK"
    assert len(notifier_stub.success_calls) == 1
    subject, body = notifier_stub.success_calls[0]
    assert subject.startswith("[AnyRouter][OK]")
    assert "Run ID: run-123" in body
    assert not notifier_stub.failure_calls


def test_main_retry_and_failure_flow(tmp_path, base_config, notifier_stub, dummy_logger, deterministic_run, monkeypatch) -> None:
    config = base_config
    config.notify.email_on_failure_always = True
    monkeypatch.setattr("src.signin.load_config", lambda: config)
    monkeypatch.setattr("src.signin.ensure_data_tree", lambda *args, **kwargs: None)

    configure_time(
        monkeypatch,
        [
            datetime(2024, 1, 1, 7, 0, tzinfo=ZoneInfo("UTC")),
            datetime(2024, 1, 1, 7, 0, 30, tzinfo=ZoneInfo("UTC")),
        ],
    )

    screenshot_path = tmp_path / "screenshots" / "failure.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path.write_text("capture")

    attempts = {"count": 0}

    def attempt_stub(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            error = SignInError("TEMP", "temporary failure")
            error.retryable = True
            error.screenshot_path = str(screenshot_path)
            raise error
        error = SignInError("FINAL", "final failure", retryable=False)
        error.screenshot_path = str(screenshot_path)
        raise error

    monkeypatch.setattr("src.signin._attempt_checkin", attempt_stub)

    sleeps: List[float] = []

    class SleepModule:
        @staticmethod
        def sleep(delay: float) -> None:
            sleeps.append(delay)

    monkeypatch.setattr("src.signin.time", SleepModule)

    history_records: List[List[str]] = []
    monkeypatch.setattr(
        "src.signin.append_history_entry",
        lambda path, limit, row: history_records.append(row),
    )

    exit_code = main()

    assert exit_code == 1
    assert attempts["count"] == 2
    assert sleeps == [2.5]
    assert len(history_records) == 1
    assert history_records[0][3] == "CHECKIN_FAIL"
    assert history_records[0][4] == "FINAL"
    assert len(notifier_stub.failure_calls) == 1
    failure_subject, failure_body, attachments = notifier_stub.failure_calls[0]
    assert "FINAL" in failure_subject
    assert attachments and attachments[0] == Path(screenshot_path)
    assert notifier_stub.success_calls == []
