# `data/convert_real_dataset.py` — explained

**What it is:** a one-time conversion script that turns the real UCI
"Online Retail.xlsx" file into the CSV shape `database/build_database.py`
expects.

## Why this step exists at all

The UCI dataset is published as an Excel file (`.xlsx`), not a CSV, and
its `InvoiceDate` column is stored as a spreadsheet datetime, not text.
Rather than teach the database loader to understand Excel files directly,
this script does that conversion once, up front, producing a plain CSV
that's easy to read, diff, and reason about.

## How the real file was actually obtained here

The official source, archive.ics.uci.edu, wasn't reachable from this
project's sandboxed network (outbound access is limited to package
registries and GitHub). The real file was instead fetched with:

```bash
git clone https://github.com/eaintkyawthmu/UCI_Online_Retail_Dataset_Cleaned_Version.git
```

— a public mirror that includes the original, unmodified `Online
Retail.xlsx`. The script was pointed at that original file (not the
mirror's own "cleaned" derivative files), so every cleaning decision in
this project is still made by `build_database.py`, in one documented
place, rather than inherited silently from someone else's preprocessing.
Its authenticity was checked against published facts about the dataset
before use: 541,909 rows, a Dec 2010–Dec 2011 date range, 9,288
cancellation invoices, and 135,080 rows with no `CustomerID` — all of
which matched.

## What the conversion does

1. Reads the `.xlsx` with `pandas.read_excel`.
2. Checks that all eight expected columns are present (fails loudly with
   a clear message if not, rather than silently producing a broken CSV).
3. Reformats `InvoiceDate` from a spreadsheet datetime into plain text
   (`YYYY-MM-DD HH:MM:SS`).
4. Cleans up `CustomerID`: it arrives as a float (`17850.0`) with
   missing values for guest checkouts; this writes it as a clean integer
   string, or an empty string for guests.
5. Writes the result to `data/online_retail_raw.csv`.

## Usage

```bash
python3 data/convert_real_dataset.py "/path/to/Online Retail.xlsx"
```

Then rebuild the database from the new CSV:

```bash
python3 database/build_database.py
```
