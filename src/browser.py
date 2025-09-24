"""Browser helper utilities for Playwright launches."""
from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from playwright.sync_api import BrowserContext, Playwright
else:  # pragma: no cover - runtime fallback for tests without Playwright
    BrowserContext = object  # type: ignore[assignment]
    Playwright = object  # type: ignore[assignment]

from .config import Config


def _accept_language_header(locale: str | None) -> str:
    if not locale:
        return "en-US,en;q=0.9"
    lang = locale.split("-")[0]
    if lang.lower() == "en" and locale.lower() != "en":
        return f"{locale},en;q=0.9"
    return f"{locale},{lang};q=0.9,en;q=0.8"


def launch_user_context(playwright: Playwright, config: Config, *, headless: bool) -> BrowserContext:
    """Launch the persistent Chromium context optimized for automation."""
    launch_args: List[str] = [str(arg) for arg in config.run.chromium_launch_args]
    locale = config.run.browser_locale
    if locale and not any(arg.startswith("--lang=") for arg in launch_args):
        launch_args.append(f"--lang={locale}")

    launch_kwargs: Dict[str, object] = {
        "user_data_dir": str(config.userdata_dir),
        "headless": headless,
    }
    if locale:
        launch_kwargs["locale"] = locale
    if launch_args:
        launch_kwargs["args"] = launch_args

    context = playwright.chromium.launch_persistent_context(**launch_kwargs)
    accept_language = config.run.accept_language or _accept_language_header(locale)
    context.set_extra_http_headers({"Accept-Language": accept_language})
    context.set_default_navigation_timeout(config.run.nav_timeout_ms)
    context.set_default_timeout(config.run.action_timeout_ms)
    if locale:
        context.add_init_script(
            """
            (() => {
                const locale = %r;
                Object.defineProperty(navigator, 'language', { value: locale, configurable: true });
                Object.defineProperty(navigator, 'languages', { value: [locale, 'en'], configurable: true });
            })();
            """
            % locale
        )
    return context
