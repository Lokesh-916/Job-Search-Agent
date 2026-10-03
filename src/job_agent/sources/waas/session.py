"""Interactive WaaS login that saves a reusable Playwright session (cookies + storage).

The saved file is copied to the lab PC so scheduled headless runs stay logged in.
"""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from job_agent.settings import BrowserConfig

WAAS_URL = "https://www.workatastartup.com"
LOGIN_URL = f"{WAAS_URL}/companies"


def interactive_login(browser_cfg: BrowserConfig, session_path: Path, timeout_s: int = 600) -> bool:
    """Open a visible browser, let the user sign in, save the session when they close it.

    The session is re-saved every couple of seconds while the browser shows a WaaS page,
    so closing the window at any point after logging in keeps the latest state.
    Returns True once a WaaS page was seen after login.
    """
    session_path.parent.mkdir(parents=True, exist_ok=True)
    saved = False
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=browser_cfg.channel or None, headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and not page.is_closed():
            host = urlparse(page.url).hostname or ""
            if host.endswith("workatastartup.com") and "login" not in page.url:
                context.storage_state(path=str(session_path))
                saved = True
            try:
                page.wait_for_timeout(2000)
            except Exception:  # window closed by the user
                break
        browser.close()
    return saved
