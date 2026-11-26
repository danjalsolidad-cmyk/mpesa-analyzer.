# M-Pesa Statement Analyzer

Turn an M-Pesa statement CSV into a clear picture of where your money goes.

It reads the statement, sorts every transaction into a category (bills, shopping,
airtime, fees, Fuliza, and so on), and produces:

- a text summary with monthly totals and savings rate
- spending by category and your top payees
- a list of unusually large transactions (robust outlier detection)
- three charts and a categorized CSV you can open in Excel

## Quick start

```bash
pip install -r requirements.txt

# 1. Try it on fake data
python generate_sample.py
python analyzer.py sample_statement.csv

# 2. Use your own statement
python analyzer.py my_statement.csv --out results
```

Results are saved in the `output/` folder (or the one you pass with `--out`):

| File | What it is |
|------|------------|
| `summary.txt` | Full text report |
| `categorized_transactions.csv` | Every transaction with its category |
| `monthly_in_vs_out.png` | Money in vs out per month |
| `spending_by_category.png` | Spending breakdown |
| `top_payees.png` | Who or where you paid the most |

## Getting your statement

Request your statement from the M-Pesa app or *234# and export it as CSV.
If your PDF statement is password-protected, convert it to CSV first
(a PDF parser such as `pdfplumber` is a good next step, see Ideas below).
The analyzer looks for columns named like `Completion Time`, `Details`,
`Paid In`, `Withdrawn` and `Balance`, and tolerates common variations.

**Privacy:** your statement is processed locally and never leaves your computer.
Do not commit real statements to GitHub. The `generate_sample.py` file produces
fully fictional data for demos and screenshots.

## How it works

- `analyzer.py`: loading and cleaning, rule-based categorization (regex rules in
  `CATEGORY_RULES`, first match wins), aggregation with pandas, charts with matplotlib.
- Outlier detection uses a robust z-score (median and MAD) per category, so a few
  big payments can't hide themselves by inflating the average.
  Regular payees (4+ payments) are compared with their own history, and rare payees
  are compared with all your spending. Known limitation: a payee you pay often but
  irregularly (say, an electronics shop with wildly different amounts) won't be
  flagged, because big amounts are normal for that payee.
- `test_analyzer.py`: unit tests, run with `python -m unittest -v`.

## Customizing categories

Edit `CATEGORY_RULES` at the top of `analyzer.py`. Each entry is
`(category name, regex)`; put more specific rules above general ones.

## Ideas for extending it

- Streamlit dashboard with date filters and a file upload box
- Parse the PDF statement directly with `pdfplumber`
- Machine-learning categorizer (TF-IDF + logistic regression) trained on your own labels
- Monthly budget targets with overspend alerts
- Forecast next month's spending with a simple time-series model
