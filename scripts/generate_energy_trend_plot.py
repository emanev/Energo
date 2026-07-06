"""Generate an interactive HTML chart from invoice receipt data."""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import plotly.graph_objects as go

from scripts.invoice_parsing import BG_MONTHS, MIN_DATE

RECEIPTS_PATH = Path("data/invoices/receipts.txt")
OUTPUT_PATH = Path("reports/energy_price_trend.html")

BG_MONTH_BY_NAME = {name: month for month, name in BG_MONTHS.items()}

RECEIPT_LINE_RE = re.compile(r"^(\S+)\.(\d{4})\s*-\s*([\d.,]+)\s*€\s*$")


def parse_receipt_line(line: str) -> tuple[int, int, float] | None:
    """Parse 'юли.2026 - 18.02 €' into (year, month, amount)."""
    match = RECEIPT_LINE_RE.match(line.strip())
    if not match:
        return None

    month_name, year_text, amount_text = match.groups()
    month = BG_MONTH_BY_NAME.get(month_name)
    if month is None:
        return None

    try:
        year = int(year_text)
        amount = float(amount_text.replace(",", "."))
    except ValueError:
        return None

    return year, month, amount


def load_monthly_totals(path: Path) -> list[tuple[str, float]]:
    """Read receipts.txt and return chronologically sorted (label, total) pairs."""
    if not path.is_file():
        raise FileNotFoundError(f"receipts file not found: {path}")

    totals: dict[tuple[int, int], float] = defaultdict(float)

    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or "EUR_NOT_FOUND" in line:
            continue

        parsed = parse_receipt_line(line)
        if parsed is None:
            print(f"warning: skipping malformed line {line_no}: {raw_line!r}", file=sys.stderr)
            continue

        year, month, amount = parsed
        invoice_date = date(year, month, 1)
        if invoice_date < MIN_DATE:
            continue

        totals[(year, month)] += amount

    if not totals:
        raise ValueError(f"no usable receipt data found in {path}")

    points: list[tuple[str, float]] = []
    for year, month in sorted(totals):
        label = f"{BG_MONTHS[month]}.{year}"
        points.append((label, round(totals[(year, month)], 2)))

    return points


def build_chart(points: list[tuple[str, float]]) -> go.Figure:
    """Build an interactive line chart for monthly invoice totals."""
    labels = [label for label, _ in points]
    amounts = [amount for _, amount in points]

    fig = go.Figure(
        data=[
            go.Scatter(
                x=labels,
                y=amounts,
                mode="lines+markers",
                name="Monthly total",
                hovertemplate="%{x}<br>%{y:.2f} €<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title="Electricity Invoice Trend",
        xaxis_title="Month",
        yaxis_title="Amount (€)",
        xaxis={"type": "category", "tickangle": -45},
        hovermode="x unified",
    )
    return fig


def generate_plot(receipts_path: Path = RECEIPTS_PATH, output_path: Path = OUTPUT_PATH) -> Path:
    """Read receipts, aggregate by month, and write a self-contained HTML chart."""
    points = load_monthly_totals(receipts_path)
    fig = build_chart(points)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(output_path, include_plotlyjs="inline")
    return output_path


def main() -> int:
    try:
        points = load_monthly_totals(RECEIPTS_PATH)
        output_path = generate_plot()
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"Wrote {len(points)} month(s) to {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
