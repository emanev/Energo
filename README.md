# Electrohold Invoice Scraper

A small Python + Playwright CLI that downloads **your own** electricity invoice
PDFs from the Electrohold customer portal
(`https://info.electrohold.bg/webint/vok/`).

You log in **manually** in a real browser window; the script only takes over
afterwards to find and download the PDFs. It never sees, stores, or types your
credentials.

## Safety model

- **Manual login only.** A headed browser opens on the login page. You type your
username, password, and complete any 2FA/CAPTCHA yourself. When you're logged
in, you press Enter in the terminal and the script continues.
- **No credentials anywhere.** Login credentials (username, password) are never
  hardcoded, stored in `.env`, written to config, or logged. Your client number
  is read from the `ELECTROHOLD_CLIENT` environment variable or a local,
  gitignored `.env` file.
- **No security bypass.** The script does not attempt to bypass CAPTCHA, 2FA,
bot protection, or rate limits. The human stays in the loop for login.
- **Local, gitignored session.** The browser profile (cookies/session) is stored
in `.auth/user-data/`, which is gitignored, so you usually log in once and the
session is reused on later runs.
- **Downloads.** PDFs are saved under `data/invoices/pdf/` and are gitignored.
  Aggregated EUR lines are written to `data/invoices/receipts.txt` and are
  committed so the chart source data stays in sync with `reports/`.



## Setup

Requires Python 3.9+.

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

Copy `.env.example` to `.env` and set your Electrohold client number:

```
ELECTROHOLD_CLIENT=your_client_number_here
```

The `.env` file is gitignored and is never committed. You can also export
`ELECTROHOLD_CLIENT` in your shell instead of using a `.env` file.



## Tests

Unit tests cover pure parsing/formatting logic in
[scripts/invoice_parsing.py](scripts/invoice_parsing.py) (invoice number/date
splitting, Bulgarian month labels, EUR extraction, receipt lines, and PDF
filenames). They do not launch a browser or touch the scraper flow.

```bash
python -m pytest tests/test_invoice_parsing.py -v
```

Run the full test suite:

```bash
python -m pytest -v
```



## Usage

```bash
python scripts/scrape_invoices.py
```

What happens:

1. A Chromium window opens at the Electrohold login page
  (`.../webint/vok/index.php`).
2. Log in manually in that window.
3. Return to the terminal and press **Enter**.
4. The script navigates to the main page (`.../webint/vok/vok.php`), walks the
   paginated invoices table, and matches invoices for your configured client
   number (`ELECTROHOLD_CLIENT` in `.env`) dated from `01.01.2024` onward.
5. For each match it writes a EUR-only line to `data/invoices/receipts.txt`
  (format: `месец.година - XX.XX €`) and downloads the row's orange PDF button
   into `data/invoices/pdf/`.
6. Already-downloaded PDFs are skipped, so re-runs are safe and resumable.
7. A summary is printed at the end: `receipts=… downloaded=… skipped=… failed=…`.

If the session expires mid-run and the browser returns to the login page, the
script pauses and asks you to log in again manually and press Enter.

## Visualization

Generate an interactive monthly trend chart from `data/invoices/receipts.txt`:

```bash
python scripts/generate_energy_trend_plot.py
```

Then open the self-contained HTML file in your browser:

`reports/energy_price_trend.html`

The chart aggregates duplicate months by summing EUR amounts and shows the trend
from January 2024 through the latest available month. `data/invoices/receipts.txt`
and `reports/energy_price_trend.html` are committed; PDFs under `data/` stay
gitignored.

## Adjusting selectors

The portal's authenticated pages can only be inspected while logged in, so the
invoice-page selectors in [scripts/scrape_invoices.py](scripts/scrape_invoices.py)
are best-effort guesses marked with `# TODO: adjust selector`.

If the script reports that **no invoices were found**, it stops instead of
guessing. To fix the selectors, send one of:

- a screenshot of the logged-in invoices page, or
- the HTML snippet around the invoices table / download links (DevTools ->
Elements -> right-click the invoices container -> Copy -> Copy outerHTML).

You can also discover selectors interactively with Playwright codegen:

```bash
python -m playwright codegen https://info.electrohold.bg/webint/vok/index.php
```



## Notes

- Only use this for your own account and in line with the portal's Terms of
  Service.
- Be polite: the script downloads sequentially with a short delay between files.
- Cursor agent guidance for this scraper lives in
  [`.cursor/skills/portal-invoice-scraper/`](.cursor/skills/portal-invoice-scraper/).
  That folder is committed; other `.cursor/` working files (e.g. plans) stay
  gitignored.

