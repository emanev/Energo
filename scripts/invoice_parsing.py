"""Pure parsing and formatting helpers for invoice data."""

from __future__ import annotations

import re
from datetime import date, datetime

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

MIN_DATE = date(2024, 1, 1)

EUR_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*€")


def parse_invoice_number_and_date(invoice_number_date_text: str) -> tuple[str, date]:
    """Split '0479715762/02.06.2026' into invoice number and date."""
    text = " ".join(invoice_number_date_text.split())
    if "/" not in text:
        raise ValueError(f"invalid invoice number/date text: {invoice_number_date_text!r}")
    number, _, rest = text.partition("/")
    date_token = rest.strip().split()[0]
    try:
        parsed_date = datetime.strptime(date_token, "%d.%m.%Y").date()
    except ValueError as exc:
        raise ValueError(
            f"invalid date in invoice number/date text: {invoice_number_date_text!r}"
        ) from exc
    return number.strip(), parsed_date


def get_bulgarian_month_year(d: date) -> str:
    """Return Bulgarian month.year label, e.g. date(2025, 7, 31) -> 'юли.2025'."""
    return f"{BG_MONTHS[d.month]}.{d.year}"


def extract_eur_amount(invoice_amount_text: str) -> str | None:
    """Extract the EUR amount regardless of order or parentheses."""
    match = EUR_RE.search(invoice_amount_text)
    if not match:
        return None
    amount = match.group(1).replace(",", ".")
    return f"{amount} €"


def should_include_invoice(d: date) -> bool:
    """Include only invoices with date >= 01.01.2024."""
    return d >= MIN_DATE


def format_receipt_line(d: date, eur_amount: str) -> str:
    """Format a receipts.txt line, e.g. 'юни.2026 - 12.25 €'."""
    return f"{get_bulgarian_month_year(d)} - {eur_amount}"


def build_pdf_filename(invoice_number: str, d: date) -> str:
    """Build a PDF filename, e.g. 'invoice_0479715762_2026-06-02.pdf'."""
    return f"invoice_{invoice_number}_{d:%Y-%m-%d}.pdf"
