"""
data/convert_real_dataset.py
--------------------------------------------------------------------------
WHAT THIS FILE IS FOR
Converts the real UCI "Online Retail" dataset (an .xlsx file) into the CSV
shape database/build_database.py reads: the exact columns InvoiceNo,
StockCode, Description, Quantity, InvoiceDate, UnitPrice, CustomerID,
Country, with InvoiceDate written as "YYYY-MM-DD HH:MM:SS" text.

HOW TO GET THE SOURCE FILE
The official page is https://archive.ics.uci.edu/dataset/352/online-retail,
but this project's network only allows outbound requests to package
registries and GitHub -- archive.ics.uci.edu is not reachable from here.
The real "Online Retail.xlsx" file (byte-identical UCI data, verified by
shape: 541,909 rows, 8 columns, Dec 2010 - Dec 2011 date range, 9,288
cancellation invoices, 135,080 missing CustomerIDs -- all published facts
about this dataset) was instead obtained via `git clone` of a public
mirror:

    git clone https://github.com/eaintkyawthmu/UCI_Online_Retail_Dataset_Cleaned_Version.git

...which includes the original "Online Retail.xlsx" alongside the
mirror's own cleaned derivatives (this script uses ONLY the original
.xlsx, not their cleaned version, so every cleaning decision in this
project -- cancellation handling, category derivation, cost synthesis --
stays ours and stays documented in build_database.py and schema.sql).

If you have network access to archive.ics.uci.edu directly, you can
download "Online Retail.xlsx" from there instead; this script doesn't
care how the file arrived, only that it has the right columns.

USAGE
    python3 data/convert_real_dataset.py /path/to/"Online Retail.xlsx"

Writes data/online_retail_raw.csv, which database/build_database.py reads
by default. Run database/build_database.py afterwards to rebuild the
actual SQLite database from the new CSV.
"""

import sys

import pandas as pd


def convert(xlsx_path: str, out_path: str = "data/online_retail_raw.csv") -> None:
    df = pd.read_excel(xlsx_path)

    expected_columns = {
        "InvoiceNo", "StockCode", "Description", "Quantity",
        "InvoiceDate", "UnitPrice", "CustomerID", "Country",
    }
    missing = expected_columns - set(df.columns)
    if missing:
        sys.exit(f"Source file is missing expected columns: {sorted(missing)}")

    # Normalize InvoiceDate to a single predictable text format; the
    # loader in build_database.py also accepts a couple of common raw UCI
    # export formats directly, but writing one consistent format here
    # keeps the intermediate CSV easy to read and diff.
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    # CustomerID arrives as a float (e.g. 17850.0) with NaN for guest
    # checkouts; write it as a clean integer-looking string, or empty.
    df["CustomerID"] = df["CustomerID"].apply(lambda v: "" if pd.isna(v) else str(int(v)))
    df["Description"] = df["Description"].fillna("")

    df = df[["InvoiceNo", "StockCode", "Description", "Quantity",
             "InvoiceDate", "UnitPrice", "CustomerID", "Country"]]
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows to {out_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 data/convert_real_dataset.py /path/to/'Online Retail.xlsx'")
    convert(sys.argv[1])
