"""Tests for the analyzer. Run with:  python -m unittest -v"""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

import analyzer


class CategorizeTests(unittest.TestCase):
    def test_fee_beats_transfer(self):
        self.assertEqual(analyzer.categorize("Customer Transfer of Funds Charge"), "Fees & Charges")

    def test_basic_categories(self):
        cases = {
            "Customer Transfer to - 2547XXXX123 Jane D": "Sent to People",
            "Merchant Payment to 123 - Some Shop": "Shopping & Merchants",
            "Pay Bill to 888880 - Power Prepaid": "Rent & Bills",
            "Airtime Purchase": "Airtime & Data",
            "Withdrawal at Agent 456789 - Jua Kali": "Cash Withdrawal",
            "Funds received from - Acme Payroll": "Received",
            "OD Loan Repayment to Fuliza": "Fuliza",
            "Something totally new": "Other",
        }
        for details, expected in cases.items():
            with self.subTest(details=details):
                self.assertEqual(analyzer.categorize(details), expected)

    def test_counterparty(self):
        self.assertEqual(
            analyzer.counterparty("Merchant Payment to 123 - green basket"), "Green Basket"
        )


class LoadTests(unittest.TestCase):
    def _write_csv(self, rows):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "s.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        return path

    def test_parses_commas_negatives_and_skips_failed(self):
        path = self._write_csv([
            {"Receipt No.": "A", "Completion Time": "2026-01-05 10:00:00", "Details": "Funds received from - Acme Payroll",
             "Transaction Status": "Completed", "Paid In": "60,000.00", "Withdrawn": "", "Balance": "60,000.00"},
            {"Receipt No.": "B", "Completion Time": "2026-01-06 10:00:00", "Details": "Merchant Payment to 1 - Shop",
             "Transaction Status": "Completed", "Paid In": "", "Withdrawn": "-1,500.00", "Balance": "58,500.00"},
            {"Receipt No.": "C", "Completion Time": "2026-01-07 10:00:00", "Details": "Merchant Payment to 1 - Shop",
             "Transaction Status": "Failed", "Paid In": "", "Withdrawn": "-999", "Balance": "58,500.00"},
        ])
        df = analyzer.load_statement(path)
        self.assertEqual(len(df), 2)  # failed row dropped
        self.assertEqual(df["paid_in"].sum(), 60000)
        self.assertEqual(df["withdrawn"].sum(), 1500)  # negative sign removed

    def test_missing_column_gives_clear_error(self):
        path = self._write_csv([{"foo": 1, "bar": 2}])
        with self.assertRaises(ValueError):
            analyzer.load_statement(path)


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        times = pd.date_range("2026-01-01", periods=8, freq="D")
        self.df = pd.DataFrame({
            "time": times,
            "details": ["x"] * 8,
            "paid_in": [1000.0] + [0.0] * 7,
            "withdrawn": [0.0, 100, 110, 90, 105, 95, 100, 5000],
            "category": ["Received"] + ["Shopping & Merchants"] * 7,
            "counterparty": ["Employer"] + ["Shop"] * 7,
        })
        self.df["month"] = self.df["time"].dt.to_period("M").astype(str)

    def test_monthly_net(self):
        monthly = analyzer.monthly_summary(self.df)
        self.assertEqual(monthly.loc["2026-01", "net"], 1000 - self.df["withdrawn"].sum())

    def test_flags_the_outlier(self):
        flagged = analyzer.flag_unusual(self.df)
        self.assertEqual(list(flagged["withdrawn"]), [5000])


if __name__ == "__main__":
    unittest.main()
