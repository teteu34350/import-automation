"""Temporary: list all hotels visible after AmerisConnect login."""
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from credentials import read_password
from settings import AMERISCONNECT, AppSettings

WORKSPACE = Path(__file__).resolve().parent
PORTAL = "https://amerisconnect.autosky.cloud/"
PROFILE_DIR = WORKSPACE / "_inspect_profile"
_TMP_DIR = WORKSPACE / "_tmp"
_TMP_DIR.mkdir(parents=True, exist_ok=True)
for _var in ("TMP", "TEMP", "TMPDIR"):
    os.environ[_var] = str(_TMP_DIR)


def main():
    settings = AppSettings.load()
    hotel = next((h for h in settings.hotels if h.system == AMERISCONNECT and h.active), None)
    password = read_password(hotel.credential_target)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            args=["--no-first-run", "--no-default-browser-check"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(PORTAL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(2)
        page.locator('input[name="email"]').fill(hotel.username)
        page.locator('input[name="password"]').fill(password)
        page.get_by_role("button", name="Entrar", exact=True).click()
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            pass
        time.sleep(3)
        print("URL:", page.url, flush=True)
        # List every <p> (hotel names are MuiTypography body1 <p>)
        print("=== <p> elements ===", flush=True)
        ps = page.locator("p")
        for i in range(ps.count()):
            try:
                t = ps.nth(i).inner_text().strip()
                if t:
                    print(f"[{i}] {t!r}", flush=True)
            except Exception:
                pass
        # Also list clickable cards (role button/link with text)
        print("=== clickable with text ===", flush=True)
        for role in ("button", "link"):
            loc = page.get_by_role(role)
            for i in range(loc.count()):
                try:
                    t = loc.nth(i).inner_text().strip()
                    if t:
                        print(f"{role}[{i}] {t!r}", flush=True)
                except Exception:
                    pass
        print("DONE", flush=True)
        time.sleep(2)
        context.close()


if __name__ == "__main__":
    main()
