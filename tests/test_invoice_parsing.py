"""Unit tests for invoice parsing helpers."""

from __future__ import annotations

from datetime import date

import pytest

from scripts.invoice_parsing import (
    build_pdf_filename,
    extract_eur_amount,
    format_receipt_line,
    get_bulgarian_month_year,
    parse_invoice_number_and_date,
    should_include_invoice,
)


def test_parse_invoice_number_and_date_example() -> None:
    invoice_number, parsed_date = parse_invoice_number_and_date("0479715762/02.06.2026")
    assert invoice_number == "0479715762"
    assert parsed_date == date(2026, 6, 2)


def test_parse_invoice_number_and_date_invalid() -> None:
    with pytest.raises(ValueError):
        parse_invoice_number_and_date("0479715762")


@pytest.mark.parametrize(
    ("parsed_date", "expected"),
    [
        (date(2026, 6, 2), "юни.2026"),
        (date(2025, 7, 31), "юли.2025"),
        (date(2024, 1, 14), "януари.2024"),
    ],
)
def test_get_bulgarian_month_year(parsed_date: date, expected: str) -> None:
    assert get_bulgarian_month_year(parsed_date) == expected


@pytest.mark.parametrize(
    ("amount_text", "expected"),
    [
        ("59.38 лв. (30.36 €)", "30.36 €"),
        ("18.02 € (35.24 лв.)", "18.02 €"),
        ("12.25 € (23.96 лв.)", "12.25 €"),
        ("65.34 лв. (33.41 €)", "33.41 €"),
    ],
)
def test_extract_eur_amount(amount_text: str, expected: str) -> None:
    assert extract_eur_amount(amount_text) == expected


def test_should_include_invoice_boundary() -> None:
    assert should_include_invoice(date(2024, 1, 1)) is True
    assert should_include_invoice(date(2023, 12, 31)) is False


def test_format_receipt_line() -> None:
    assert format_receipt_line(date(2026, 6, 2), "12.25 €") == "юни.2026 - 12.25 €"


def test_build_pdf_filename() -> None:
    assert (
        build_pdf_filename("0479715762", date(2026, 6, 2))
        == "invoice_0479715762_2026-06-02.pdf"
    )
