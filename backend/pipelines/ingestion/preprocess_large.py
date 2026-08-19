"""
preprocess_part_d.py

Structural-only preprocessing for the CMS Medicare Part D Prescribers by
Provider and Drug file, prior to loading into the claim_sentinel.db SQLite
database for the rule engine.

Scope (deliberately narrow):
  - schema contract check
  - string-first read, deliberate casting
  - whitespace trim
  - numeric cast with real NULLs (never fill with 0)
  - fixed-width identifier preservation (NPI, FIPS)
  - suppression flags left untouched
  - no dedup, no filtering, no correction, no interpretation
  - load into SQLite using pre-agreed DDL types

Everything else (Completeness, Uniqueness, Validity, Consistency,
Referential Integrity, Plausibility, Correctness) is explicitly OUT of
scope and left for the downstream rule engine.
"""

import sys
import logging
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RAW_FILE_PATH = "Prescribers/Medicare Part D Prescribers - by Provider and Drug/2024/Drug-provider_50000.xlsx"
RAW_FILE_SHEET = 0                 # sheet name or index; update if not the first sheet
RAW_FILE_HEADER_ROW = 0            # 0-indexed row containing real column names;
                                    # bump to 1, 2, etc. if there's a title row above it
                                    # (auto-detected for Excel files regardless)
TABLE_NAME = "part_d_prescriber_drug"

# Path to your existing claim_sentinel.db, same file already open in VS Code's
# SQLite viewer. Relative path assumes the script runs from the same folder
# as claim_sentinel.db — update to an absolute path if that's not the case,
# e.g. r"C:\Users\sweth\OneDrive\Pictures\Desktop\Congnizant\claim_sentinel.db"
SQLITE_DB_PATH = "claim_sentinel.db"
DB_URI = f"sqlite:///{SQLITE_DB_PATH}"

# Exact expected schema — order and spelling matter (contract check)
EXPECTED_COLUMNS = [
    "Prscrbr_NPI",
    "Prscrbr_Last_Org_Name",
    "Prscrbr_First_Name",
    "Prscrbr_City",
    "Prscrbr_State_Abrvtn",
    "Prscrbr_State_FIPS",
    "Prscrbr_Type",
    "Prscrbr_Type_Src",
    "Brnd_Name",
    "Gnrc_Name",
    "Tot_Clms",
    "Tot_30day_Fills",
    "Tot_Day_Suply",
    "Tot_Drug_Cst",
    "Tot_Benes",
    "GE65_Sprsn_Flag",
    "GE65_Tot_Clms",
    "GE65_Tot_30day_Fills",
    "GE65_Tot_Drug_Cst",
    "GE65_Tot_Day_Suply",
    "GE65_Bene_Sprsn_Flag",
    "GE65_Tot_Benes",
]

# Columns to cast to numeric (real NULL on blank, never fill with 0)
NUMERIC_COLUMNS = [
    "Tot_Clms",
    "Tot_30day_Fills",
    "Tot_Day_Suply",
    "Tot_Drug_Cst",
    "Tot_Benes",
    "GE65_Tot_Clms",
    "GE65_Tot_30day_Fills",
    "GE65_Tot_Drug_Cst",
    "GE65_Tot_Day_Suply",
    "GE65_Tot_Benes",
]

# Columns that must stay fixed-format strings (no int casting, no leading-zero strip)
IDENTIFIER_STRING_COLUMNS = [
    "Prscrbr_NPI",
    "Prscrbr_State_FIPS",
]

# Suppression flag columns — left byte-for-byte as given, no interpretation
SUPPRESSION_FLAG_COLUMNS = [
    "GE65_Sprsn_Flag",
    "GE65_Bene_Sprsn_Flag",
]

# All other string/categorical columns — whitespace trim only, no normalization
PLAIN_STRING_COLUMNS = [
    "Prscrbr_Last_Org_Name",
    "Prscrbr_First_Name",
    "Prscrbr_City",
    "Prscrbr_State_Abrvtn",
    "Prscrbr_Type",
    "Prscrbr_Type_Src",
    "Brnd_Name",
    "Gnrc_Name",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("preprocess_part_d")


# ---------------------------------------------------------------------------
# Step 1a: Excel row-limit truncation check
# ---------------------------------------------------------------------------

EXCEL_MAX_ROWS = 1_048_576  # Excel's hard sheet limit, including header

def check_excel_truncation(df: pd.DataFrame, path: str) -> None:
    if not path.lower().endswith((".xlsx", ".xls")):
        return
    # If row count lands exactly at (or one below, accounting for header)
    # Excel's max, the source data may have been cut off when originally
    # saved/converted to .xlsx. This is a silent data-loss risk that no
    # schema or type check would ever catch.
    if len(df) >= EXCEL_MAX_ROWS - 1:
        log.warning(
            "Row count (%d) is at or near Excel's maximum sheet size (%d). "
            "This strongly suggests the source data was TRUNCATED when "
            "saved/converted to .xlsx. Verify against the original CSV "
            "source (e.g. data.cms.gov) or an authoritative row count "
            "before trusting this load.",
            len(df), EXCEL_MAX_ROWS,
        )


# ---------------------------------------------------------------------------
# Step 1: Schema contract check (fail-fast gate)
# ---------------------------------------------------------------------------

def detect_header_row(path: str, sheet=0, max_scan_rows: int = 10) -> int:
    """
    Cheaply scan just the first `max_scan_rows` rows (no dtype forcing, no
    full-file read) to find which row actually contains the expected column
    names — e.g. 'Prscrbr_NPI'. Avoids a wasted ~4 minute full read on a
    wrong header_row guess.
    """
    preview = pd.read_excel(path, sheet_name=sheet, header=None, nrows=max_scan_rows)
    for row_idx in range(len(preview)):
        row_values = set(str(v).strip() for v in preview.iloc[row_idx].tolist())
        overlap = row_values & set(EXPECTED_COLUMNS)
        # A real header row should match most/all expected column names.
        if len(overlap) >= len(EXPECTED_COLUMNS) - 2:
            log.info(
                "Auto-detected header at row %d (matched %d/%d expected columns).",
                row_idx, len(overlap), len(EXPECTED_COLUMNS),
            )
            return row_idx
    raise ValueError(
        f"Could not auto-detect header row within the first {max_scan_rows} "
        f"rows of '{path}'. Inspect the file manually and set "
        f"RAW_FILE_HEADER_ROW explicitly."
    )


def check_schema(df: pd.DataFrame) -> None:
    actual_columns = list(df.columns)
    if actual_columns != EXPECTED_COLUMNS:
        missing = set(EXPECTED_COLUMNS) - set(actual_columns)
        extra = set(actual_columns) - set(EXPECTED_COLUMNS)
        out_of_order = (
            actual_columns != EXPECTED_COLUMNS
            and set(actual_columns) == set(EXPECTED_COLUMNS)
        )
        msg_parts = ["Schema contract check FAILED."]
        if missing:
            msg_parts.append(f"Missing columns: {sorted(missing)}")
        if extra:
            msg_parts.append(f"Unexpected columns: {sorted(extra)}")
        if out_of_order:
            msg_parts.append("Columns present but out of expected order.")
        raise ValueError(" ".join(msg_parts))
    log.info("Schema contract check passed: all %d columns present, in order.",
              len(EXPECTED_COLUMNS))


# ---------------------------------------------------------------------------
# Step 2-3: String-first read + whitespace trim
# ---------------------------------------------------------------------------

def load_raw_as_strings(path: str, sheet=0, header_row=0) -> pd.DataFrame:
    # dtype=str forces every column to load as text; keep_default_na=False
    # combined with na_values=[""] means ONLY truly empty cells become NaN —
    # we don't want pandas guessing "NA", "NULL", "N/A" etc. as missing,
    # since that's an interpretation step, not a structural one.
    #
    # header_row lets us skip a title/metadata row that some CMS exports
    # place above the real column header — without it pandas silently
    # invents "Column1", "Column2"... names instead of failing loudly.
    #
    # Supports both .xlsx (Excel) and .csv source files — dispatched by
    # extension so the same script handles either without edits beyond
    # RAW_FILE_PATH / RAW_FILE_SHEET.
    if path.lower().endswith((".xlsx", ".xls")):
        log.info("Reading Excel file (this is slow for large files, please wait)...")
        try:
            # python-calamine is dramatically faster than openpyxl on large
            # .xlsx files. Falls back to openpyxl if calamine isn't installed.
            df = pd.read_excel(
                path,
                sheet_name=sheet,
                header=header_row,
                dtype=str,
                keep_default_na=False,
                na_values=[""],
                engine="calamine",
            )
        except ImportError:
            log.warning(
                "python-calamine not installed (pip install python-calamine) "
                "— falling back to openpyxl, which is much slower on large files."
            )
            df = pd.read_excel(
                path,
                sheet_name=sheet,
                header=header_row,
                dtype=str,
                keep_default_na=False,
                na_values=[""],
                engine="openpyxl",
            )
        log.info("Excel read complete: %d rows loaded.", len(df))
    else:
        df = pd.read_csv(
            path,
            header=header_row,
            dtype=str,
            keep_default_na=False,
            na_values=[""],
        )
    return df


def trim_whitespace(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        df[col] = df[col].apply(lambda v: v.strip() if isinstance(v, str) else v)
    return df


# ---------------------------------------------------------------------------
# Step 4: Deliberate numeric casting — blanks become real NULL, never 0
# ---------------------------------------------------------------------------

def cast_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in NUMERIC_COLUMNS:
        before_non_null = df[col].notna().sum()
        # errors="raise" would kill the whole load on one bad cell; here we
        # convert what parses and flag genuinely non-numeric garbage loudly
        # rather than silently coercing it to NaN (which would look identical
        # to a legitimate blank/suppressed cell).
        numeric_series = pd.to_numeric(df[col], errors="coerce")
        bad_mask = df[col].notna() & numeric_series.isna()
        if bad_mask.any():
            bad_values = df.loc[bad_mask, col].unique()
            raise ValueError(
                f"Column '{col}' contains non-numeric, non-blank values "
                f"that cannot be cast: {bad_values[:10]}"
            )
        df[col] = numeric_series
        after_non_null = df[col].notna().sum()
        log.info(
            "Cast '%s' to numeric: %d non-null before -> %d non-null after "
            "(blanks preserved as NULL, not 0).",
            col, before_non_null, after_non_null,
        )
    return df


# ---------------------------------------------------------------------------
# Step 5: Fixed-width identifier preservation
# ---------------------------------------------------------------------------

def preserve_identifiers(df: pd.DataFrame) -> pd.DataFrame:
    for col in IDENTIFIER_STRING_COLUMNS:
        # Already string from the string-first read; just confirm no
        # accidental float coercion happened and leave exact digits alone.
        df[col] = df[col].astype("string")
    return df


# ---------------------------------------------------------------------------
# Step 6: Suppression flags — untouched, byte-for-byte
# ---------------------------------------------------------------------------

def leave_suppression_flags(df: pd.DataFrame) -> pd.DataFrame:
    for col in SUPPRESSION_FLAG_COLUMNS:
        df[col] = df[col].astype("string")  # no value changes, just dtype
    return df


# ---------------------------------------------------------------------------
# Step 7: Plain string/categorical columns — dtype only, no normalization
# ---------------------------------------------------------------------------

def finalize_string_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in PLAIN_STRING_COLUMNS:
        df[col] = df[col].astype("string")
    return df


# ---------------------------------------------------------------------------
# Step 8: No row-level filtering — explicitly a no-op, documented for clarity
# ---------------------------------------------------------------------------

def confirm_no_filtering(raw_row_count: int, df: pd.DataFrame) -> None:
    if len(df) != raw_row_count:
        raise AssertionError(
            f"Row count changed during preprocessing ({raw_row_count} -> "
            f"{len(df)}). Preprocessing must not drop or filter rows."
        )
    log.info("Row count unchanged: %d rows in, %d rows out.", raw_row_count, len(df))


# ---------------------------------------------------------------------------
# Step 9: Create target table if missing (SQLite DDL, matches agreed types)
# ---------------------------------------------------------------------------

CREATE_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    Prscrbr_NPI              TEXT,
    Prscrbr_Last_Org_Name    TEXT,
    Prscrbr_First_Name       TEXT,
    Prscrbr_City             TEXT,
    Prscrbr_State_Abrvtn     TEXT,
    Prscrbr_State_FIPS       TEXT,
    Prscrbr_Type             TEXT,
    Prscrbr_Type_Src         TEXT,
    Brnd_Name                TEXT,
    Gnrc_Name                TEXT,
    Tot_Clms                 INTEGER,
    Tot_30day_Fills          DECIMAL(10,2),
    Tot_Day_Suply            INTEGER,
    Tot_Drug_Cst              DECIMAL(12,2),
    Tot_Benes                 INTEGER,
    GE65_Sprsn_Flag           TEXT,
    GE65_Tot_Clms              INTEGER,
    GE65_Tot_30day_Fills       DECIMAL(10,2),
    GE65_Tot_Drug_Cst          DECIMAL(12,2),
    GE65_Tot_Day_Suply         INTEGER,
    GE65_Bene_Sprsn_Flag       TEXT,
    GE65_Tot_Benes             INTEGER
);
"""

def create_table_if_missing(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(CREATE_TABLE_DDL))
    log.info("Confirmed table '%s' exists in %s.", TABLE_NAME, SQLITE_DB_PATH)


# ---------------------------------------------------------------------------
# Step 9b: Load into SQLite using pre-agreed DDL types
# ---------------------------------------------------------------------------

def load_to_db(df: pd.DataFrame, engine, table_name: str) -> int:
    # if_exists="append" relies on create_table_if_missing() having already
    # ensured the table exists with the agreed types. Use "replace" only
    # for a fresh/dev table (drops and recreates, loses agreed types).
    #
    # SQLite caps the number of bound '?' parameters in a single statement
    # (commonly 999, sometimes higher on newer SQLite builds). With 22
    # columns, a chunk of 5000 rows = 110,000 placeholders — way over the
    # limit, causing every insert to silently fail and the table to stay
    # empty. Keep chunk_size small enough that chunk_size * num_columns
    # stays safely under 999 regardless of SQLite version.
    total_rows = len(df)
    num_columns = len(df.columns)
    chunk_size = max(1, 900 // num_columns)  # e.g. 22 cols -> ~40 rows/chunk
    rows_written = 0
    log.info("Starting SQLite insert: %d rows in chunks of %d (safe for SQLite's variable limit)...",
              total_rows, chunk_size)
    for start in range(0, total_rows, chunk_size):
        end = min(start + chunk_size, total_rows)
        try:
            df.iloc[start:end].to_sql(
                table_name,
                con=engine,
                if_exists="append",
                index=False,
                method="multi",
            )
        except Exception as exc:
            # Print a short, useful error instead of letting SQLAlchemy dump
            # the full compiled SQL statement (which floods the terminal).
            log.error("Insert failed at rows %d-%d: %s", start, end, type(exc).__name__)
            raise
        rows_written = end
        if (start // chunk_size) % 500 == 0:  # log periodically, not every chunk
            log.info("Insert progress: %d / %d rows (%.1f%%)",
                      rows_written, total_rows, 100 * rows_written / total_rows)
    log.info("Insert complete: %d / %d rows written.", rows_written, total_rows)
    return rows_written


# ---------------------------------------------------------------------------
# Step 10: Load metadata logging only (no data-quality findings logged here)
# ---------------------------------------------------------------------------

def log_load_metadata(file_path: str, row_count: int) -> None:
    log.info(
        "LOAD METADATA | file=%s | rows_ingested=%d | loaded_at_utc=%s",
        file_path, row_count, datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def main() -> None:
    log.info("Starting preprocessing for: %s", RAW_FILE_PATH)

    header_row = RAW_FILE_HEADER_ROW
    if RAW_FILE_PATH.lower().endswith((".xlsx", ".xls")):
        header_row = detect_header_row(RAW_FILE_PATH, sheet=RAW_FILE_SHEET)

    df = load_raw_as_strings(RAW_FILE_PATH, sheet=RAW_FILE_SHEET, header_row=header_row)
    raw_row_count = len(df)

    check_excel_truncation(df, RAW_FILE_PATH)  # Step 1a — warn, don't block
    check_schema(df)                 # Step 1 — hard gate, raises on failure
    df = trim_whitespace(df)         # Step 3
    df = cast_numeric_columns(df)    # Step 4
    df = preserve_identifiers(df)    # Step 5
    df = leave_suppression_flags(df) # Step 6
    df = finalize_string_columns(df) # Step 7
    confirm_no_filtering(raw_row_count, df)  # Step 8 — assertion, not logic

    engine = create_engine(DB_URI)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))  # connectivity check before bulk load
        create_table_if_missing(engine)      # Step 9a
        rows_written = load_to_db(df, engine, TABLE_NAME)  # Step 9b
    except Exception as exc:
        log.error("SQLite load failed (technical failure, not a QA finding): %s", exc)
        raise

    log_load_metadata(RAW_FILE_PATH, rows_written)  # Step 10
    log.info("Preprocessing complete. Table '%s' ready for rule engine.", TABLE_NAME)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.error("Preprocessing halted: %s", exc)
        sys.exit(1)