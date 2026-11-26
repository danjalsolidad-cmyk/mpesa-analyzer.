"""Generate a fake M-Pesa statement CSV for testing the analyzer.

All names, till numbers and amounts are fictional.

Usage:
    python generate_sample.py                 # writes sample_statement.csv
    python generate_sample.py --months 12 --seed 7 --out my_sample.csv
"""
import argparse
import random
import string
from datetime import datetime, timedelta

import pandas as pd

PEOPLE = ["Amina W", "Brian O", "Cynthia K", "David M", "Esther N", "Felix T"]
SHOPS = [
    ("Merchant Payment to 523001 - Green Basket Supermarket", 300, 3500),
    ("Merchant Payment to 523002 - Mama Mboga Fresh", 80, 600),
    ("Merchant Payment to 523003 - Corner Cafe", 150, 900),
    ("Merchant Payment to 523004 - Jiji Fuel Station", 1000, 4000),
]
BILLS = [
    ("Pay Bill to 888880 - Power Prepaid", 500, 2500),
    ("Pay Bill to 888881 - City Water Services", 300, 1200),
    ("Pay Bill to 888882 - FiberHome Internet", 2999, 2999),
]


def receipt():
    return "S" + "".join(random.choices(string.ascii_uppercase + string.digits, k=9))


def build_rows(start, months):
    rows = []  # (time, details, paid_in, withdrawn)
    for m in range(months):
        month_start = (start + timedelta(days=31 * m)).replace(day=1)
        # Salary on the 28th of each month, 1st of the following one for the sim.
        rows.append((month_start.replace(day=28, hour=9), "Funds received from - Acme Payroll", random.randint(55000, 65000), 0))
        # Occasional money from friends/family.
        for _ in range(random.randint(1, 3)):
            day = random.randint(1, 27)
            rows.append((month_start.replace(day=day, hour=random.randint(8, 20)),
                         f"Funds received from - {random.choice(PEOPLE)}", random.randint(500, 5000), 0))
        # Rent
        rows.append((month_start.replace(day=3, hour=8), "Pay Bill to 777000 - Sunrise Apartments Rent", 0, 18000))
        # Bills
        for details, lo, hi in BILLS:
            rows.append((month_start.replace(day=random.randint(4, 12), hour=random.randint(7, 21)),
                         details, 0, random.randint(lo, hi)))
        # Shopping
        for _ in range(random.randint(12, 22)):
            details, lo, hi = random.choice(SHOPS)
            rows.append((month_start.replace(day=random.randint(1, 28), hour=random.randint(7, 21),
                                             minute=random.randint(0, 59)), details, 0, random.randint(lo, hi)))
        # Sending money to people
        for _ in range(random.randint(3, 7)):
            rows.append((month_start.replace(day=random.randint(1, 28), hour=random.randint(7, 21)),
                         f"Customer Transfer to - 2547XXXX{random.randint(100, 999)} {random.choice(PEOPLE)}",
                         0, random.randint(200, 6000)))
        # Airtime
        for _ in range(random.randint(3, 6)):
            rows.append((month_start.replace(day=random.randint(1, 28), hour=random.randint(7, 21)),
                         "Airtime Purchase", 0, random.choice([20, 50, 100, 200])))
        # Cash withdrawals
        for _ in range(random.randint(1, 3)):
            rows.append((month_start.replace(day=random.randint(1, 28), hour=random.randint(7, 21)),
                         "Withdrawal at Agent 456789 - Jua Kali Agency", 0, random.choice([1000, 2000, 3000, 5000])))
        # One unusually large purchase now and then (good for anomaly detection demo)
        if random.random() < 0.4:
            rows.append((month_start.replace(day=random.randint(5, 25), hour=14),
                         "Merchant Payment to 523099 - Tech Mart Electronics", 0, random.randint(25000, 45000)))
    rows.sort(key=lambda r: r[0])
    return rows


def to_statement(rows, opening_balance=20000):
    out, balance = [], opening_balance
    for time, details, paid_in, withdrawn in rows:
        balance += paid_in - withdrawn
        out.append({
            "Receipt No.": receipt(),
            "Completion Time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "Details": details,
            "Transaction Status": "Completed",
            "Paid In": paid_in if paid_in else "",
            "Withdrawn": -withdrawn if withdrawn else "",
            "Balance": balance,
        })
        # Transaction fee for outgoing person-to-person transfers, like the real statement.
        if details.startswith("Customer Transfer") and withdrawn:
            fee = 7 if withdrawn <= 100 else 13 if withdrawn <= 500 else 23 if withdrawn <= 1000 else 33 if withdrawn <= 1500 else 53
            balance -= fee
            out.append({
                "Receipt No.": receipt(),
                "Completion Time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "Details": "Customer Transfer of Funds Charge",
                "Transaction Status": "Completed",
                "Paid In": "",
                "Withdrawn": -fee,
                "Balance": balance,
            })
    return pd.DataFrame(out)


def main():
    parser = argparse.ArgumentParser(description="Generate a fake M-Pesa statement CSV.")
    parser.add_argument("--months", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default="sample_statement.csv")
    args = parser.parse_args()

    random.seed(args.seed)
    start = datetime(2026, 1, 1)
    df = to_statement(build_rows(start, args.months))
    df.to_csv(args.out, index=False)
    print(f"Wrote {len(df)} transactions to {args.out}")


if __name__ == "__main__":
    main()
