"""M-Pesa statement analyzer.

Reads an M-Pesa statement exported as CSV, categorizes each transaction,
and produces a text summary, a categorized CSV and three charts.

Usage:
    python analyzer.py statement.csv
    python analyzer.py statement.csv --out results --top 10
"""
import argparse
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed; we only save images
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
import pandas as pd

# Order matters: the first matching rule wins. Fees come first because a
# line like "Customer Transfer of Funds Charge" also contains "Customer Transfer".
CATEGORY_RULES = [
    ("Fees & Charges", r"charge|\bfee\b"),
    ("Fuliza", r"fuliza|overdraft"),
    ("Airtime & Data", r"airtime|bundle|\bdata\b"),
    ("Cash Withdrawal", r"withdraw"),
    ("Cash Deposit", r"deposit"),
    ("Rent & Bills", r"pay ?bill"),
    ("Shopping & Merchants", r"merchant payment|buy goods|\btill\b"),
    ("Sent to People", r"customer transfer|send money|sent to"),
    ("Received", r"funds received|received from|salary"),
]

COLUMN_HINTS = {
    "time": ["completion time", "time", "date"],
    "details": ["details", "description", "narrative"],
    "status": ["transaction status", "status"],
    "paid_in": ["paid in", "credit", "money in"],
    "withdrawn": ["withdrawn", "debit", "paid out", "money out"],
    "balance": ["balance"],
}


def _find_column(columns, hints):
    lowered = {c.lower().strip(): c for c in columns}
    for hint in hints:
        for low, original in lowered.items():
            if hint in low:
                return original
    return None


def _to_number(series):
    """Turn strings like '1,234.50' or '-500' into floats; blanks become 0."""
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.strip()
    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0)


def categorize(details: str) -> str:
    text = str(details).lower()
    for name, pattern in CATEGORY_RULES:
        if re.search(pattern, text):
            return name
    return "Other"


def counterparty(details: str) -> str:
    """Best-effort name of who/what the money went to or came from."""
    text = str(details).strip()
    match = re.search(r"\s-\s*(.+)$", text)
    name = match.group(1) if match else text
    return re.sub(r"\s+", " ", name).strip().title()


def load_statement(path) -> pd.DataFrame:
    """Load a statement CSV into a clean DataFrame."""
    raw = pd.read_csv(path)
    cols = {key: _find_column(raw.columns, hints) for key, hints in COLUMN_HINTS.items()}
    missing = [k for k in ("time", "details", "paid_in", "withdrawn") if cols[k] is None]
    if missing:
        raise ValueError(
            f"Could not find column(s) for: {', '.join(missing)}. "
            f"Columns in file: {list(raw.columns)}"
        )

    df = pd.DataFrame({
        "time": pd.to_datetime(raw[cols["time"]], errors="coerce"),
        "details": raw[cols["details"]].astype(str),
        "paid_in": _to_number(raw[cols["paid_in"]]).abs(),
        "withdrawn": _to_number(raw[cols["withdrawn"]]).abs(),  # statements show these as negatives
    })
    if cols["balance"]:
        df["balance"] = _to_number(raw[cols["balance"]])
    if cols["status"]:
        df = df[raw[cols["status"]].astype(str).str.lower().str.contains("complet")]

    df = df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    df["month"] = df["time"].dt.to_period("M").astype(str)
    df["category"] = df["details"].map(categorize)
    df["counterparty"] = df["details"].map(counterparty)
    return df


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    monthly = df.groupby("month")[["paid_in", "withdrawn"]].sum()
    monthly["net"] = monthly["paid_in"] - monthly["withdrawn"]
    monthly["saved_pct"] = np.where(
        monthly["paid_in"] > 0, 100 * monthly["net"] / monthly["paid_in"], np.nan
    )
    return monthly.round(2)


def spending_by_category(df: pd.DataFrame) -> pd.Series:
    spend = df[df["withdrawn"] > 0].groupby("category")["withdrawn"].sum()
    return spend.sort_values(ascending=False)


def top_counterparties(df: pd.DataFrame, n: int = 10) -> pd.Series:
    spend = df[df["withdrawn"] > 0].groupby("counterparty")["withdrawn"].sum()
    return spend.sort_values(ascending=False).head(n)


def flag_unusual(df: pd.DataFrame, threshold: float = 3.5, min_history: int = 4) -> pd.DataFrame:
    """Flag outgoing transactions that are unusually large.

    Two tiers, both using a robust z-score (median and MAD) so a few big
    payments can't hide themselves by inflating the average:

    1. Regular payees (at least `min_history` payments): compared with that
       payee's own history. Rent that is always 18,000 is never flagged, but
       a sudden 40,000 payment to the same payee would be.
    2. Rare payees: compared with all your payments, so one-off big
       purchases stand out.

    In tier 1 a flagged payment must also be at least 1.5x that payee's median,
    which stops tiny deviations from being flagged when amounts are very
    consistent.
    """
    spend = df[df["withdrawn"] > 0].copy()
    if spend.empty:
        return spend
    flags = pd.Series(False, index=spend.index)
    counts = spend.groupby("counterparty")["withdrawn"].transform("size")

    # Tier 1: regular payees vs their own history
    for _, group in spend[counts >= min_history].groupby("counterparty"):
        median = group["withdrawn"].median()
        mad = (group["withdrawn"] - median).abs().median()
        big = group["withdrawn"] > 1.5 * median
        if mad == 0:
            flags[group.index] = big
        else:
            score = 0.6745 * (group["withdrawn"] - median) / mad
            flags[group.index] = (score > threshold) & big

    # Tier 2: rare payees vs the whole spending distribution, using Tukey's
    # "far out" fence (Q3 + 3 x IQR). A log-scale z-score doesn't work well
    # here because everyday spending spans airtime to rent, which makes the
    # spread so wide that nothing ever looks extreme.
    q1, q3 = spend["withdrawn"].quantile([0.25, 0.75])
    fence = q3 + 3 * (q3 - q1)
    rare = spend[counts < min_history]
    flags[rare.index] = rare["withdrawn"] > fence

    return spend[flags].sort_values("withdrawn", ascending=False)


# ----------------------------------------------------------------- charts

def _style(ax, title):
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)


def chart_monthly(monthly: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x = np.arange(len(monthly))
    width = 0.38
    ax.bar(x - width / 2, monthly["paid_in"], width, label="Money in", color="#2a9d8f")
    ax.bar(x + width / 2, monthly["withdrawn"], width, label="Money out", color="#e76f51")
    ax.set_xticks(x)
    ax.set_xticklabels(monthly.index, rotation=0)
    ax.set_ylabel("KES")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.legend(frameon=False)
    _style(ax, "Money in vs money out, by month")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def chart_categories(spend: pd.Series, path: Path):
    spend = spend.sort_values()
    fig, ax = plt.subplots(figsize=(9, 4.5))
    bars = ax.barh(spend.index, spend.values, color="#264653")
    ax.bar_label(bars, labels=[f"{v:,.0f}" for v in spend.values], padding=4, fontsize=9)
    ax.set_xlabel("KES")
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlim(0, spend.max() * 1.15)
    _style(ax, "Where the money went, by category")
    ax.grid(axis="x", alpha=0.25)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def chart_top_counterparties(top: pd.Series, path: Path):
    top = top.sort_values()
    fig, ax = plt.subplots(figsize=(9, 4.5))
    bars = ax.barh(top.index, top.values, color="#e9c46a")
    ax.bar_label(bars, labels=[f"{v:,.0f}" for v in top.values], padding=4, fontsize=9)
    ax.set_xlabel("KES")
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlim(0, top.max() * 1.15)
    _style(ax, "Top places and people you paid")
    ax.grid(axis="x", alpha=0.25)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ----------------------------------------------------------------- report

def build_report(df, monthly, spend, top, unusual) -> str:
    total_in, total_out = df["paid_in"].sum(), df["withdrawn"].sum()
    fees = df.loc[df["category"] == "Fees & Charges", "withdrawn"].sum()
    fuliza = df.loc[df["category"] == "Fuliza", "withdrawn"].sum()
    lines = [
        "M-PESA STATEMENT SUMMARY",
        "=" * 60,
        f"Period:            {df['time'].min():%d %b %Y} to {df['time'].max():%d %b %Y}",
        f"Transactions:      {len(df):,}",
        f"Total money in:    KES {total_in:,.2f}",
        f"Total money out:   KES {total_out:,.2f}",
        f"Net:               KES {total_in - total_out:,.2f}",
        f"Fees & charges:    KES {fees:,.2f}",
        f"Fuliza repayments: KES {fuliza:,.2f}",
        "",
        "MONTHLY",
        "-" * 60,
        monthly.to_string(float_format=lambda v: f"{v:,.2f}"),
        "",
        "SPENDING BY CATEGORY",
        "-" * 60,
    ]
    for name, value in spend.items():
        share = 100 * value / total_out if total_out else 0
        lines.append(f"{name:<24} KES {value:>12,.2f}  ({share:4.1f}%)")
    lines += ["", f"TOP {len(top)} PAYEES", "-" * 60]
    for name, value in top.items():
        lines.append(f"{name:<40} KES {value:>12,.2f}")
    lines += ["", "UNUSUALLY LARGE TRANSACTIONS", "-" * 60]
    if unusual.empty:
        lines.append("None flagged.")
    else:
        for _, row in unusual.iterrows():
            lines.append(f"{row['time']:%d %b %Y}  KES {row['withdrawn']:>10,.2f}  {row['category']}: {row['counterparty']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Analyze an M-Pesa statement CSV.")
    parser.add_argument("statement", help="Path to the statement CSV")
    parser.add_argument("--out", default="output", help="Folder for results (default: output)")
    parser.add_argument("--top", type=int, default=8, help="How many top payees to show")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    df = load_statement(args.statement)
    if df.empty:
        raise SystemExit("No completed transactions found in the file.")

    monthly = monthly_summary(df)
    spend = spending_by_category(df)
    top = top_counterparties(df, args.top)
    unusual = flag_unusual(df)

    report = build_report(df, monthly, spend, top, unusual)
    print(report)
    (out / "summary.txt").write_text(report, encoding="utf-8")
    df.to_csv(out / "categorized_transactions.csv", index=False)
    chart_monthly(monthly, out / "monthly_in_vs_out.png")
    if not spend.empty:
        chart_categories(spend, out / "spending_by_category.png")
    if not top.empty:
        chart_top_counterparties(top, out / "top_payees.png")
    print(f"\nSaved summary, categorized CSV and charts to: {out.resolve()}")


if __name__ == "__main__":
    main()
