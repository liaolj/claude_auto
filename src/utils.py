"""Utility helpers for AnyRouter automation."""
from __future__ import annotations

import csv
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from zoneinfo import ZoneInfo


class SignInError(Exception):
    """Exception representing a domain-specific failure with an error code."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        retryable: bool = True,
        screenshot_path: Optional[Path] = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable
        self.screenshot_path = screenshot_path


@dataclass
class CheckInOutcome:
    status: str
    notes: str = ""
    url: Optional[str] = None


_META_SUCCESS_FILE = "last_success_email.json"


def ensure_directories(paths: Iterable[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def ensure_data_tree(
    data_dir: Path,
    screenshots_dir: Path,
    userdata_dir: Path,
    meta_dir: Path,
) -> None:
    ensure_directories((data_dir, screenshots_dir, userdata_dir, meta_dir, data_dir / "logs"))


def get_timezone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def now_tz(tz: ZoneInfo | None = None) -> datetime:
    tzinfo = tz or timezone.utc
    return datetime.now(tzinfo)


def generate_run_id() -> str:
    return uuid.uuid4().hex


def history_header() -> list[str]:
    return ["ts", "run_id", "stage", "result", "error_code", "retry_count", "duration_ms", "notes"]


def append_history_entry(path: Path, limit: int, row: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[list[str]] = []
    if path.exists():
        with path.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            lines = list(reader)
    if not lines:
        lines.append(history_header())
    lines.append(row)
    header, *entries = lines
    max_entries = max(limit, 1)
    if len(entries) > max_entries:
        entries = entries[-max_entries:]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(entries)


def success_email_state_path(meta_dir: Path) -> Path:
    return meta_dir / _META_SUCCESS_FILE


def should_send_success_email(meta_dir: Path, current_date: datetime) -> bool:
    path = success_email_state_path(meta_dir)
    if not path.exists():
        return True
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        sent_on = data.get("date")
        if not sent_on:
            return True
        return sent_on != current_date.date().isoformat()
    except json.JSONDecodeError:
        return True


def record_success_email_sent(meta_dir: Path, current_date: datetime) -> None:
    path = success_email_state_path(meta_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"date": current_date.date().isoformat(), "ts": current_date.isoformat()}
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def build_screenshot_path(
    screenshots_dir: Path,
    run_id: str,
    current_time: datetime,
    *,
    attempt: int,
    error_code: str,
) -> Path:
    slug = f"{current_time.strftime('%Y%m%dT%H%M%S')}_{run_id}_a{attempt}_{error_code.lower()}"
    return screenshots_dir / f"{slug}.png"


def exponential_backoff(seconds: Iterable[float], attempt: int) -> float:
    seq = list(seconds)
    if not seq:
        return float(attempt * attempt)
    idx = min(attempt - 1, len(seq) - 1)
    return float(seq[idx])


def sleep_backoff(seconds: Iterable[float], attempt: int) -> None:
    time.sleep(exponential_backoff(seconds, attempt))


def serialize_duration_ms(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() * 1000)


def capture_screenshot(page, path: Path) -> Path:
    page.screenshot(path=str(path), full_page=True)
    return path


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
