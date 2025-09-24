from __future__ import annotations

from dataclasses import replace
from typing import Callable, Dict, Optional

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
from src.state_check import (
    PlaywrightTimeoutError,
    ensure_logged_in,
    evaluate_checkin_state,
    perform_checkin,
)
from src.utils import CheckInOutcome, SignInError


class LocatorStub:
    def __init__(self, behavior: Dict[str, Callable]):
        self._behavior = behavior
        self.first = self

    def wait_for(self, *, state: str, timeout: int) -> None:
        func: Optional[Callable] = self._behavior.get("wait_for")
        if func is None:
            raise PlaywrightTimeoutError("timeout")
        func(state=state, timeout=timeout)

    def click(self, *, timeout: int) -> None:
        func: Optional[Callable] = self._behavior.get("click")
        if func is None:
            raise PlaywrightTimeoutError("click timeout")
        func(timeout=timeout)


class PageStub:
    def __init__(self, behaviors: Dict[str, Dict[str, Callable]], url: str = "https://example.com") -> None:
        self._behaviors = behaviors
        self.url = url

    def locator(self, selector: str) -> LocatorStub:
        return LocatorStub(self._behaviors.get(selector, {}))


@pytest.fixture
def base_config(tmp_path):
    smtp = SMTPConfig(
        host="smtp.example.com",
        port=465,
        use_ssl=True,
        recipients=("ops@example.com",),
    )
    config = Config(
        timezone="UTC",
        schedule=ScheduleConfig(),
        notify=NotifyConfig(enable_email=True, smtp=smtp),
        run=RunConfig(action_timeout_ms=1000),
        selectors=SelectorConfig(
            login_required=("#login",),
            login_confirmed=("#ok",),
            checkin_triggers=("button.checkin",),
            success_indicators=(".success",),
            already_checked=(".already",),
        ),
        site=SiteConfig(base_url="https://example.com", checkin_url="https://example.com/checkin"),
        logging=LoggingConfig(log_file=tmp_path / "log.jsonl"),
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        history_file=tmp_path / "data" / "history.csv",
        screenshots_dir=tmp_path / "screenshots",
        userdata_dir=tmp_path / "userdata",
        meta_dir=tmp_path / "meta",
    )
    return config


def test_ensure_logged_in_requires_reauthentication(base_config):
    page = PageStub({"#login": {"wait_for": lambda **_: None}})
    with pytest.raises(SignInError) as exc:
        ensure_logged_in(page, base_config)
    assert exc.value.error_code == "NEED_AUTH"


def test_ensure_logged_in_validates_confirmation(base_config):
    page = PageStub({"#ok": {"wait_for": lambda **_: None}})
    ensure_logged_in(page, base_config)


def test_ensure_logged_in_raises_when_confirmation_missing(base_config):
    page = PageStub({})
    with pytest.raises(SignInError) as exc:
        ensure_logged_in(page, base_config)
    assert exc.value.error_code == "NEED_AUTH"


def test_evaluate_checkin_state_reports_already_checked(base_config):
    page = PageStub({".already": {"wait_for": lambda **_: None}})
    outcome = evaluate_checkin_state(page, base_config)
    assert isinstance(outcome, CheckInOutcome)
    assert outcome.status == "CHECKIN_ALREADY"


def test_perform_checkin_success(base_config):
    behaviors = {
        "button.checkin": {
            "wait_for": lambda **_: None,
            "click": lambda **_: None,
        },
        ".success": {"wait_for": lambda **_: None},
    }
    page = PageStub(behaviors)
    outcome = perform_checkin(page, base_config)
    assert outcome.status == "CHECKIN_OK"


def test_perform_checkin_detects_already_checked_after_click(base_config):
    behaviors = {
        "button.checkin": {
            "wait_for": lambda **_: None,
            "click": lambda **_: None,
        },
        ".success": {},
        ".already": {"wait_for": lambda **_: None},
    }
    page = PageStub(behaviors)
    outcome = perform_checkin(page, base_config)
    assert outcome.status == "CHECKIN_ALREADY"


def test_perform_checkin_raises_when_trigger_missing(base_config):
    config = replace(base_config, selectors=replace(base_config.selectors, checkin_triggers=(".missing",)))
    page = PageStub({})
    with pytest.raises(SignInError) as exc:
        perform_checkin(page, config)
    assert exc.value.error_code == "SELECTOR_CHANGED"


def test_perform_checkin_raises_when_no_success_indicators(base_config):
    config = replace(
        base_config,
        selectors=replace(
            base_config.selectors,
            success_indicators=(".success",),
            already_checked=(),
        ),
    )
    behaviors = {
        "button.checkin": {
            "wait_for": lambda **_: None,
            "click": lambda **_: None,
        },
        ".success": {},
    }
    page = PageStub(behaviors)
    with pytest.raises(SignInError) as exc:
        perform_checkin(page, config)
    assert exc.value.error_code == "UNKNOWN"
