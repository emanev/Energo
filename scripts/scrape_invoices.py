"""Download your own PDF electricity invoices from the Electrohold portal.

Safety model (see docs/electrohold-invoice-scraper-plan.md and the
portal-invoice-scraper skill):
  * Personal use, own account only. Respect the portal's Terms of Service.
  * NO credentials are ever stored, hardcoded, logged, or typed
    programmatically. You log in by hand in the headed browser; the script
    only continues after you press Enter.
  * The browser session lives in a gitignored profile dir (SESSION_DIR).
  * Downloaded PDFs go to a gitignored folder (OUTPUT_DIR), idempotently.
  * CAPTCHA / 2FA / bot protection / rate limits are never bypassed. The
    human stays in the loop for anything the portal requires at login.

Setup:
    pip install -r requirements.txt
    python -m playwright install chromium

Run:
    python scripts/scrape_invoices.py

The invoices-page selectors below are marked with `# TODO: adjust selector`.
Discover the real ones live against the authenticated page, e.g.:
    python -m playwright codegen https://info.electrohold.bg/webint/vok/index.php
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"


def _load_env_file(path: Path) -> None:
    """Minimal .env loader used when python-dotenv is not installed."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


try:
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH)
except ImportError:
    _load_env_file(ENV_PATH)

from playwright.sync_api import (
    Download,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

# --- Configuration ----------------------------------------------------------
LOGIN_URL = "https://info.electrohold.bg/webint/vok/index.php"
VOK_URL = "https://info.electrohold.bg/webint/vok/vok.php"

SESSION_DIR = Path(".auth/user-data")
OUTPUT_DIR = Path("data/invoices/pdf")
RECEIPTS_PATH = Path("data/invoices/receipts.txt")

TARGET_CLIENT = os.environ.get("ELECTROHOLD_CLIENT", "").strip()
MIN_DATE = date(2024, 1, 1)

BG_MONTHS = {
    1: "януари",
    2: "февруари",
    3: "март",
    4: "април",
    5: "май",
    6: "юни",
    7: "юли",
    8: "август",
    9: "септември",
    10: "октомври",
    11: "ноември",
    12: "декември",
}

REQUIRED_HEADERS = (
    "Клиентски номер",
    "Номер/дата фактура",
    "Сума фактура",
    "Документи",
)

DELAY_BETWEEN_DOWNLOADS = 1.0
NAV_RETRIES = 3

EUR_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*€")


@dataclass
class MatchedInvoice:
    invoice_no: str
    invoice_date: date
    eur_amount: str | None


# --- Login -------------------------------------------------------------------
def wait_for_manual_login(page: Page) -> None:
    """Open the portal and let the user authenticate by hand."""
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    print("\n" + "=" * 70)
    print("A browser window is open at the Electrohold login page.")
    print("Log in MANUALLY in that window (username, password, any 2FA/CAPTCHA).")
    print("This script never sees, stores, or types your credentials.")
    print("When you can see your account/invoices, return here.")
    print("=" * 70)
    input("Press Enter once you are logged in... ")

    if not looks_logged_in(page):
        print(
            "WARNING: could not confirm a logged-in session. "
            "Adjust `looks_logged_in()` for this portal, or try logging in again."
        )


def looks_logged_in(page: Page) -> bool:
    """Heuristic check for an authenticated session."""
    candidates = [
        page.get_by_role("link", name="Изход"),
        page.get_by_role("link", name="Фактури"),
        page.locator("a[href*='logout']"),
        page.locator("a[href*='vok.php']"),
    ]
    for loc in candidates:
        try:
            if loc.first.is_visible(timeout=1500):
                return True
        except Exception:
            continue
    return False


def is_login_page(page: Page) -> bool:
    """Detect that the session dropped and we are back on the login screen."""
    url = page.url.lower()
    if "index.php" in url or "login" in url:
        try:
            if page.locator("input[type='password']").first.is_visible(timeout=1000):
                return True
        except Exception:
            pass
    signals = [
        page.locator("input[type='password']"),
        page.get_by_role("button", name="Вход"),
    ]
    for loc in signals:
        try:
            if loc.first.is_visible(timeout=1000):
                return True
        except Exception:
            continue
    return False


def ensure_logged_in(page: Page) -> None:
    """Re-run the manual login flow if the session has been lost."""
    if looks_logged_in(page) and not is_login_page(page):
        return
    print("\nSession appears to be logged out. Please log in again manually.")
    wait_for_manual_login(page)


def safe_navigate(page: Page, action, description: str):
    """Run a navigation action, re-logging-in and retrying if the session drops."""
    last_exc: Exception | None = None
    for attempt in range(1, NAV_RETRIES + 1):
        try:
            result = action()
            if is_login_page(page):
                raise RuntimeError("navigation landed on the login page")
            return result
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            print(
                f"  navigation '{description}' failed "
                f"(attempt {attempt}/{NAV_RETRIES}): {exc}"
            )
            ensure_logged_in(page)
            time.sleep(attempt)
    raise RuntimeError(
        f"navigation '{description}' failed after {NAV_RETRIES} attempts: "
        f"{last_exc}"
    )


# --- Parsing helpers ---------------------------------------------------------
def parse_invoice_cell(text: str) -> tuple[str, date] | None:
    """Split '0479715762/02.06.2026' into invoice number and date."""
    text = " ".join(text.split())
    if "/" not in text:
        return None
    number, _, rest = text.partition("/")
    date_token = rest.strip().split()[0]
    try:
        return number.strip(), datetime.strptime(date_token, "%d.%m.%Y").date()
    except ValueError:
        return None


def bg_month_year(d: date) -> str:
    """Return Bulgarian month.year label, e.g. date(2025, 7, 31) -> 'юли.2025'."""
    return f"{BG_MONTHS[d.month]}.{d.year}"


def parse_eur_amount(text: str) -> str | None:
    """Extract the EUR amount regardless of order or parentheses."""
    match = EUR_RE.search(text)
    if not match:
        return None
    amount = match.group(1).replace(",", ".")
    return f"{amount} €"


# --- Table discovery ---------------------------------------------------------
def _normalize_header(text: str) -> str:
    return " ".join(text.split())


def _cell_text(cell: Locator) -> str:
    # Use text_content(): DataTables renders header labels inside zero-height
    # `div.dataTables_sizing`, which inner_text() (visibility-aware) returns as "".
    try:
        txt = cell.text_content(timeout=2000) or ""
    except Exception:
        txt = ""
    return _normalize_header(txt)


def find_invoice_table(page: Page) -> Locator | None:
    """Locate the invoices table by required Bulgarian column headers.

    The portal uses jQuery DataTables with a scroll layout: a header-only table
    lives in `.dataTables_scrollHead` (no id) and the real data table is
    `table#einv` in `.dataTables_scrollBody`. Prefer the id, then fall back to a
    header-text scan over every table.
    """
    einv = page.locator("table#einv")
    try:
        if einv.count() and map_column_indices(einv.first) is not None:
            return einv.first
    except Exception:
        pass

    tables = page.locator("table")
    try:
        count = tables.count()
    except Exception:
        return None

    for i in range(count):
        table = tables.nth(i)
        if map_column_indices(table) is not None:
            return table
    return None


def map_column_indices(table: Locator) -> dict[str, int] | None:
    """Map required header labels to zero-based column indices."""
    header_cells = table.locator("thead tr").first.locator("th, td")
    if header_cells.count() == 0:
        header_cells = table.locator("tr").first.locator("th, td")

    headers: dict[str, int] = {}
    try:
        col_count = header_cells.count()
    except Exception:
        return None

    for idx in range(col_count):
        label = _normalize_header(_cell_text(header_cells.nth(idx)))
        if label in REQUIRED_HEADERS:
            headers[label] = idx

    if all(header in headers for header in REQUIRED_HEADERS):
        return headers
    return None


def _row_cells(row: Locator) -> Locator:
    return row.locator("td")


def _table_fingerprint(table: Locator) -> str:
    rows = table.locator("tbody tr")
    try:
        if rows.count() == 0:
            return ""
        return _cell_text(rows.first)
    except Exception:
        return ""


def find_orange_pdf_button(docs_cell: Locator) -> Locator | None:
    """Return the orange PDF link inside this row's Документи cell only.

    The invoice PDF is `<a style="background-color:#ff5722"><i class="fad
    fa-file-pdf">`. The green receipt button is `<a class="... green ..."><i
    class="fal fa-file-invoice">` and must never be returned. Scoping to the
    row's cell also rules out the orange toolbar button above the table.
    """
    btn = docs_cell.locator("a:has(i.fa-file-pdf)")
    try:
        if btn.count():
            return btn.first
    except Exception:
        pass
    return None


def click_next_page(page: Page, before_fingerprint: str) -> bool:
    """Advance to the next DataTables page via `a#einv_next`.

    Returns False when the next control is disabled (last page) or the table
    content does not change. DataTables re-renders in place (no full navigation)
    and shows the `#einv_processing` overlay while loading.
    """
    nxt = page.locator("a#einv_next")
    try:
        if not nxt.count():
            return False
        cls = (nxt.get_attribute("class") or "").lower()
        if "disabled" in cls or nxt.get_attribute("aria-disabled") == "true":
            return False
    except Exception:
        return False

    try:
        nxt.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    # A sticky page header overlaps the pager and intercepts normal pointer
    # clicks, so dispatch the click via JS (DataTables' handler still fires);
    # fall back to a forced click.
    try:
        nxt.evaluate("el => el.click()")
    except Exception:
        try:
            nxt.click(force=True, timeout=5000)
        except Exception as exc:  # noqa: BLE001
            print(f"    pagination click failed: {exc}")
            return False

    try:
        page.locator("#einv_processing").wait_for(state="hidden", timeout=15000)
    except Exception:
        pass

    for _ in range(20):
        table_after = find_invoice_table(page)
        after = _table_fingerprint(table_after) if table_after is not None else ""
        if after and after != before_fingerprint:
            return True
        page.wait_for_timeout(300)
    return False


def scrape_invoices(page: Page) -> tuple[list[MatchedInvoice], int, int, int]:
    """Walk every paginated page, extract matching rows, and download each PDF.

    Downloads happen inline while the row's page is displayed, because
    DataTables replaces the tbody on pagination (so row/button handles from an
    earlier page would go stale). Returns (matches, downloaded, skipped, failed).
    """
    table = find_invoice_table(page)
    if table is None:
        return [], 0, 0, 0

    matches: list[MatchedInvoice] = []
    downloaded = skipped = failed = 0
    seen_fingerprints: set[str] = set()
    page_no = 0

    while True:
        page_no += 1
        col_map = map_column_indices(table)
        if col_map is None:
            break

        fingerprint = _table_fingerprint(table)
        if fingerprint in seen_fingerprints:
            break
        seen_fingerprints.add(fingerprint)

        rows = table.locator("tbody tr")
        try:
            row_count = rows.count()
        except Exception:
            break

        print(f"\n-- page {page_no}: {row_count} row(s) --")
        for i in range(row_count):
            row = rows.nth(i)
            cells = _row_cells(row)
            try:
                if cells.count() <= max(col_map.values()):
                    continue
            except Exception:
                continue

            client = _cell_text(cells.nth(col_map["Клиентски номер"]))
            if client != TARGET_CLIENT:
                continue

            invoice_cell = _cell_text(cells.nth(col_map["Номер/дата фактура"]))
            parsed = parse_invoice_cell(invoice_cell)
            if parsed is None:
                print(f"  warning: could not parse invoice cell: {invoice_cell!r}")
                continue

            invoice_no, invoice_date = parsed
            if invoice_date < MIN_DATE:
                continue

            amount_text = _cell_text(cells.nth(col_map["Сума фактура"]))
            eur_amount = parse_eur_amount(amount_text)
            if eur_amount is None:
                print(
                    f"  warning: no EUR amount for invoice {invoice_no} "
                    f"({amount_text!r}); marking EUR_NOT_FOUND"
                )

            matches.append(
                MatchedInvoice(
                    invoice_no=invoice_no,
                    invoice_date=invoice_date,
                    eur_amount=eur_amount,
                )
            )

            dest = OUTPUT_DIR / f"{invoice_no}.pdf"
            if dest.exists() and validate_pdf(dest):
                print(f"  [{invoice_no}] skip (exists)")
                skipped += 1
                continue

            docs_cell = cells.nth(col_map["Документи"])
            pdf_button = find_orange_pdf_button(docs_cell)
            if pdf_button is None:
                print(f"  [{invoice_no}] no orange PDF button found; skipping")
                failed += 1
                continue

            print(f"  [{invoice_no}] downloading {eur_amount or 'EUR_NOT_FOUND'}")
            if download_pdf(page, pdf_button, dest):
                downloaded += 1
            else:
                print(f"  [{invoice_no}] download failed")
                failed += 1
            time.sleep(DELAY_BETWEEN_DOWNLOADS)

        if not click_next_page(page, fingerprint):
            break
        table = find_invoice_table(page)
        if table is None:
            break

    return matches, downloaded, skipped, failed


def write_receipts(invoices: list[MatchedInvoice], dest: Path) -> None:
    """Overwrite receipts.txt with newest-first EUR lines."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for inv in sorted(invoices, key=lambda item: item.invoice_date, reverse=True):
        month_year = bg_month_year(inv.invoice_date)
        amount = inv.eur_amount if inv.eur_amount else "EUR_NOT_FOUND"
        lines.append(f"{month_year} - {amount}")
    dest.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


# --- Navigation --------------------------------------------------------------
def go_to_invoices(page: Page) -> None:
    """Navigate to the billing/invoices view on vok.php."""
    def _open_vok():
        page.goto(VOK_URL, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")

    safe_navigate(page, _open_vok, "open vok.php main page")

    invoice_link_names = [
        "Електронна фактура",
        "Електронни фактури",
        "Фактури",
        "Фактура",
        "Сметки",
    ]

    def _open_invoices():
        for name in invoice_link_names:
            for role in ("link", "button", "tab"):
                loc = page.get_by_role(role, name=name)  # type: ignore[arg-type]
                try:
                    if loc.first.is_visible(timeout=1000):
                        loc.first.click()
                        page.wait_for_load_state("networkidle")
                        return True
                except Exception:
                    continue
        return False

    try:
        safe_navigate(page, _open_invoices, "open invoices section")
    except Exception:
        print(
            "Could not auto-navigate to the invoices section. Navigate there "
            "manually in the browser, then press Enter."
        )
        input("Press Enter when the invoices list is visible... ")


# --- Downloading -------------------------------------------------------------
def download_pdf(page: Page, click_target: Locator, dest: Path) -> bool:
    """Download the invoice PDF for the orange button.

    The orange link has no href; its `onclick` runs `g(2, {devbg:'<token>'})`
    and opens the PDF in a new tab (`target="_blank"`). Primary strategy: catch
    that new tab and fetch its URL via the authenticated request context (reuses
    session cookies). Fallbacks: a download event, or a popup, on the main page.
    """
    ctx = page.context

    # Dispatch the click via JS: a sticky page header overlaps top rows and
    # intercepts normal pointer clicks. el.click() still runs the anchor's
    # onclick (pw(); g(2, {...})) that produces the PDF.
    def _fire_click() -> None:
        click_target.evaluate("el => el.click()")

    # Strategy A: the click streams the PDF as a download (attachment).
    try:
        with page.expect_download(timeout=15000) as dl_info:
            _fire_click()
        download: Download = dl_info.value
        download.save_as(str(dest))
        if validate_pdf(dest):
            return True
    except PlaywrightTimeoutError:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"    download-event attempt failed: {exc}")

    # Strategy B: fallback - the click opened a new tab pointing at the PDF.
    try:
        with ctx.expect_page(timeout=8000) as page_info:
            _fire_click()
        new_page = page_info.value
        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        pdf_url = new_page.url
        ok = pdf_url.startswith("http") and _fetch_pdf_via_request(page, pdf_url, dest)
        try:
            new_page.close()
        except Exception:
            pass
        if ok:
            return True
    except PlaywrightTimeoutError:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"    new-tab attempt failed: {exc}")

    return False


def _fetch_pdf_via_request(page: Page, url: str, dest: Path) -> bool:
    try:
        resp = page.context.request.get(url, timeout=15000)
        if not resp.ok:
            print(f"    fetch {url} returned HTTP {resp.status}")
            return False
        body = resp.body()
        if not body or body[:4] != b"%PDF":
            return False
        dest.write_bytes(body)
        return validate_pdf(dest)
    except Exception as exc:  # noqa: BLE001
        print(f"    request fetch failed: {exc}")
        return False


def validate_pdf(path: Path) -> bool:
    try:
        if path.stat().st_size == 0:
            return False
        with path.open("rb") as fh:
            return fh.read(4) == b"%PDF"
    except OSError:
        return False


def _structure_unclear_message() -> str:
    return (
        "\nNo matching invoice table was found on the page.\n"
        "The invoice page structure is unclear, so I'm stopping "
        "before guessing.\n\n"
        "Please help me adjust the selectors by sending EITHER:\n"
        "  * a screenshot of the logged-in invoices page, or\n"
        "  * the HTML snippet around the invoices table / download links\n"
        "(open DevTools -> Elements, right-click the invoices "
        "container -> Copy -> Copy outerHTML).\n"
    )


# --- Orchestration -----------------------------------------------------------
def _force_utf8_console() -> None:
    """Avoid UnicodeEncodeError when printing Cyrillic/€ on a cp1252 console."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass


def run() -> int:
    _force_utf8_console()
    if not TARGET_CLIENT:
        print(
            "ERROR: set ELECTROHOLD_CLIENT (e.g. in a local .env). See .env.example."
        )
        return 1
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RECEIPTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR),
            headless=False,
            accept_downloads=True,
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        try:
            wait_for_manual_login(page)
            go_to_invoices(page)

            invoices, downloaded, skipped, failed = scrape_invoices(page)
            if not invoices:
                print(_structure_unclear_message())
                return 2

            write_receipts(invoices, RECEIPTS_PATH)

            print(
                f"\nDone. receipts={len(invoices)} downloaded={downloaded} "
                f"skipped={skipped} failed={failed}\n"
                f"  PDFs -> {OUTPUT_DIR.resolve()}\n"
                f"  receipts -> {RECEIPTS_PATH.resolve()}"
            )
            return 0 if failed == 0 else 1
        finally:
            ctx.close()


if __name__ == "__main__":
    sys.exit(run())
