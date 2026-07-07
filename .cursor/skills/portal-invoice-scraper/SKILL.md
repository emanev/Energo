---
name: portal-invoice-scraper
description: Build safe, reliable Python + Playwright scrapers that download your own PDF invoices from authenticated customer portals (e.g. an electricity provider account). Use when the user wants to log into a personal account portal and download or archive invoices/bills/statements, or asks to build a scraper/downloader for an authenticated web portal. Emphasizes a manual login flow with no stored credentials, gitignored session state, reliable selectors, and polite/robust automation.
disable-model-invocation: true
---

# Portal Invoice Scraper

Build a scraper that logs into a customer portal and downloads the user's **own**
PDF invoices. Default reference target: the Electrohold (Bulgaria) portal at
`https://info.electrohold.bg/webint/vok/index.php`, but the approach is reusable.

## Non-negotiable safety rules

1. **Personal use, own account only.** Only automate accounts the user owns.
   Respect the site's Terms of Service and `robots.txt`. Do not build tools to
   access other people's data or to bypass access controls.
2. **Never store credentials.** Do not put username/password in source code,
   `appsettings.json`, `.env`, config files, logs, screenshots, or commit
   history. Do not add a "convenience" auto-login. The user types credentials
   manually in the browser.
3. **Manual login flow.** Launch a **headed** browser, navigate to the portal,
   then **pause** so the user logs in by hand. Only continue after the user
   confirms they are logged in.
4. **Session state is local + gitignored.** If you persist a browser session to
   avoid re-logging-in, store it only under a gitignored folder such as
   `.auth/` or `user-data/`. Never commit it. Downloaded PDFs also go in a
   gitignored folder (e.g. `invoices/`).
5. **Be polite.** Add small delays between actions, avoid hammering the server,
   download sequentially, and skip files already downloaded (idempotent).

## Workflow

Copy this checklist and track progress:

```
- [ ] Step 1: Scaffold project (deps, .gitignore, folders)
- [ ] Step 2: Launch headed browser + manual login pause
- [ ] Step 3: Confirm logged-in state, persist session locally
- [ ] Step 4: Navigate to the invoices/billing page
- [ ] Step 5: Discover reliable selectors for invoice rows + download links
- [ ] Step 6: Enumerate invoices and download PDFs idempotently
- [ ] Step 7: Verify downloads, log a summary (no secrets)
```

### Step 1: Scaffold

- Create a Python project. Install deps and browsers:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

- `requirements.txt` (see `scripts/`): `playwright`.
- Create/append `.gitignore` with at least:

```gitignore
.auth/
user-data/
invoices/
downloads/
*.pdf
```

### Step 2 & 3: Manual login with persistent session

Use a **persistent context** so the session survives runs, stored in a
gitignored `user-data/` dir. Launch headed, go to the portal, then wait for the
user. Do NOT type credentials programmatically.

The provided `scripts/scrape_invoices.py` implements this. Key idea:

```python
ctx = pw.chromium.launch_persistent_context(
    user_data_dir=".auth/user-data",  # gitignored
    headless=False,
    accept_downloads=True,
)
page = ctx.pages[0] if ctx.pages else ctx.new_page()
page.goto(PORTAL_URL)
input("Log in manually in the browser, then press Enter here to continue...")
```

Confirm login by checking for a post-login element (a logout link, account
menu, or the invoices nav item) rather than assuming success.

**Retry-login on navigation.** Sessions can expire mid-run. Wrap every
navigation action (following a link, opening a page/tab, switching to the
invoices view) in a guard that: (a) detects the login page, (b) re-triggers the
**manual** login flow, and (c) retries the same navigation. Never re-login by
auto-typing credentials. The provided script implements this via
`safe_navigate(page, action, description)` plus `is_login_page()` /
`ensure_logged_in()`, and also re-logs-in + refreshes row handles when a
download fails due to a dropped session.

### Step 4 & 5: Navigate and discover selectors

Because portal DOMs differ and require auth, **discover selectors live** instead
of guessing. Fastest options:

- Run Playwright codegen against the target to record navigation and copy the
  suggested locators: `python -m playwright codegen https://info.electrohold.bg/webint/vok/index.php`
- Or, in the running headed session, open DevTools and inspect the invoice
  table/rows and the PDF download control.

Choose **reliable selectors** in this priority order (see `reference.md`):
role/label/text → stable `id` → semantic `data-*` → stable class/structure.
Avoid auto-generated hashed classes and fragile deep `:nth-child` chains.

### Step 6: Download PDFs idempotently

- Prefer Playwright's download event (`page.expect_download()`), which handles
  the file even when the link triggers a server-side stream.
- Name files deterministically (e.g. `invoice_<number>_<date>.pdf`), and skip
  any that already exist so re-runs are safe and resumable.

### Step 7: Verify + summarize

- Assert each downloaded file is non-empty and starts with the `%PDF` header.
- Print a summary: how many found, downloaded, skipped, failed. Never log
  credentials or full session cookies.

## Files in this skill

- `scripts/scrape_invoices.py` — runnable starter with the manual-login flow,
  persistent gitignored session, download handling, and clearly marked
  `# TODO: adjust selector` spots for the invoices page.
- `scripts/requirements.txt` — pinned-free minimal deps.
- `reference.md` — selector strategy, robustness/anti-flakiness patterns,
  legal/ethical notes, and troubleshooting.

Read `reference.md` before writing custom selectors or debugging flaky runs.
