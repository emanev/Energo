# Reference: reliable, safe portal scraping

Detailed guidance for `portal-invoice-scraper`. Read this when choosing
selectors, hardening against flakiness, or troubleshooting.

## Legal & ethical checklist

- Only scrape accounts you own, for personal archival of your own invoices.
- Review the portal's Terms of Service and `robots.txt`; if automated access is
  prohibited, stop and tell the user.
- Do not attempt to bypass CAPTCHAs, MFA, bot-detection, or paywalls. If the
  portal blocks automation, keep the human in the loop (manual login) and only
  automate the download step after the user is authenticated.
- Keep request volume low. This is not a crawler; you fetch a handful of the
  user's own PDFs.

## Selector strategy (most → least reliable)

Prefer locators that reflect user-visible semantics; they survive redesigns and
CSS-in-JS hash churn better than structural paths.

1. **Role + accessible name** — best for buttons/links:
   ```python
   page.get_by_role("link", name="Изтегли")        # "Download"
   page.get_by_role("button", name="Фактури")       # "Invoices"
   ```
2. **Label / placeholder / text**:
   ```python
   page.get_by_text("Фактура", exact=False)
   page.get_by_label("Клиентски номер")             # "Customer number"
   ```
3. **Stable `id`** (only if it looks human-authored, not random):
   ```python
   page.locator("#invoicesTable")
   ```
4. **Semantic `data-*` attributes**:
   ```python
   page.locator("[data-invoice-id]")
   page.locator("a[data-action='download-pdf']")
   ```
5. **Stable class / HTML structure** — scope narrowly and anchor to text:
   ```python
   page.locator("table.invoices tbody tr")
   ```
6. **Attribute patterns on links** (useful for PDF endpoints):
   ```python
   page.locator("a[href*='pdf'], a[href*='invoice'], a[href$='.pdf']")
   ```

### Selectors to avoid

- Auto-generated/hashed classes: `.css-1a2b3c`, `.jsx-xxxxxxx`, `.MuiBox-root-42`.
- Long positional chains: `div > div:nth-child(3) > span:nth-child(2)`.
- Absolute XPath from `/html/body/...`.
- Selectors that depend on transient state (spinners, toasts).

### Discovering selectors reliably

- `python -m playwright codegen <url>` records actions and emits robust locators.
- In the headed session, use DevTools "Copy" sparingly — rewrite copied CSS into
  role/text/id-based locators.
- Confirm a locator resolves to exactly one element: `expect(loc).to_have_count(n)`.

## Robustness / anti-flakiness

- **Auto-waiting**: Playwright locators auto-wait for actionability. Prefer
  `locator.click()` over manual `sleep`. Use `expect(...).to_be_visible()` for
  explicit sync points.
- **Idempotent downloads**: derive a deterministic filename and skip if it
  exists. This makes runs resumable after failures.
- **Retries**: wrap a single invoice download in a small retry (2–3 attempts
  with backoff). Do not retry the whole run blindly.
- **Pagination**: if invoices span pages, loop "next page" until the control is
  disabled/absent; collect row handles per page before downloading.
- **Waiting for navigation/AJAX**: use `page.wait_for_load_state("networkidle")`
  sparingly, or better, wait for a concrete post-action element.
- **Politeness**: `page.wait_for_timeout(500–1500)` between downloads.

## Download handling patterns

Portals expose PDFs in different ways. Handle the common cases:

- **Direct link/stream** (click triggers download):
  ```python
  with page.expect_download() as dl:
      row.get_by_role("link", name="PDF").click()
  dl.value.save_as(dest_path)
  ```
- **Opens PDF in a new tab**: capture the popup, then read its URL and download
  via the browser context's `request` (reuses auth cookies):
  ```python
  with page.expect_popup() as pop:
      row.click()
  pdf_url = pop.value.url
  resp = page.context.request.get(pdf_url)
  Path(dest_path).write_bytes(resp.body())
  ```
- **Authenticated direct URL**: if you can build the PDF URL, fetch it with
  `page.context.request.get(url)` so session cookies are sent automatically.

Always validate: file is non-empty and `content[:4] == b"%PDF"`.

## Session persistence (no credentials)

- `launch_persistent_context(user_data_dir=...)` keeps cookies/localStorage in a
  local profile dir → user usually logs in once, not every run.
- Alternative: `context.storage_state(path=".auth/state.json")` after manual
  login, then `new_context(storage_state=...)` next time. Treat `state.json` as
  a secret: gitignored, never logged.
- If the session expires, detect the login page and re-pause for manual login.

### Retry-login on navigation

Any navigation can silently redirect to the login page when a session lapses.
Guard navigations so they self-heal without ever auto-typing credentials:

```python
def safe_navigate(page, action, description, retries=3):
    for attempt in range(1, retries + 1):
        try:
            result = action()
            if is_login_page(page):
                raise RuntimeError("landed on login page")
            return result
        except Exception:
            ensure_logged_in(page)   # re-pause for MANUAL login
            page.wait_for_timeout(attempt * 1000)
    raise RuntimeError(f"{description} failed after {retries} attempts")
```

- `is_login_page(page)`: check a login-only signal (password field, sign-in
  button, or a `login` URL fragment). Keep it distinct from `looks_logged_in`.
- `ensure_logged_in(page)`: if not logged in, re-run the manual login pause.
- After re-login, **re-acquire stale handles** (e.g. re-open the invoices list
  and re-`find_invoice_rows`) — old `Locator`/row references may be detached.
- Apply the same wrapper to popup/new-tab downloads: re-login, then retry the
  click that opens the PDF tab.

## Logging without leaking secrets

- Log URLs, counts, filenames, and timings — never cookies, tokens, headers, or
  form values. Do not screenshot the login form with credentials filled in.
- If you must screenshot for debugging, do it only on the invoices page.

## Troubleshooting

- **"Element not found"**: the DOM changed or content is in an `iframe`. Use
  `page.frame_locator("iframe#...")`. Re-discover with codegen.
- **Download never fires**: the link may open a viewer; use the popup/URL
  pattern above.
- **Logged out mid-run**: session expired → re-run and log in again; consider
  storage-state refresh.
- **Charset/encoding in filenames**: sanitize invoice labels; keep ASCII-safe
  names, store the original in a sidecar `.json` if needed.
