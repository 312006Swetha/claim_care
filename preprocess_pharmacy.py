"""
Load "Medicare Part D Drug Lists" sheet from
MUP_DPR_RY26_P06_V10_DYT24_DLSum.xlsx into MySQL.

Run in VS Code:
    1. pip install -r requirements.txt
    2. Fill in DB_CONFIG below (or use a .env file, see note at bottom)
    3. python load_drug_list_to_mysql.py
"""
import sqlite3
import sys
import pandas as pd
import mysql.connector
from mysql.connector import Error

# ------------------------------------------------------------------
# 1. CONFIG — edit these
# ------------------------------------------------------------------
EXCEL_PATH = "Prescribers/Medicare Part D Prescribers - by Provider and Drug/2024/MUP_DPR_RY26_P06_V10_DYT24_DLSum.xlsx"
SHEET_NAME = "Medicare Part D Drug Lists"

DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "Shwe16",
    "database": "claim_sentinel",
}

TABLE_NAME = "medicare_part_d_drug_lists"

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    id INT AUTO_INCREMENT PRIMARY KEY,
    drug_name VARCHAR(50) NOT NULL,
    generic_name VARCHAR(50) NOT NULL,
    opioid_flag CHAR(1) NOT NULL,
    la_opioid_flag CHAR(1) NOT NULL,
    antibiotic_flag CHAR(1) NOT NULL,
    antipsychotic_flag CHAR(1) NOT NULL,
    ndc_conflict_flag CHAR(1) NOT NULL,
    INDEX idx_drug_name (drug_name)
);
"""

INSERT_SQL = f"""
INSERT INTO {TABLE_NAME}
    (drug_name, generic_name, opioid_flag, la_opioid_flag,
     antibiotic_flag, antipsychotic_flag, ndc_conflict_flag)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""

EXCEL_TO_MYSQL_COLUMNS = {
    "Drug Name": "drug_name",
    "Generic Name": "generic_name",
    "Opioid Flag": "opioid_flag",
    "LA Opioid Flag": "la_opioid_flag",
    "Antibiotic Flag": "antibiotic_flag",
    "Antipsychotic Flag": "antipsychotic_flag",
    "NDC Conflict Flag": "ndc_conflict_flag",
}

FLAG_COLUMNS = [
    "opioid_flag", "la_opioid_flag", "antibiotic_flag",
    "antipsychotic_flag", "ndc_conflict_flag",
]

EXPECTED_ROW_COUNT = 474  # sanity check; adjust if source file is refreshed

def load_to_sqlite(df: pd.DataFrame) -> None:
    SQLITE_DB = "claim_sentinel.db"

    conn = None

    try:
        conn = sqlite3.connect(SQLITE_DB)
        cursor = conn.cursor()

        # Create table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS medicare_part_d_drug_lists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                drug_name VARCHAR(50) NOT NULL,
                generic_name VARCHAR(50) NOT NULL,
                opioid_flag CHAR(1) NOT NULL,
                la_opioid_flag CHAR(1) NOT NULL,
                antibiotic_flag CHAR(1) NOT NULL,
                antipsychotic_flag CHAR(1) NOT NULL,
                ndc_conflict_flag CHAR(1) NOT NULL
            )
        """)

        rows = [
            (
                r.drug_name,
                r.generic_name,
                r.opioid_flag,
                r.la_opioid_flag,
                r.antibiotic_flag,
                r.antipsychotic_flag,
                r.ndc_conflict_flag
            )
            for r in df.itertuples(index=False)
        ]

        cursor.executemany("""
            INSERT INTO medicare_part_d_drug_lists
            (
                drug_name,
                generic_name,
                opioid_flag,
                la_opioid_flag,
                antibiotic_flag,
                antipsychotic_flag,
                ndc_conflict_flag
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rows)

        conn.commit()

        print(
            f"Inserted {len(rows)} rows into SQLite "
            f"'claim_sentinel.db' → medicare_part_d_drug_lists."
        )

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        sys.exit(1)

    finally:
        if conn:
            conn.close()

# ------------------------------------------------------------------
# 2. EXTRACT + CLEAN
# ------------------------------------------------------------------
def load_and_clean(path: str, sheet: str) -> pd.DataFrame:
    # Row 4 in Excel (1-indexed) = header row -> header=3 (0-indexed) in pandas
    df = pd.read_excel(path, sheet_name=sheet, header=3)

    # Rename columns to MySQL snake_case
    df = df.rename(columns=EXCEL_TO_MYSQL_COLUMNS)
    df = df[list(EXCEL_TO_MYSQL_COLUMNS.values())]

    # Drop fully empty rows
    df = df.dropna(how="all")

    # Strip whitespace from text columns
    df["drug_name"] = df["drug_name"].astype(str).str.strip()
    df["generic_name"] = df["generic_name"].astype(str).str.strip()

    # Standardize flag columns to upper-case Y/N
    for col in FLAG_COLUMNS:
        df[col] = df[col].astype(str).str.strip().str.upper()

    return df.reset_index(drop=True)


# ------------------------------------------------------------------
# 3. VALIDATE
# ------------------------------------------------------------------
def validate(df: pd.DataFrame) -> None:
    errors = []

    # Row count check
    if len(df) != EXPECTED_ROW_COUNT:
        errors.append(
            f"Row count mismatch: expected {EXPECTED_ROW_COUNT}, got {len(df)}"
        )

    # Null check on required columns
    required_cols = list(EXCEL_TO_MYSQL_COLUMNS.values())
    null_counts = df[required_cols].isnull().sum()
    for col, count in null_counts.items():
        if count > 0:
            errors.append(f"Column '{col}' has {count} null value(s)")

    # Flag value check — only Y/N allowed
    for col in FLAG_COLUMNS:
        bad_values = df.loc[~df[col].isin(["Y", "N"]), col].unique()
        if len(bad_values) > 0:
            errors.append(f"Column '{col}' has invalid flag values: {bad_values}")

    # Full-row duplicate check (informational — not blocking)
    dup_count = df.duplicated().sum()
    if dup_count > 0:
        print(f"[WARNING] {dup_count} full-row duplicate(s) found — will be inserted as-is "
              f"unless you choose to drop them.")

    # NOTE: do NOT check drug_name for uniqueness/duplicates.
    # Multiple rows legitimately share the same drug_name with different
    # generic_name values (different formulations/NDCs).

    if errors:
        print("Validation FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"Validation passed: {len(df)} rows ready to load.")


# ------------------------------------------------------------------
# 4. LOAD INTO MYSQL
# ------------------------------------------------------------------
def load_to_mysql(df: pd.DataFrame) -> None:
    conn = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        cursor.execute(CREATE_TABLE_SQL)
        conn.commit()
        print(f"Table '{TABLE_NAME}' ready.")

        rows = [
            (
                r.drug_name, r.generic_name, r.opioid_flag, r.la_opioid_flag,
                r.antibiotic_flag, r.antipsychotic_flag, r.ndc_conflict_flag,
            )
            for r in df.itertuples(index=False)
        ]

        cursor.executemany(INSERT_SQL, rows)
        conn.commit()
        print(f"Inserted {cursor.rowcount} rows into '{TABLE_NAME}'.")

    except Error as e:
        print(f"MySQL error: {e}")
        sys.exit(1)
    finally:
        if conn and conn.is_connected():
            cursor.close()
            conn.close()


# ------------------------------------------------------------------
# 5. MAIN
# ------------------------------------------------------------------
if __name__ == "__main__":

    df = load_and_clean(EXCEL_PATH, SHEET_NAME)

    validate(df)

    # Load into MySQL
    load_to_mysql(df)

    # Load into SQLite claim_sentinel.db
    load_to_sqlite(df)

    print("Done.")