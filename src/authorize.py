"""Manual GitHub OAuth helper to seed the persistent session."""
from __future__ import annotations

import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from .config import load_config
from .logging_setup import setup_logging
from .utils import (
    SignInError,
    append_history_entry,
    ensure_data_tree,
    generate_run_id,
    get_timezone,
    now_tz,
    serialize_duration_ms,
)


def main() -> int:
    config = load_config()
    tz = get_timezone(config.timezone)
    ensure_data_tree(config.data_dir, config.screenshots_dir, config.userdata_dir, config.meta_dir)
    run_id = generate_run_id()
    logger = setup_logging(config, run_id)
    start = now_tz(tz)
    stage = "AUTH"
    result = "AUTH_OK"
    error_code = ""
    notes = "GitHub OAuth completed"

    logger.info("Launching browser for manual authorization", extra={"step": "authorize"})

    context = None
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(config.userdata_dir),
                headless=False,
            )
            page = context.new_page()
            page.set_default_navigation_timeout(config.run.nav_timeout_ms)
            page.set_default_timeout(config.run.action_timeout_ms)
            logger.info("Navigating to base URL", extra={"step": "navigate", "url": config.site.base_url})
            try:
                page.goto(config.site.base_url, wait_until="networkidle", timeout=config.run.nav_timeout_ms)
            except PlaywrightTimeoutError as exc:
                raise SignInError("NAV_TIMEOUT", "Timed out opening base URL", retryable=False) from exc

            print(
                """
================================================================================
Manual authorization required.
1. Use the opened browser window to complete GitHub OAuth for https://anyrouter.top/.
2. Verify the dashboard loads successfully.
3. Return to this terminal and press ENTER when finished.
================================================================================
"""
            )
            input("Press ENTER once authorization is complete...")
            context.storage_state(path=str(config.data_dir / "auth_state.json"))
    except SignInError as exc:
        result = "AUTH_FAIL"
        error_code = exc.error_code
        notes = str(exc)
        logger.error("Authorization failed", extra={"error_code": exc.error_code, "step": stage})
    except Exception as exc:  # pragma: no cover - defensive
        result = "AUTH_FAIL"
        error_code = "UNKNOWN"
        notes = str(exc)
        logger.exception("Unexpected failure during authorization", extra={"step": stage})

    finally:
        if context is not None:
            try:
                context.close()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.warning("Failed to close browser context", extra={"step": stage})

    end = now_tz(tz)
    duration = serialize_duration_ms(start, end)
    append_history_entry(
        config.history_file,
        config.run.history_limit,
        [
            end.isoformat(),
            run_id,
            stage,
            result,
            error_code,
            "0",
            str(duration),
            notes,
        ],
    )
    logger.info("Authorization complete", extra={"result": result, "error_code": error_code})
    return 0 if result == "AUTH_OK" else 1


if __name__ == "__main__":
    sys.exit(main())
