from __future__ import annotations

from pathlib import Path

from src.browser import launch_user_context
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


class ContextStub:
    def __init__(self) -> None:
        self.extra_headers = None
        self.nav_timeout = None
        self.action_timeout = None
        self.init_scripts = []

    def set_extra_http_headers(self, headers):
        self.extra_headers = headers

    def set_default_navigation_timeout(self, value: int) -> None:
        self.nav_timeout = value

    def set_default_timeout(self, value: int) -> None:
        self.action_timeout = value

    def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)


class ChromiumStub:
    def __init__(self, context: ContextStub) -> None:
        self.context = context
        self.launch_kwargs = None

    def launch_persistent_context(self, **kwargs):
        self.launch_kwargs = kwargs
        return self.context


class PlaywrightStub:
    def __init__(self, chromium: ChromiumStub) -> None:
        self.chromium = chromium


def make_config(tmp_path: Path) -> Config:
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
        run=RunConfig(
            nav_timeout_ms=12345,
            action_timeout_ms=6789,
            chromium_launch_args=("--foo",),
            browser_locale="en-US",
        ),
        selectors=SelectorConfig(),
        site=SiteConfig(base_url="https://example.com", checkin_url="https://example.com"),
        logging=LoggingConfig(log_file=tmp_path / "logs.jsonl"),
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        history_file=tmp_path / "data" / "history.csv",
        screenshots_dir=tmp_path / "screenshots",
        userdata_dir=tmp_path / "userdata",
        meta_dir=tmp_path / "meta",
    )


def test_launch_user_context_configures_locale_and_headers(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    context = ContextStub()
    chromium = ChromiumStub(context)
    playwright = PlaywrightStub(chromium)

    result = launch_user_context(playwright, config, headless=True)

    assert result is context
    assert chromium.launch_kwargs["headless"] is True
    assert chromium.launch_kwargs["locale"] == "en-US"
    assert "--foo" in chromium.launch_kwargs["args"]
    assert any(arg.startswith("--lang=en-US") for arg in chromium.launch_kwargs["args"])
    assert context.extra_headers == {"Accept-Language": "en-US,en;q=0.9"}
    assert context.nav_timeout == 12345
    assert context.action_timeout == 6789
    assert any("navigator" in script for script in context.init_scripts)


def test_launch_user_context_respects_custom_accept_language(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    config.run.accept_language = "en-GB,en;q=0.9"
    context = ContextStub()
    chromium = ChromiumStub(context)
    playwright = PlaywrightStub(chromium)

    launch_user_context(playwright, config, headless=False)

    assert chromium.launch_kwargs["headless"] is False
    assert context.extra_headers == {"Accept-Language": "en-GB,en;q=0.9"}
