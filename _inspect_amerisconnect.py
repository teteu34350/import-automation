"""Temporary inspection #2: click "Abrir no navegador" and observe system open."""
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
OUT = WORKSPACE / "_inspect_output.txt"
PROFILE_DIR = WORKSPACE / "_inspect_profile"
_TMP_DIR = WORKSPACE / "_tmp"
_TMP_DIR.mkdir(parents=True, exist_ok=True)
for _var in ("TMP", "TEMP", "TMPDIR"):
    os.environ[_var] = str(_TMP_DIR)

_lines = []


def log(*args):
    line = " ".join(str(a) for a in args)
    line = line.replace("\u200b", "").replace("\u00ad", "")
    _lines.append(line)
    print(line, flush=True)


def flush():
    OUT.write_text("\n".join(_lines) + "\n", encoding="utf-8")


def dump_text(page, label, limit=6000):
    log(f"\n===== BODY TEXT [{label}] =====")
    try:
        text = page.locator("body").inner_text()
        log(text[:limit])
        if len(text) > limit:
            log(f"... (truncated, total {len(text)} chars)")
    except Exception as e:
        log(f"ERROR {e}")


def dump_ancestors(page, needle):
    log(f"\n===== ANCESTORS OF '{needle}' =====")
    try:
        el = page.get_by_text(needle, exact=False).first
        if el.count() == 0:
            log("not found")
            return
        for depth in range(5):
            info = el.evaluate(
                """(el) => {
                    let n = el;
                    let out = [];
                    for (let i = 0; i < 5 && n; i++) {
                        out.push(n.tagName + '.' + (n.className||'').toString().split(' ').slice(0,3).join('.'));
                        n = n.parentElement;
                    }
                    return out;
                }"""
            )
            log("ancestors:", info)
    except Exception as e:
        log(f"ERROR {e}")


def main():
    settings = AppSettings.load()
    hotel = next((h for h in settings.hotels if h.system == AMERISCONNECT and h.active), None)
    password = read_password(hotel.credential_target)
    log(f"hotel={hotel.name}")

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            args=["--no-first-run", "--no-default-browser-check"],
        )
        new_pages = []
        context.on("page", lambda pg: new_pages.append(pg))
        page = context.pages[0] if context.pages else context.new_page()

        log("========== LOGIN ==========")
        page.goto(PORTAL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=30000)
        time.sleep(2)
        page.locator('input[name="email"]').wait_for(state="visible", timeout=20000)
        page.locator('input[name="email"]').fill(hotel.username)
        page.locator('input[name="password"]').fill(password)
        page.get_by_role("button", name="Entrar", exact=True).click()
        try:
            page.wait_for_load_state("networkidle", timeout=30000)
        except PlaywrightTimeoutError:
            pass
        time.sleep(3)
        log("URL after login:", page.url)
        dump_text(page, "hotel-list", limit=6000)
        dump_ancestors(page, "Iracema Travel")
        flush()

        log("\n========== CLICK IRACEMA ==========")
        try:
            iracema = page.get_by_text("Iracema Travel", exact=True)
            log("exact Iracema count:", iracema.count())
            if iracema.count() >= 1:
                iracema.first.click()
            time.sleep(4)
            log("URL after Iracema:", page.url)
            dump_text(page, "access-method", limit=6000)
            flush()
        except Exception as e:
            log("ERROR:", repr(e))
            flush()

        log("\n========== CLICK ABRIR NO NAVEGADOR ==========")
        try:
            btn = page.get_by_role("button", name="Abrir no navegador", exact=True)
            log("button count:", btn.count())
            if btn.count() >= 1:
                btn.first.click()
                log("clicked")
            # wait for new page or navigation
            for _ in range(20):
                time.sleep(1)
                total = context.pages + new_pages
                if any(pg.url != page.url for pg in total if pg.url):
                    break
            time.sleep(6)
            log("=== ALL PAGES ===")
            seen = set()
            for pg in context.pages + new_pages:
                try:
                    key = id(pg)
                    if key in seen:
                        continue
                    seen.add(key)
                    log(f"url={pg.url!r} title={pg.title()!r}")
                except Exception:
                    pass
            # dump the newest non-portal page
            for pg in reversed(context.pages + new_pages):
                try:
                    if pg.url and "amerisconnect.autosky.cloud" not in pg.url:
                        log(f"\n===== DUMP SYSTEM PAGE {pg.url} =====")
                        dump_text(pg, "system", limit=8000)
                        break
                except Exception:
                    pass
            flush()
        except Exception as e:
            log("ERROR:", repr(e))
            flush()

        log("\nDONE. Keeping open 5s.")
        flush()
        time.sleep(5)
        context.close()

    flush()
    log("finished")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("FATAL:", repr(e))
        flush()
        sys.exit(1)
