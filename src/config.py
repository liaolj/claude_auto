"""Configuration loading utilities for AnyRouter automation."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

try:  # Python 3.11+
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - fallback for older versions
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass
class SMTPConfig:
    host: str
    port: int
    use_ssl: bool = True
    use_starttls: bool = False
    username: Optional[str] = None
    password: Optional[str] = None
    sender: Optional[str] = None
    recipients: Sequence[str] = field(default_factory=list)


@dataclass
class NotifyConfig:
    enable_email: bool = False
    success_email_once_per_day: bool = True
    email_on_failure_always: bool = True
    smtp: Optional[SMTPConfig] = None


@dataclass
class ScheduleConfig:
    times: Sequence[str] = field(default_factory=lambda: ("08:30", "12:30", "20:30"))


@dataclass
class RunConfig:
    headless_preferred: bool = True
    fallback_to_headed_on_retry: bool = True
    nav_timeout_ms: int = 20000
    action_timeout_ms: int = 15000
    max_retries: int = 3
    retry_backoff_seconds: Sequence[float] = field(default_factory=lambda: (1.0, 4.0, 9.0))
    history_limit: int = 1000
    screenshot_on_failure: bool = True
    trace_on_failure: bool = False
    log_max_bytes: int = 1_000_000
    log_backup_count: int = 7


@dataclass
class SelectorConfig:
    login_required: Sequence[str] = field(default_factory=list)
    login_confirmed: Sequence[str] = field(default_factory=list)
    checkin_triggers: Sequence[str] = field(default_factory=list)
    success_indicators: Sequence[str] = field(default_factory=list)
    already_checked: Sequence[str] = field(default_factory=list)


@dataclass
class SiteConfig:
    base_url: str
    checkin_url: str


@dataclass
class LoggingConfig:
    log_file: Path


@dataclass
class Config:
    timezone: str
    schedule: ScheduleConfig
    notify: NotifyConfig
    run: RunConfig
    selectors: SelectorConfig
    site: SiteConfig
    logging: LoggingConfig
    project_root: Path
    data_dir: Path
    history_file: Path
    screenshots_dir: Path
    userdata_dir: Path
    meta_dir: Path


def _load_smtp(data: Dict[str, Any]) -> SMTPConfig:
    return SMTPConfig(
        host=data.get("host", ""),
        port=int(data.get("port", 465)),
        use_ssl=bool(data.get("use_ssl", True)),
        use_starttls=bool(data.get("use_starttls", False)),
        username=data.get("username"),
        password=data.get("password"),
        sender=data.get("from"),
        recipients=tuple(data.get("to", []) or []),
    )


def _load_notify(data: Dict[str, Any]) -> NotifyConfig:
    smtp_cfg = data.get("smtp")
    smtp = _load_smtp(smtp_cfg) if isinstance(smtp_cfg, dict) else None
    return NotifyConfig(
        enable_email=bool(data.get("enable_email", False)),
        success_email_once_per_day=bool(data.get("success_email_once_per_day", True)),
        email_on_failure_always=bool(data.get("email_on_failure_always", True)),
        smtp=smtp,
    )


def _load_schedule(data: Dict[str, Any]) -> ScheduleConfig:
    times = data.get("times", ["08:30", "12:30", "20:30"])
    return ScheduleConfig(times=tuple(times))


def _load_run(data: Dict[str, Any]) -> RunConfig:
    retry_backoff = data.get("retry_backoff_seconds") or (1.0, 4.0, 9.0)
    return RunConfig(
        headless_preferred=bool(data.get("headless_preferred", True)),
        fallback_to_headed_on_retry=bool(data.get("fallback_to_headed_on_retry", True)),
        nav_timeout_ms=int(data.get("nav_timeout_ms", 20000)),
        action_timeout_ms=int(data.get("action_timeout_ms", 15000)),
        max_retries=int(data.get("max_retries", 3)),
        retry_backoff_seconds=tuple(float(v) for v in retry_backoff),
        history_limit=int(data.get("history_limit", 1000)),
        screenshot_on_failure=bool(data.get("screenshot_on_failure", True)),
        trace_on_failure=bool(data.get("trace_on_failure", False)),
        log_max_bytes=int(data.get("log_max_bytes", 1_000_000)),
        log_backup_count=int(data.get("log_backup_count", 7)),
    )


def _load_selectors(data: Dict[str, Any]) -> SelectorConfig:
    return SelectorConfig(
        login_required=tuple(data.get("login_required", [])),
        login_confirmed=tuple(data.get("login_confirmed", [])),
        checkin_triggers=tuple(data.get("checkin_triggers", [])),
        success_indicators=tuple(data.get("success_indicators", [])),
        already_checked=tuple(data.get("already_checked", [])),
    )


def _load_site(data: Dict[str, Any]) -> SiteConfig:
    base_url = data.get("base_url") or "https://anyrouter.top/"
    checkin_url = data.get("checkin_url") or base_url
    return SiteConfig(base_url=base_url, checkin_url=checkin_url)


def _load_logging(data: Dict[str, Any], project_root: Path) -> LoggingConfig:
    log_path = data.get("log_file") or "data/logs/signin.jsonl"
    log_file = (project_root / log_path).resolve()
    return LoggingConfig(log_file=log_file)


def load_config(path: Path | str = "config.toml") -> Config:
    """Load configuration from ``config.toml`` and expand derived paths."""
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with config_path.open("rb") as fh:
        raw: Dict[str, Any] = tomllib.load(fh)

    project_root = config_path.parent.resolve()
    timezone = raw.get("timezone") or "Europe/Helsinki"
    schedule = _load_schedule(raw.get("schedule", {}))
    notify = _load_notify(raw.get("notify", {}))
    run = _load_run(raw.get("run", {}))
    selectors = _load_selectors(raw.get("selectors", {}))
    site = _load_site(raw.get("site", {}))
    logging_cfg = _load_logging(raw.get("logging", {}), project_root)

    data_dir = (project_root / "data").resolve()
    history_file = data_dir / "history.csv"
    screenshots_dir = (project_root / "screenshots").resolve()
    userdata_dir = data_dir / "userdata"
    meta_dir = data_dir / "meta"

    return Config(
        timezone=timezone,
        schedule=schedule,
        notify=notify,
        run=run,
        selectors=selectors,
        site=site,
        logging=logging_cfg,
        project_root=project_root,
        data_dir=data_dir,
        history_file=history_file,
        screenshots_dir=screenshots_dir,
        userdata_dir=userdata_dir,
        meta_dir=meta_dir,
    )
