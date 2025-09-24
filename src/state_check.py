"""State validation helpers for the AnyRouter flows."""
from __future__ import annotations

from typing import Iterable, Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .config import Config
from .utils import CheckInOutcome, SignInError


def _wait_for_any(page: Page, selectors: Iterable[str], *, timeout: int, state: str = "visible") -> bool:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state=state, timeout=timeout)
            return True
        except PlaywrightTimeoutError:
            continue
    return False


def ensure_logged_in(page: Page, config: Config) -> None:
    selectors = config.selectors
    run_cfg = config.run
    if selectors.login_required and _wait_for_any(
        page, selectors.login_required, timeout=run_cfg.action_timeout_ms
    ):
        raise SignInError("NEED_AUTH", "Login indicator detected; session renewal required", retryable=False)
    if selectors.login_confirmed:
        if not _wait_for_any(page, selectors.login_confirmed, timeout=run_cfg.action_timeout_ms):
            raise SignInError("NEED_AUTH", "Unable to confirm authenticated session", retryable=False)


def evaluate_checkin_state(page: Page, config: Config) -> Optional[CheckInOutcome]:
    selectors = config.selectors
    run_cfg = config.run
    if selectors.already_checked and _wait_for_any(
        page, selectors.already_checked, timeout=run_cfg.action_timeout_ms
    ):
        return CheckInOutcome(status="CHECKIN_ALREADY", notes="Already signed in", url=page.url)
    return None


def perform_checkin(page: Page, config: Config) -> CheckInOutcome:
    selectors = config.selectors
    run_cfg = config.run
    preexisting = evaluate_checkin_state(page, config)
    if preexisting is not None:
        return preexisting

    clicked = False
    for selector in selectors.checkin_triggers:
        locator = page.locator(selector).first
        try:
            locator.wait_for(state="attached", timeout=run_cfg.action_timeout_ms)
            locator.click(timeout=run_cfg.action_timeout_ms)
            clicked = True
            break
        except PlaywrightTimeoutError:
            continue
    if not clicked:
        raise SignInError("SELECTOR_CHANGED", "Unable to locate check-in trigger", retryable=False)

    if selectors.success_indicators and _wait_for_any(
        page, selectors.success_indicators, timeout=run_cfg.action_timeout_ms
    ):
        return CheckInOutcome(status="CHECKIN_OK", notes="Success indicator detected", url=page.url)
    if selectors.already_checked and _wait_for_any(
        page, selectors.already_checked, timeout=run_cfg.action_timeout_ms
    ):
        return CheckInOutcome(status="CHECKIN_ALREADY", notes="Check-in already completed", url=page.url)

    raise SignInError("UNKNOWN", "No success indicator after click", retryable=True)
