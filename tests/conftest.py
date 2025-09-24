"""Shared pytest fixtures and Playwright test doubles."""
from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


if "playwright" not in sys.modules:
    sys.modules["playwright"] = types.ModuleType("playwright")

sync_api = types.ModuleType("playwright.sync_api")


class DummyTimeoutError(Exception):
    """Replacement for Playwright's TimeoutError used during tests."""


def _unavailable_sync_playwright(*args, **kwargs):  # pragma: no cover - guardrail
    raise RuntimeError("sync_playwright is not available in the test doubles")


def _setup_sync_api_module() -> None:
    sync_api.TimeoutError = DummyTimeoutError
    sync_api.Page = object  # type: ignore[attr-defined]
    sync_api.sync_playwright = _unavailable_sync_playwright
    sys.modules["playwright.sync_api"] = sync_api


_setup_sync_api_module()
