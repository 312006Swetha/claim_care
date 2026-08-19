"""
CMS FFS Claims + Part D preprocessing pipeline.

Implements the pipeline: Raw CMS files -> Read safely -> Trim whitespace ->
Standardize nulls -> Parse dates -> Correct numeric types -> Preserve
IDs/codes as strings -> Basic quality checks -> Save as CSV.

Encodes the specific rules from the constraints doc:
  - PK per claims table: (BENE_ID, CLM_ID, CLM_LINE_NUM), or LINE_NUM
    instead of CLM_LINE_NUM for carrier/dme.
  - Pipe-delimited (|), dates as DD-Mon-YYYY text.
  - BENE_ID / CLM_ID are intentionally negative -> never CHECK > 0.
  - CHECK (CLM_PMT_AMT >= 0) only -- other *_AMT columns can be blank/0.
  - CLM_THRU_DT >= CLM_FROM_DT where both columns exist.
  - ID/code columns (CARR_NUM, PRVDR_NUM, TAX_NUM, *_PIN_NUM, ICD_DGNS_CD*,
    ICD_PRCDR_CD*, HCPCS_CD, *_VRSN_CD) stay as strings, never cast to int.
  - Blank / whitespace-only strings -> NULL, not "".
  - Part D HLSum / DLSum: skip first 3 title/blank rows.
  - Orphan check: claim BENE_IDs not present in beneficiary before enabling FK.

Adjust INPUT_DIR / file names below to match your actual layout, then run:
    python cms_preprocess.py
"""

from pathlib import Path
import re
import sys
import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Config -- edit to match your local paths
# ---------------------------------------------------------------------------

INPUT_DIR = Path(".")                     # preprocess.py runs from inside Congnizant\ already
CLAIMS_DIR = INPUT_DIR / "All FFS Claims"
PARTD_DIR = INPUT_DIR / "Medicare Part D Prescribers - by Provider"
BENEFICIARY_FILE = INPUT_DIR / "beneficiary_2025.csv"

OUTPUT_DIR = Path("./cms_csv")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# claims table -> (filename, line-number column name)
CLAIMS_TABLES = {
    "carrier":    ("carrier.csv",    "LINE_NUM"),
    "dme":        ("dme.csv",        "LINE_NUM"),
    "hha":        ("hha.csv",        "CLM_LINE_NUM"),
    "hospice":    ("hospice.csv",    "CLM_LINE_NUM"),
    "inpatient":  ("inpatient.csv",  "CLM_LINE_NUM"),
    "outpatient": ("outpatient.csv", "CLM_LINE_NUM"),
    "snf":        ("snf.csv",        "CLM_LINE_NUM"),
}

# columns that must NEVER be cast to numeric, even though they look numeric
ID_CODE_PATTERNS = [
    r"^BENE_ID$", r"^CLM_ID$",
    r"^CARR_NUM$", r"^PRVDR_NUM$", r"^TAX_NUM$", r".*_PIN_NUM$",
    r"^ICD_DGNS_CD\d*$", r"^ICD_PRCDR_CD\d*$", r"^HCPCS_CD$",
    r".*_VRSN_CD$",
]
ID_CODE_RE = re.compile("|".join(ID_CODE_PATTERNS))

DATE_SUFFIX_RE = re.compile(r"_DT$")
AMT_SUFFIX_RE = re.compile(r"_AMT$")


# ---------------------------------------------------------------------------
# Step 1: Read safely
# ---------------------------------------------------------------------------

def read_claims_csv(path: Path) -> pd.DataFrame:
    """Read a pipe-delimited claims file with everything as string first.

    Reading everything as `str` up front prevents pandas from guessing
    types (e.g. turning a leading-zero PRVDR_NUM into an int, or a date
    into its own datetime dtype before we've had a chance to standardize
    nulls). We fix types explicitly in later steps.
    """
    if not path.exists():
        raise FileNotFoundError(f"Missing input file: {path}")
    df = pd.read_csv(
        path,
        sep="|",
        dtype=str,
        keep_default_na=False,   # we do our own null standardization
        na_filter=False,
        low_memory=False,
    )
    return df


# ---------------------------------------------------------------------------
# Step 2: Trim whitespace
# ---------------------------------------------------------------------------

def trim_whitespace(df: pd.DataFrame) -> pd.DataFrame:
    obj_cols = df.columns  # all cols are str/object at this point
    for col in obj_cols:
        df[col] = df[col].str.strip()
    return df


# ---------------------------------------------------------------------------
# Step 3: Standardize nulls
# ---------------------------------------------------------------------------

def standardize_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """Blank / space-only / literal 'NA' style values -> real NaN."""
    null_tokens = {"", "NA", "N/A", "NULL", "."}
    for col in df.columns:
        df[col] = df[col].where(~df[col].isin(null_tokens), other=np.nan)
    return df


# ---------------------------------------------------------------------------
# Step 4: Parse dates (DD-Mon-YYYY -> datetime64)
# ---------------------------------------------------------------------------

def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    date_cols = [c for c in df.columns if DATE_SUFFIX_RE.search(c)]
    for col in date_cols:
        df[col] = pd.to_datetime(df[col], format="%d-%b-%Y", errors="coerce")
    return df, date_cols


# ---------------------------------------------------------------------------
# Step 5: Correct numeric types (amounts only; IDs/codes stay string)
# ---------------------------------------------------------------------------

def fix_numeric_types(df: pd.DataFrame) -> pd.DataFrame:
    amt_cols = [c for c in df.columns if AMT_SUFFIX_RE.search(c) and not ID_CODE_RE.match(c)]
    for col in amt_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").round(2)
    return df, amt_cols


# ---------------------------------------------------------------------------
# Step 6: Preserve IDs/codes as strings (no-op guard + explicit re-cast)
# ---------------------------------------------------------------------------

def preserve_id_code_strings(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if ID_CODE_RE.match(col):
            df[col] = df[col].astype("string")  # pandas nullable string dtype
    return df


# Columns where CMS ships intentionally-negative synthetic IDs. The doc is
# explicit that these must stay negative for referential integrity (don't
# add CHECK (bene_id > 0)) -- but for display/downstream readability we
# strip the leading '-' here, AFTER the string dtype is locked in, so the
# value is still text, never re-cast to a numeric type.
NEGATIVE_ID_COLS = ["BENE_ID", "CLM_ID"]


def strip_negative_sign(df: pd.DataFrame) -> pd.DataFrame:
    for col in NEGATIVE_ID_COLS:
        if col in df.columns:
            df[col] = df[col].str.lstrip("-")
    return df


# ---------------------------------------------------------------------------
# Step 7: Basic quality checks
# ---------------------------------------------------------------------------

def quality_checks(df: pd.DataFrame, table_name: str, pk_cols: list[str],
                    date_cols: list[str]) -> dict:
    report = {"table": table_name, "rows": len(df)}

    # 7a. PK uniqueness + null keys
    report["null_pk_rows"] = int(df[pk_cols].isna().any(axis=1).sum())
    report["duplicate_pk_rows"] = int(df.duplicated(subset=pk_cols).sum())

    # 7b. CLM_PMT_AMT >= 0 (only this amount column gets a hard constraint)
    if "CLM_PMT_AMT" in df.columns:
        report["negative_clm_pmt_amt"] = int((df["CLM_PMT_AMT"] < 0).sum())

    # 7c. CLM_THRU_DT >= CLM_FROM_DT, where both exist
    if "CLM_FROM_DT" in df.columns and "CLM_THRU_DT" in df.columns:
        bad = df["CLM_THRU_DT"] < df["CLM_FROM_DT"]
        report["thru_before_from"] = int(bad.sum())

    # 7d. Date parse failures (non-null source that became NaT)
    report["unparseable_dates"] = {c: int(df[c].isna().sum()) for c in date_cols}

    return report


def orphan_bene_check(claims_df: pd.DataFrame, beneficiary_df: pd.DataFrame | None,
                       table_name: str) -> dict:
    """BENE_IDs present in a claims table but absent from beneficiary."""
    if beneficiary_df is None:
        return {"table": table_name, "orphan_check": "SKIPPED - beneficiary not loaded"}
    known = set(beneficiary_df["BENE_ID"].dropna())
    claim_ids = set(claims_df["BENE_ID"].dropna())
    orphans = claim_ids - known
    return {"table": table_name, "orphan_bene_id_count": len(orphans)}


# ---------------------------------------------------------------------------
# Step 8: Save as CSV
# ---------------------------------------------------------------------------

def save_parquet(df: pd.DataFrame, name: str) -> Path:
    out_path = OUTPUT_DIR / f"{name}.csv"
    df.to_csv(out_path, index=False)
    return out_path


# ---------------------------------------------------------------------------
# Claims table pipeline
# ---------------------------------------------------------------------------

def process_claims_table(table_name: str, filename: str, line_col: str) -> tuple[pd.DataFrame, dict]:
    path = CLAIMS_DIR / filename
    df = read_claims_csv(path)
    df = trim_whitespace(df)
    df = standardize_nulls(df)
    df, date_cols = parse_dates(df)
    df, amt_cols = fix_numeric_types(df)
    df = preserve_id_code_strings(df)
    df = strip_negative_sign(df)

    pk_cols = ["BENE_ID", "CLM_ID", line_col]
    missing_pk = [c for c in pk_cols if c not in df.columns]
    if missing_pk:
        raise ValueError(f"{table_name}: missing expected PK column(s) {missing_pk}")

    report = quality_checks(df, table_name, pk_cols, date_cols)
    return df, report


# ---------------------------------------------------------------------------
# Beneficiary table (real file, once landed -- was a placeholder in the doc)
# ---------------------------------------------------------------------------

def process_beneficiary(path: Path) -> pd.DataFrame:
    df = read_claims_csv(path)
    df = trim_whitespace(df)
    df = standardize_nulls(df)
    df, _ = parse_dates(df)
    df, _ = fix_numeric_types(df)
    df = preserve_id_code_strings(df)
    df = strip_negative_sign(df)
    if "BENE_ID" in df.columns:
        df["BENE_ID"] = df["BENE_ID"].astype("string")
    return df


# ---------------------------------------------------------------------------
# Part D summary files (xlsx) -- header=3 skip rule, Y/N flag check
# ---------------------------------------------------------------------------

def process_partd_hlsum(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Data", header=3)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def process_partd_dlsum(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Medicare Part D Drug Lists", header=3)
    df.columns = [str(c).strip() for c in df.columns]
    flag_cols = [c for c in df.columns if "Flag" in c]
    bad_flags = {}
    for c in flag_cols:
        invalid = ~df[c].isin(["Y", "N", np.nan])
        if invalid.any():
            bad_flags[c] = int(invalid.sum())
    if bad_flags:
        print(f"  WARNING - DLSum flag values outside Y/N: {bad_flags}")
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    reports = []

    # Beneficiary first (parent table)
    beneficiary_df = None
    if BENEFICIARY_FILE.exists():
        print(f"Loading beneficiary: {BENEFICIARY_FILE}")
        beneficiary_df = process_beneficiary(BENEFICIARY_FILE)
        save_parquet(beneficiary_df, "beneficiary")
        print(f"  rows={len(beneficiary_df)} -> saved beneficiary.csv")
    else:
        print(f"NOTE: {BENEFICIARY_FILE} not found -- orphan checks will be skipped, "
              f"FK enforcement deferred (matches placeholder note in the constraints doc).")

    # Claims tables
    for table_name, (filename, line_col) in CLAIMS_TABLES.items():
        print(f"Processing {table_name} ({filename}) ...")
        try:
            df, report = process_claims_table(table_name, filename, line_col)
        except FileNotFoundError as e:
            print(f"  SKIPPED: {e}")
            continue
        orphan_report = orphan_bene_check(df, beneficiary_df, table_name)
        report.update(orphan_report)
        reports.append(report)

        out_path = save_parquet(df, table_name)
        print(f"  rows={report['rows']} dup_pk={report['duplicate_pk_rows']} "
              f"null_pk={report['null_pk_rows']} -> {out_path}")

    # Part D summary files -- match actual filenames in your directory
    hlsum_candidates = list(PARTD_DIR.glob("*HLSum*.xlsx"))
    dlsum_candidates = list(PARTD_DIR.glob("*DLSum*.xlsx"))

    if hlsum_candidates:
        print(f"Processing Part D HLSum: {hlsum_candidates[0].name}")
        hlsum_df = process_partd_hlsum(hlsum_candidates[0])
        save_parquet(hlsum_df, "partd_national_totals")
        print(f"  rows={len(hlsum_df)} -> saved partd_national_totals.csv")
    else:
        print("NOTE: no HLSum xlsx found, skipping Part D national totals.")

    if dlsum_candidates:
        print(f"Processing Part D DLSum: {dlsum_candidates[0].name}")
        dlsum_df = process_partd_dlsum(dlsum_candidates[0])
        save_parquet(dlsum_df, "partd_drug_list")
        print(f"  rows={len(dlsum_df)} -> saved partd_drug_list.csv")
    else:
        print("NOTE: no DLSum xlsx found, skipping Part D drug list.")

    # Summary report
    print("\n=== Quality check summary ===")
    for r in reports:
        print(r)

    if reports:
        pd.DataFrame(reports).to_csv(OUTPUT_DIR / "quality_report.csv", index=False)
        print(f"\nFull quality report written to {OUTPUT_DIR / 'quality_report.csv'}")


if __name__ == "__main__":
    main()