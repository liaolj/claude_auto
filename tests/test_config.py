from __future__ import annotations

from pathlib import Path

import pytest

from src.config import (
    Config,
    load_config,
)


def write_config(tmp_path: Path) -> Path:
    content = """
timezone = "America/New_York"

[notify]
enable_email = true
success_email_once_per_day = true
email_on_failure_always = false

  [notify.smtp]
  host = "smtp.example.com"
  port = 587
  use_ssl = false
  use_starttls = true
  username = "bot"
  password = "secret"
  from = "bot@example.com"
  to = ["ops@example.com", "alerts@example.com"]

[run]
max_retries = 5
retry_backoff_seconds = [1.5, 3.0, 6.0]
history_limit = 50
screenshot_on_failure = false

[selectors]
login_required = ["#login"]
login_confirmed = ["#logged-in"]
checkin_triggers = ["button.checkin"]
success_indicators = [".alert-success"]
already_checked = [".already"]

[site]
base_url = "https://example.com"
checkin_url = "https://example.com/checkin"

[logging]
log_file = "logs/signin.jsonl"
"""
    path = tmp_path / "config.toml"
    path.write_text(content)
    return path


def test_load_config_expands_paths(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    config = load_config(path)
    assert isinstance(config, Config)
    assert config.project_root == tmp_path.resolve()
    assert config.data_dir == tmp_path.resolve() / "data"
    assert config.history_file == config.data_dir / "history.csv"
    assert config.screenshots_dir == tmp_path.resolve() / "screenshots"
    assert config.logging.log_file == tmp_path.resolve() / "logs" / "signin.jsonl"
    assert config.notify.smtp is not None
    assert config.notify.smtp.port == 587
    assert config.notify.smtp.use_starttls is True
    assert config.notify.smtp.recipients == ("ops@example.com", "alerts@example.com")
    assert config.run.retry_backoff_seconds == (1.5, 3.0, 6.0)
    assert config.selectors.login_required == ("#login",)


def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"
    with pytest.raises(FileNotFoundError):
        load_config(missing)
