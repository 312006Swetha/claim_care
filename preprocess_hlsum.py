"""
Load CMS Part D Prescriber Grand Totals (2013-2024) into BOTH:
  1. The SQLite file claim_sentinel.db (the same file your other tables
     -- beneficiary, carrier, dme, medicare_part_d_drug_lists, etc. --
     already live in, viewed via the SQLite Viewer extension in VS Code)
  2. The MySQL database `claim_sentinel` on localhost:3306

These are two SEPARATE databases that just happen to share a name.
Writing to MySQL does NOT touch the .db file, and vice versa -- that's
why the table didn't show up in the SQLite Viewer after the last run.

Run in VS Code's integrated terminal, from the folder containing
claim_sentinel.db (e.g. C:\\Users\\swetha\\Pictures\\Desktop\\Congnizant):
    pip install pandas openpyxl sqlalchemy pymysql --break-system-packages
    python load_part_d_grand_totals.py --xlsx MUP_DPR_RY26_P06_V10_DYT24_HLSum.xlsx

Or import run() from another script/notebook cell in VS Code.
"""

import re
import sys
import argparse
import sqlite3
import pandas as pd
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# 1. CONNECTION SETTINGS  (edit here, or override with CLI flags / env vars)
# ---------------------------------------------------------------------------
DB_HOST = "localhost"
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "Shwe16"
DB_NAME = "claim_sentinel"
TABLE_NAME = "part_d_grand_totals"

# Path to the SQLite file that VS Code's SQLite Viewer has open.
# Update this if claim_sentinel.db lives somewhere other than the
# script's working directory.
SQLITE_PATH = "claim_sentinel.db"

XLSX_PATH = "Prescribers/Medicare Part D Prescribers - by Provider and Drug/2024/MUP_DPR_RY26_P06_V10_DYT24_HLSum.xlsx"
SHEET_NAME = "Data"
HEADER_ROW = 3  # 0-indexed: title row + 2 blank rows, header is row 4 in Excel

# ---------------------------------------------------------------------------
# 2. COLUMN NORMALIZATION RULES
#    (explicit map = predictable; regex fallback = safety net for any
#    columns not already listed, e.g. if CMS tweaks header text later)
# ---------------------------------------------------------------------------
COLUMN_MAP = {
    'Calendar Year': 'calendar_year',
    'Total Claims': 'total_claims',
    'Total Standardized 30-Day Fills': 'total_standardized_30_day_fills',
    'Total Drug Cost': 'total_drug_cost',
    'Total Beneficiaries': 'total_beneficiaries',
    'Total Prescribers': 'total_prescribers',
    'Total Claims for Beneficiaries  (Age 65+)': 'total_claims_for_beneficiaries_age65plus',
    'Total Standardized 30-Day Fills for Beneficiaries (Age 65+)': 'total_standardized_30_day_fills_for_beneficiaries_age65plus',
    'Total Drug Cost for Beneficiaries  (Age 65+)': 'total_drug_cost_for_beneficiaries_age65plus',
    'Total Beneficiaries (Age 65+)': 'total_beneficiaries_age65plus',
    'Total Claims for Brand Drugs': 'total_claims_for_brand_drugs',
    'Total Drug Cost  for Brand Drugs': 'total_drug_cost_for_brand_drugs',
    'Total Claims for Generic Drugs': 'total_claims_for_generic_drugs',
    'Total Drug Cost for Generic Drugs': 'total_drug_cost_for_generic_drugs',
    'Total Claims for Other Drugs': 'total_claims_for_other_drugs',
    'Total Drug Cost for Other Drugs': 'total_drug_cost_for_other_drugs',
    'Total Claims for LIS Beneficiaries': 'total_claims_for_lis_beneficiaries',
    'Total Drug Cost for LIS Beneficiaries': 'total_drug_cost_for_lis_beneficiaries',
    'Total Claims for NonLIS Beneficiaries': 'total_claims_for_nonlis_beneficiaries',
    'Total Drug Cost for NonLIS Beneficiaries': 'total_drug_cost_for_nonlis_beneficiaries',
    'Total Claims for Antibiotic Drugs': 'total_claims_for_antibiotic_drugs',
    'Total Drug Cost  for Antibiotic Drugs': 'total_drug_cost_for_antibiotic_drugs',
    'Total Beneficiaries for Antibiotic Drugs': 'total_beneficiaries_for_antibiotic_drugs',
    'Total Claims for Antipsychotic Drugs (Age 65+)': 'total_claims_for_antipsychotic_drugs_age65plus',
    'Total Drug Cost for Antipsychotic Drugs  (Age 65+)': 'total_drug_cost_for_antipsychotic_drugs_age65plus',
    'Total Beneficiaries for Antipsychotic Drugs  (Age 65+)': 'total_beneficiaries_for_antipsychotic_drugs_age65plus',
    'Total Claims for Opioid Drugs': 'total_claims_for_opioid_drugs',
    'Total Drug Cost  for Opioid Drugs': 'total_drug_cost_for_opioid_drugs',
    'Total Beneficiaries for Opioid Drugs': 'total_beneficiaries_for_opioid_drugs',
    'Total Claims for LA Opioid Drugs': 'total_claims_for_la_opioid_drugs',
    'Total Drug Cost  for LA Opioid Drugs': 'total_drug_cost_for_la_opioid_drugs',
    'Total Beneficiaries for LA Opioid Drugs': 'total_beneficiaries_for_la_opioid_drugs',
}


def _fallback_clean(col: str) -> str:
    """Regex fallback for any column not in COLUMN_MAP."""
    c = re.sub(r"\s+", " ", col).strip().lower()
    c = c.replace("(age 65+)", "age65plus")
    c = re.sub(r"[^a-z0-9]+", "_", c)
    return re.sub(r"_+", "_", c).strip("_")


# Columns that are whole-number counts (claims, fills, beneficiaries, prescribers)
INT_SUFFIXES = ("claims", "fills", "beneficiaries", "prescribers")
# Columns that are dollar amounts
COST_KEYWORD = "cost"


def load_and_clean(xlsx_path: str) -> pd.DataFrame:
    df = pd.read_excel(xlsx_path, sheet_name=SHEET_NAME, header=HEADER_ROW)

    # Normalize headers
    new_cols = {}
    for c in df.columns:
        c_str = str(c)
        new_cols[c] = COLUMN_MAP.get(c_str, _fallback_clean(c_str))
    df = df.rename(columns=new_cols)

    # Drop fully-empty rows and duplicate years
    df = df.dropna(how="all")
    df = df[df["calendar_year"].notna()]
    df = df.drop_duplicates(subset="calendar_year", keep="first")

    # Type coercion
    for col in df.columns:
        if col == "calendar_year" or any(col.startswith(p) or f"_{p}" in col or col.endswith(p) for p in INT_SUFFIXES):
            df[col] = pd.to_numeric(df[col], errors="coerce")
            if col != "calendar_year" and "cost" not in col:
                df[col] = df[col].round(0)
        if COST_KEYWORD in col or "standardized" in col:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

    df["calendar_year"] = df["calendar_year"].astype(int)
    for col in df.columns:
        if col != "calendar_year" and pd.api.types.is_float_dtype(df[col]) and "cost" not in col and "standardized" not in col:
            df[col] = df[col].astype("Int64")

    df = df.sort_values("calendar_year").reset_index(drop=True)
    return df


def build_engine(host, port, user, password, database, create_db_if_missing=True):
    # Connect without a DB first so we can CREATE DATABASE IF NOT EXISTS
    root_engine = create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/")
    if create_db_if_missing:
        with root_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{database}` "
                               f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
            conn.commit()
    return create_engine(f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}")


def create_table_sql(df: pd.DataFrame, table_name: str, dialect: str = "mysql") -> str:
    q = "`" if dialect == "mysql" else '"'
    col_defs = []
    for col in df.columns:
        if dialect == "mysql":
            int_type, num_type = "BIGINT", "DECIMAL(18,2)"
        else:  # sqlite
            int_type, num_type = "INTEGER", "REAL"
        if col == "calendar_year":
            col_defs.append(f"{q}{col}{q} {'SMALLINT' if dialect == 'mysql' else 'INTEGER'} NOT NULL PRIMARY KEY")
        elif "cost" in col or "standardized" in col:
            col_defs.append(f"{q}{col}{q} {num_type}")
        else:
            col_defs.append(f"{q}{col}{q} {int_type}")
    cols_sql = ",\n    ".join(col_defs)
    stmt = f"CREATE TABLE IF NOT EXISTS {q}{table_name}{q} (\n    {cols_sql}\n)"
    if dialect == "mysql":
        stmt += " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    return stmt + ";"


def load_into_sqlite(df: pd.DataFrame, sqlite_path: str, table: str):
    """Write to the local .db file (same one the SQLite Viewer has open)."""
    conn = sqlite3.connect(sqlite_path)
    try:
        conn.execute(create_table_sql(df, table, dialect="sqlite"))
        df.to_sql(table, conn, if_exists="append", index=False)
        conn.commit()
    finally:
        conn.close()
    print(f"Loaded {len(df)} rows into SQLite table '{table}' in {sqlite_path}")


def load_into_mysql(df: pd.DataFrame, host, port, user, password, database, table):
    engine = build_engine(host, port, user, password, database)
    with engine.connect() as conn:
        conn.execute(text(create_table_sql(df, table, dialect="mysql")))
        conn.commit()
    df.to_sql(table, engine, if_exists="append", index=False)
    print(f"Loaded {len(df)} rows into MySQL `{database}`.`{table}` on {host}:{port}")


def run(xlsx_path=XLSX_PATH, host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, database=DB_NAME, table=TABLE_NAME,
        sqlite_path=SQLITE_PATH, targets=("sqlite", "mysql"), dry_run=False):
    df = load_and_clean(xlsx_path)
    print(f"Loaded & cleaned {len(df)} rows x {len(df.columns)} columns from {xlsx_path}")

    if dry_run:
        out_csv = "part_d_grand_totals_clean.csv"
        df.to_csv(out_csv, index=False)
        print(f"[dry-run] Skipped DB write. Cleaned data saved to {out_csv}")
        return df

    if "sqlite" in targets:
        load_into_sqlite(df, sqlite_path, table)

    if "mysql" in targets:
        load_into_mysql(df, host, port, user, password, database, table)

    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load CMS Part D Grand Totals into MySQL")
    parser.add_argument("--xlsx", default=XLSX_PATH)
    parser.add_argument("--host", default=DB_HOST)
    parser.add_argument("--port", type=int, default=DB_PORT)
    parser.add_argument("--user", default=DB_USER)
    parser.add_argument("--password", default=DB_PASSWORD)
    parser.add_argument("--database", default=DB_NAME)
    parser.add_argument("--table", default=TABLE_NAME)
    parser.add_argument("--sqlite-path", default=SQLITE_PATH,
                         help="Path to claim_sentinel.db")
    parser.add_argument("--target", choices=["sqlite", "mysql", "both"], default="both",
                         help="Which database(s) to load into")
    parser.add_argument("--dry-run", action="store_true", help="clean data + write CSV only, skip DB writes")
    args = parser.parse_args()

    targets = ("sqlite", "mysql") if args.target == "both" else (args.target,)

    try:
        run(args.xlsx, args.host, args.port, args.user, args.password,
            args.database, args.table, args.sqlite_path, targets, args.dry_run)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)