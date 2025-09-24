"""Automated AnyRouter daily check-in."""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from .browser import launch_user_context
from .config import Config, load_config
from .logging_setup import setup_logging
from .notifier_email import EmailNotifier
from .state_check import ensure_logged_in, perform_checkin
from .utils import (
    CheckInOutcome,
    SignInError,
    append_history_entry,
    build_screenshot_path,
    capture_screenshot,
    ensure_data_tree,
    exponential_backoff,
    generate_run_id,
    get_timezone,
    now_tz,
    serialize_duration_ms,
)


def _capture_failure_artifacts(
    page,
    config: Config,
    run_id: str,
    tz,
    *,
    attempt: int,
    error_code: str,
) -> str | None:
    if not config.run.screenshot_on_failure or page is None:
        return None
    ensure_data_tree(config.data_dir, config.screenshots_dir, config.userdata_dir, config.meta_dir)
    ts = now_tz(tz)
    screenshot_path = build_screenshot_path(
        config.screenshots_dir, run_id, ts, attempt=attempt, error_code=error_code
    )
    try:
        capture_screenshot(page, screenshot_path)
        return str(screenshot_path)
    except Exception:  # pragma: no cover - defensive
        return None


def _attempt_checkin(
    config: Config,
    logger,
    run_id: str,
    tz,
    *,
    attempt: int,
    headless: bool,
) -> CheckInOutcome:
    page = None
    context = None
    try:
        with sync_playwright() as playwright:
            context = launch_user_context(playwright, config, headless=headless)
            page = context.new_page()
            logger.info(
                "Navigating to check-in page",
                extra={"step": "navigate", "url": config.site.checkin_url, "attempt": attempt},
            )
            try:
                page.goto(config.site.checkin_url, wait_until="networkidle", timeout=config.run.nav_timeout_ms)
            except PlaywrightTimeoutError as exc:
                raise SignInError("NAV_TIMEOUT", "Timed out waiting for page load") from exc

            ensure_logged_in(page, config)
            outcome = perform_checkin(page, config)
            logger.info("Outcome", extra={"result": outcome.status, "attempt": attempt, "url": page.url})
            return outcome
    except SignInError as exc:
        screenshot_path = _capture_failure_artifacts(page, config, run_id, tz, attempt=attempt, error_code=exc.error_code)
        exc.screenshot_path = screenshot_path
        raise
    except PlaywrightTimeoutError as exc:
        error = SignInError("NAV_TIMEOUT", "Navigation timeout during check-in")
        screenshot_path = _capture_failure_artifacts(page, config, run_id, tz, attempt=attempt, error_code=error.error_code)
        error.screenshot_path = screenshot_path
        raise error from exc
    except Exception as exc:
        error = SignInError("UNKNOWN", f"Unexpected error: {exc}")
        screenshot_path = _capture_failure_artifacts(page, config, run_id, tz, attempt=attempt, error_code=error.error_code)
        error.screenshot_path = screenshot_path
        raise error from exc
    finally:
        if context is not None:
            context.close()


def main() -> int:
    config = load_config()
    tz = get_timezone(config.timezone)
    ensure_data_tree(config.data_dir, config.screenshots_dir, config.userdata_dir, config.meta_dir)
    run_id = generate_run_id()
    logger = setup_logging(config, run_id)
    notifier = EmailNotifier(config, tz)
    logger.info("Starting scheduled check-in", extra={"step": "start"})
    start = now_tz(tz)

    outcome: CheckInOutcome | None = None
    error: SignInError | None = None
    attempts_used = 0

    for attempt in range(1, config.run.max_retries + 1):
        headless = config.run.headless_preferred
        if attempt > 1 and config.run.fallback_to_headed_on_retry:
            headless = False
        logger.info(
            "Attempting check-in",
            extra={"step": "attempt", "attempt": attempt, "headless": headless},
        )
        try:
            outcome = _attempt_checkin(config, logger, run_id, tz, attempt=attempt, headless=headless)
            attempts_used = attempt
            break
        except SignInError as exc:
            attempts_used = attempt
            error = exc
            logger.error(
                "Check-in attempt failed",
                extra={
                    "step": "attempt",
                    "attempt": attempt,
                    "error_code": exc.error_code,
                    "retryable": exc.retryable,
                },
            )
            if not exc.retryable or attempt >= config.run.max_retries:
                break
            delay = exponential_backoff(config.run.retry_backoff_seconds, attempt)
            logger.info("Retrying after backoff", extra={"step": "retry", "delay": delay})
            time.sleep(delay)

    end = now_tz(tz)
    duration = serialize_duration_ms(start, end)

    if outcome is not None:
        result = outcome.status
        error_code = ""
        notes = outcome.notes
        logger.info("Check-in completed", extra={"result": result, "notes": notes})
    else:
        result = "CHECKIN_FAIL"
        error_code = error.error_code if error else "UNKNOWN"
        notes = str(error) if error else "Unknown failure"
        logger.error(
            "Check-in failed",
            extra={"result": result, "error_code": error_code, "notes": notes},
        )

    append_history_entry(
        config.history_file,
        config.run.history_limit,
        [
            end.isoformat(),
            run_id,
            "CHECKIN",
            result,
            error_code,
            str(max(0, attempts_used - 1)),
            str(duration),
            notes,
        ],
    )

    if outcome and outcome.status == "CHECKIN_OK":
        day = end.date()
        subject = f"[AnyRouter][OK] {day.isoformat()}"
        body = (
            f"AnyRouter check-in succeeded.\n"
            f"Run ID: {run_id}\nAttempts: {attempts_used}\n"
            f"Duration: {duration} ms\nURL: {outcome.url or config.site.checkin_url}\n"
        )
        notifier.send_success(subject, body)
    elif outcome and outcome.status == "CHECKIN_ALREADY":
        logger.info("Already checked in for the day; no success email sent")
    else:
        if error:
            ts = end.isoformat()
            subject = f"[AnyRouter][FAIL][{error.error_code}] {ts}"
            screenshot = Path(error.screenshot_path) if error.screenshot_path else None
            body_lines = [
                f"Check-in failed with error {error.error_code}.",
                f"Run ID: {run_id}",
                f"Attempts used: {attempts_used}",
                f"Duration: {duration} ms",
                f"Notes: {notes}",
                f"URL: {config.site.checkin_url}",
            ]
            notifier.send_failure(subject, "\n".join(body_lines), attachments=[screenshot] if screenshot else None)

    return 0 if outcome and outcome.status in {"CHECKIN_OK", "CHECKIN_ALREADY"} else 1


if __name__ == "__main__":
    sys.exit(main())
