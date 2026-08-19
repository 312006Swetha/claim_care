import os
import re
import json
import uuid
import traceback
import pandas as pd
from datetime import datetime
from collections import defaultdict
from sqlalchemy import create_engine, inspect, text
from dagster import (
    op,
    job,
    In,
    Out,
    Nothing,
    Failure,
    OpExecutionContext,
)
# ============================================================================
# CONFIGURATION
# ============================================================================
# -----------------------------
# SQLITE DATABASE CONFIGURATION
# -----------------------------
# The DQ engine reads ALL source data directly from claim_sentinel.db.
# No MySQL connection is used anywhere in this version.
SOURCE_SQLITE_DATABASE = "claim_sentinel.db"
SOURCE_SQLITE_ENGINE = create_engine(
    f"sqlite:///{SOURCE_SQLITE_DATABASE}",
    future=True
)

# All DQ output is stored in claim_dagster.db -> dq_run_output.
DQ_SQLITE_DATABASE = "claim_dagster.db"
DQ_SQLITE_ENGINE = create_engine(
    f"sqlite:///{DQ_SQLITE_DATABASE}",
    future=True
)

# ============================================================================
# OTHER CONFIGURATION
# ============================================================================
OUT_DIR = "./dq_output"
CHUNKSIZE = 200_000
# Accepted date formats, tried in this order until one parses.
DATE_FMTS = [
    "%Y%m%d",
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d-%b-%Y"
]
TODAY = pd.Timestamp(datetime.now().date())
# Maximum number of sample rows stored for each rule
MAX_SAMPLES = 5000
# ============================================================================
# ICD-10 CUTOVER DATE
# ============================================================================
# CMS ICD-9-CM -> ICD-10-CM mandatory cutover date.
#
# Claims with CLM_FROM_DT:
#   >= 2015-10-01 -> ICD-10
#   <  2015-10-01 -> ICD-9
#
# Used for claim tables that do not contain an explicit
# ICD_DGNS_VRSN_CD column.
ICD10_CUTOVER = pd.Timestamp("2015-10-01")
# ============================================================================
# CREATE OUTPUT DIRECTORY
# ============================================================================
os.makedirs(OUT_DIR, exist_ok=True)
# ============================================================================
# CLAIM TABLES
# ============================================================================
# These are the source tables expected in claim_sentinel.db.
# The source is SQLite only. The names correspond to the original CSV names.
CLAIM_TABLES = [
    "carrier",
    "dme",
    "hha",
    "hospice",
    "inpatient",
    "outpatient",
]
# ============================================================================
# GLOBAL STATE SHARED ACROSS RULE-CHECK FUNCTIONS
# ============================================================================
# These were previously created ad-hoc inside `if __name__ == "__main__"`.
# They are now declared at module scope so Dagster ops (which each run as
# their own call into this module) can read/write them safely, without
# touching how the rule-check functions themselves use them.
# ============================================================================
VALID_BENE_IDS = set()
# Row counts per output "file" (e.g. "carrier.csv", "beneficiary_2025.csv").
# Used ONLY for persistence/reporting (affected_pct, pass/fail counts) —
# never consulted by the rule-check functions.
TABLE_ROW_COUNTS = defaultdict(int)
# Provider-level Completeness tracking grouped by the file-specific provider NPI column.
# This is additional output only and does not change existing DQ rule results.
PROVIDER_COMPLETENESS_COUNTS = defaultdict(lambda: {"total_rows": 0, "rules": defaultdict(int)})
PROVIDER_COMPLETENESS_RECORD_KEYS = defaultdict(set)
# Provider-level DQ tracking for all six dimensions.
# This is additional output only and does not change existing DQ rules.
PROVIDER_DQ_TOTAL_ROWS = defaultdict(int)
PROVIDER_DQ_DIMENSION_COUNTS = defaultdict(int)
PROVIDER_DQ_RECORD_KEYS = defaultdict(set)
# Provider NPI column used for provider-level grouping for each claim file.
# This is only for the additional provider-level DQ output.
PROVIDER_NPI_COLUMNS = {
    "carrier.csv": "PRF_PHYSN_NPI",
    "dme.csv": "PRVDR_NPI",
    "hha.csv": "ORG_NPI_NUM",
    "hospice.csv": "ORG_NPI_NUM",
    "inpatient.csv": "ORG_NPI_NUM",
    "outpatient.csv": "ORG_NPI_NUM",
}

def provider_npi_column(file, df):
    col = PROVIDER_NPI_COLUMNS.get(file)
    return col if col in df.columns else None

# ============================================================================
# HELPERS
# ============================================================================
def source_table_exists(conn, table):
    # Return True when a source table exists in claim_sentinel.db.
    return inspect(conn).has_table(table)


def to_date(series):
    """
    Parse dates safely, trying each format in DATE_FMTS in order.
    Invalid or missing dates become NaT.
    """
    s = series.astype(str).str.strip()
    result = pd.Series(
        pd.NaT,
        index=s.index,
        dtype="datetime64[ns]"
    )
    remaining = result.isna()
    for fmt in DATE_FMTS:
        if not remaining.any():
            break
        parsed = pd.to_datetime(
            s[remaining],
            format=fmt,
            errors="coerce"
        )
        result.loc[remaining] = parsed
        remaining = result.isna()
    return result
def is_blank(series):
    """
    Identify blank / missing values.
    """
    s = series.astype(str).str.strip()
    return (
        s.eq("")
        | s.isin(["nan", "NaN", "None"])
        | series.isna()
    )
def existing(df, cols):
    """
    Return only columns that actually exist in the DataFrame.
    """
    return [c for c in cols if c in df.columns]
def table_columns(conn, table):
    """
    Return column names actually present in a SQLite table.
    """
    inspector = inspect(conn)
    return [
        column["name"]
        for column in inspector.get_columns(table)
   ]
def read_sql_as_str(conn, query):
    """
    Run a SQL query and return a DataFrame where:
    - NULL -> ""
    - every column -> string
    This reproduces the original CSV behavior:
        dtype=str
        keep_default_na=False
    """
    df = pd.read_sql_query(query, conn)
    df = df.fillna("")
    for col in df.columns:
        df[col] = df[col].astype(str)
    return df
# ============================================================================
# REGULAR EXPRESSIONS
# ============================================================================
# NPI = exactly 10 digits
NPI_RE = re.compile(r"^\d{10}$")
# ICD-10-CM format
ICD10_RE = re.compile(
    r"^[A-Z][0-9][0-9A-Z](\\.?[0-9A-Z]{0,4})?$",
    re.IGNORECASE
)
# ICD-9-CM format
ICD9_RE = re.compile(
    r"^(\d{3}(\\.\d{1,2})?|[EV]\d{2,3}(\\.\d{1,2})?)$",
    re.IGNORECASE
)
# HCPCS = 5 alphanumeric characters
HCPCS_RE = re.compile(r"^[A-Z0-9]{5}$")
# Beneficiary STATE_CODE = 2 numeric digits
SSA_STATE_RE = re.compile(r"^\d{2}$")
# Provider state can be:
#   AL
#   01
USPS_STATE_RE = re.compile(
    r"^([A-Z]{2}|\d{2})$"
)
# ============================================================================
# ICD VALIDATION
# ============================================================================
def valid_diag_code(code, version):
    """
    version:
        '0'  = ICD-10-CM
        '10' = ICD-10-CM
        '9'  = ICD-9-CM
    """
    if code is None or str(code).strip() == "":
        # Blank diagnosis is handled separately by the missing_\\\\\\\<col>
        # Correctness rule below, so it is treated as "not a format
        # violation" here.
        return True
    code = str(code).strip()
    v = str(version).strip()
    if v in ("0", "10"):
        return bool(ICD10_RE.match(code))
    if v == "9":
        return bool(ICD9_RE.match(code))
    # Unknown version:
    # don't falsely flag the record.
    return True
# ============================================================================
# INFER ICD VERSION FROM CLAIM DATE
# ============================================================================
def infer_icd_version_from_date(clm_from_dt_series):
    """
    Infer ICD-9 vs ICD-10 using CLM_FROM_DT.
    >= Oct 1, 2015 -> ICD-10
    <  Oct 1, 2015 -> ICD-9
    Missing / invalid dates -> pd.NA
    """
    dt = to_date(clm_from_dt_series)
    version = pd.Series(
        pd.NA,
        index=dt.index,
        dtype="object"
    )
    version.loc[
        dt.notna() & (dt >= ICD10_CUTOVER)
   ] = "0"
    version.loc[
        dt.notna() & (dt < ICD10_CUTOVER)
   ] = "9"
    return version
# ============================================================================
# UNIQUE RECORD IDENTIFICATION
# ============================================================================
def record_key_series(df, id_cols):
    # Prefer BENE_ID + CLM_ID + line number when available.
    cols = existing(df, id_cols)
    if cols:
        work = df[cols].astype(str).fillna("")
        return work.apply(
            lambda row: "|".join(f"{c}={row[c]}" for c in cols),
            axis=1,
        )
    return pd.Series(
        [f"__row__={i}" for i in df.index],
        index=df.index,
        dtype=str,
    )

# ============================================================================
# VIOLATION SINK
# ============================================================================
class ViolationSink:
    # Accumulates violation events and UNIQUE affected-record keys.
    # A record failing multiple rules counts once for affected_rows.
    def __init__(self):
        self.counts = defaultdict(int)
        self.unique_record_keys = defaultdict(set)
        self.dimension_record_keys = defaultdict(set)
        self.samples = defaultdict(list)
        self.actions = {}

    def add(
        self,
        file,
        dimension,
        rule,
        action,
        df_bad,
        id_cols,
        extra_cols=None
    ):
        if df_bad.empty:
            return

        key = (file, dimension, rule)
        keys = record_key_series(df_bad, id_cols).astype(str)

        self.unique_record_keys[key].update(keys.tolist())
        self.counts[key] = len(self.unique_record_keys[key])
        self.dimension_record_keys[(file, dimension)].update(keys.tolist())

        # Provider-level unique affected records.
        provider_col = provider_npi_column(file, df_bad)
        if file != "beneficiary_2025.csv" and provider_col is not None:
            provider_mask = ~is_blank(df_bad[provider_col])
            if provider_mask.any():
                provider_bad = df_bad.loc[provider_mask]
                provider_keys = record_key_series(provider_bad, id_cols)
                for idx in provider_bad.index:
                    npi = str(provider_bad.loc[idx, provider_col]).strip()
                    PROVIDER_DQ_RECORD_KEYS[
                        (file, npi, dimension)
                    ].add(str(provider_keys.loc[idx]))

                for npi in provider_bad[provider_col].astype(str).str.strip().unique():
                    provider_key = (file, str(npi), dimension)
                    PROVIDER_DQ_DIMENSION_COUNTS[provider_key] = len(
                        PROVIDER_DQ_RECORD_KEYS[provider_key]
                    )

        self.actions.setdefault(key, action)

        room = MAX_SAMPLES - len(self.samples[key])
        if room > 0:
            cols = existing(df_bad, id_cols + (extra_cols or []))
            samp = df_bad[cols].head(room).copy()
            samp.insert(0, "action", action)
            samp.insert(0, "rule", rule)
            samp.insert(0, "dimension", dimension)
            samp.insert(0, "file", file)
            self.samples[key].append(samp)

    def unique_rule_count(self, file, dimension, rule):
        return len(self.unique_record_keys[(file, dimension, rule)])

    def unique_dimension_count(self, file, dimension):
        return len(self.dimension_record_keys[(file, dimension)])

    def flush(self, out_dir):
        summary = []
        for (file, dim, rule), _ in self.counts.items():
            fname = (
                f"{file.replace('.csv', '')}__{dim}__{rule}.csv"
            ).replace(" ", "_").replace("/", "-")

            if self.samples[(file, dim, rule)]:
                pd.concat(
                    self.samples[(file, dim, rule)],
                    ignore_index=True
                ).to_csv(
                    os.path.join(out_dir, fname),
                    index=False
                )

            summary.append({
                "file": file,
                "dimension": dim,
                "rule": rule,
                "action": self.actions.get((file, dim, rule), ""),
                "violation_count": self.unique_rule_count(file, dim, rule),
                "sample_file": fname
            })

        with open(
            os.path.join(out_dir, "dq_summary.json"),
            "w"
        ) as f:
            json.dump(summary, f, indent=2)

        if summary:
            return pd.DataFrame(summary).sort_values(
                ["file", "dimension"]
            )
        return pd.DataFrame()

# ============================================================================
# GLOBAL VIOLATION SINK
# ============================================================================
SINK = ViolationSink()
# ============================================================================
# 0. LOAD ENROLLMENT MASTER
# ============================================================================
#
# Drives:
#   - Referential Integrity
#
# NOTE: This no longer feeds a Concordance check. It is still needed
#       for VALID_BENE_IDS, used by check_referential_integrity().
# ============================================================================
def load_enrollment_master(conn):
    wanted = [
        "BENE_ID",
        "STATE_CODE",
        "BENE_BIRTH_DT",
        "BENE_DEATH_DT",
        "BENE_ENROLLMT_REF_YR",
        "AGE_AT_END_REF_YR",
        "VALID_DEATH_DT_SW",
        "SEX_IDENT_CD",
        "BENE_RACE_CD",
        "BENE_HI_CVRAGE_TOT_MONS",
        "BENE_SMI_CVRAGE_TOT_MONS"
   ]
    cols = [
        c
        for c in wanted
        if c in table_columns(
            conn,
            "beneficiary"
        )
   ]
    if not cols:
        raise RuntimeError(
            "No expected columns found in SQLite table 'beneficiary'."
        )
    query = (
        f"SELECT {', '.join(cols)} "
        f"FROM beneficiary"
    )
    df = read_sql_as_str(
        conn,
        query
    )
    # Remove duplicate beneficiary IDs
    if "BENE_ID" in df.columns:
        df = df.drop_duplicates(
            subset=["BENE_ID"]
        )
    return df.reset_index(
        drop=True
    )
# ============================================================================
# 1. COMPLETENESS
# ============================================================================
#
# Required fields must not be missing.
# ============================================================================
CLAIM_REQUIRED = [
    "BENE_ID",
    "CLM_ID",
    "CLM_FROM_DT",
    "CLM_THRU_DT",
    "CLM_PMT_AMT"
]
def check_completeness(df, file):
    req = existing(
        df,
        CLAIM_REQUIRED
    )

    # ------------------------------------------------------------------------
    # PROVIDER-LEVEL COMPLETENESS (ADDITIONAL OUTPUT ONLY)
    # ------------------------------------------------------------------------
    # Group claim completeness by the provider NPI column defined for this
    # source file while preserving the existing dataset-level completeness
    # checks below exactly as they are.
    provider_npi_col = provider_npi_column(file, df)
    if provider_npi_col is not None:
        valid_provider_npi = ~is_blank(df[provider_npi_col])
        provider_npis = df.loc[valid_provider_npi, provider_npi_col].astype(str).str.strip()

        if not provider_npis.empty:
            provider_total_counts = provider_npis.value_counts()
            for npi, count in provider_total_counts.items():
                key = (file, str(npi))
                PROVIDER_COMPLETENESS_COUNTS[key]["total_rows"] += int(count)

            completeness_cols = existing(
                df,
                CLAIM_REQUIRED + NPI_FIELDS
            )

            provider_keys = [
                (file, str(npi))
                for npi in provider_total_counts.index
            ]

            for key in provider_keys:
                for col in completeness_cols:
                    PROVIDER_COMPLETENESS_COUNTS[key]["rules"].setdefault(
                        f"missing_{col}",
                        0
                    )

            for col in completeness_cols:
                bad_provider = valid_provider_npi & is_blank(df[col])
                if bad_provider.any():
                    bad = df.loc[bad_provider].copy()
                    bad_keys = record_key_series(
                        bad,
                        ["BENE_ID", "CLM_ID", "LINE_NUM", "CLM_LINE_NUM"]
                    )
                    for idx in bad.index:
                        npi = str(bad.loc[idx, provider_npi_col]).strip()
                        rule_key = (file, npi, f"missing_{col}")
                        PROVIDER_COMPLETENESS_RECORD_KEYS[rule_key].add(
                            str(bad_keys.loc[idx])
                        )
                    for npi in bad[provider_npi_col].astype(str).str.strip().unique():
                        key = (file, str(npi))
                        PROVIDER_COMPLETENESS_COUNTS[key]["rules"][
                            f"missing_{col}"
                        ] = len(
                            PROVIDER_COMPLETENESS_RECORD_KEYS[
                                (file, str(npi), f"missing_{col}")
                            ]
                        )

    for col in req:
        bad = df[
            is_blank(df[col])
       ]
        SINK.add(
            file,
            "Completeness",
            f"missing_{col}",
            "quarantine",
            bad,
            ["BENE_ID", "CLM_ID"],
            [col]
        )
    # ------------------------------------------------------------------------
    # NPI FIELDS
    # ------------------------------------------------------------------------
    #
    # A blank/null NPI is a completeness problem, not a correctness
    # (format) problem, so it is flagged here as missing_\\\\\\\<col>.
    # The format check for NPIs that ARE present still lives in
    # check_correctness().
    # ------------------------------------------------------------------------
    for col in existing(
        df,
        NPI_FIELDS
    ):
        bad = df[
            is_blank(df[col])
       ]
        SINK.add(
            file,
            "Completeness",
            f"missing_{col}",
            "quarantine",
            bad,
            ["BENE_ID", "CLM_ID"],
            [col]
        )
def check_completeness_bene(df):
    req = [
        "BENE_ID",
        "STATE_CODE",
        "BENE_BIRTH_DT",
        "SEX_IDENT_CD",
        "BENE_ENROLLMT_REF_YR"
   ]
    for col in existing(df, req):
        bad = df[
            is_blank(df[col])
       ]
        SINK.add(
            "beneficiary_2025.csv",
            "Completeness",
            f"missing_{col}",
            "quarantine",
            bad,
            ["BENE_ID"],
            [col]
        )
# ============================================================================
# 2. CORRECTNESS
# ============================================================================
#
# Values must be valid / accurate, not merely present.
#
# Missing ICD diagnosis codes and missing HCPCS codes are flagged here too,
# as their own missing_\\\\\\\<col> rule under Correctness — separate from the
# invalid_diag_code_*/invalid_hcpcs_format format checks, which only run
# against codes that ARE present.
# ============================================================================
NPI_FIELDS = [
    "ORG_NPI_NUM",
    "AT_PHYSN_NPI",
    "OP_PHYSN_NPI",
    "OT_PHYSN_NPI",
    "RNDRNG_PHYSN_NPI",
    "RFR_PHYSN_NPI",
    "PRF_PHYSN_NPI",
    "CARR_CLM_BLG_NPI_NUM",
    "PRVDR_NPI"
]
def check_correctness(df, file):
    # ------------------------------------------------------------------------
    # NPI FORMAT
    # ------------------------------------------------------------------------
    for col in existing(
        df,
        NPI_FIELDS
    ):
        present = ~is_blank(
            df[col]
        )
        bad_fmt = (
            present
            &
            ~df[col]
            .astype(str)
            .str.strip()
            .str.match(NPI_RE)
        )
        SINK.add(
            file,
            "Correctness",
            f"invalid_npi_format_{col}",
            "quarantine",
            df[bad_fmt],
            ["BENE_ID", "CLM_ID"],
            [col]
        )
    # ------------------------------------------------------------------------
    # DIAGNOSIS CODES
    # ------------------------------------------------------------------------
    diag_pairs = []
    diag_code_cols_no_version = []
    for i in list(range(1, 26)) + [""]:
        suf = (
            ""
            if i == ""
            else str(i)
        )
        code_col = (
            f"ICD_DGNS_CD{suf}"
        )
        ver_col = (
            f"ICD_DGNS_VRSN_CD{suf}"
        )
        if suf == "":
            code_col = "PRNCPAL_DGNS_CD"
            ver_col = "PRNCPAL_DGNS_VRSN_CD"
        if (
            code_col in df.columns
            and ver_col in df.columns
        ):
            diag_pairs.append(
                (code_col, ver_col)
            )
        elif (
            code_col in df.columns
            and ver_col not in df.columns
        ):
            diag_code_cols_no_version.append(
                code_col
            )
    # ------------------------------------------------------------------------
    # MISSING DIAGNOSIS CODES (flagged as their own Correctness rule)
    # ------------------------------------------------------------------------
    all_diag_code_cols = (
        [code_col for code_col, _ in diag_pairs]
        + diag_code_cols_no_version
    )
    for code_col in all_diag_code_cols:
        missing = df[
            is_blank(df[code_col])
       ]
        SINK.add(
            file,
            "Correctness",
            f"missing_{code_col}",
            "quarantine",
            missing,
            ["BENE_ID", "CLM_ID"],
            [code_col]
        )
    # ------------------------------------------------------------------------
    # DIAGNOSIS WITH EXPLICIT VERSION
    # ------------------------------------------------------------------------
    for code_col, ver_col in diag_pairs:
        mask = ~df.apply(
            lambda r:
                valid_diag_code(
                    r[code_col],
                    r[ver_col]
                ),
            axis=1
        )
        SINK.add(
            file,
            "Correctness",
            f"invalid_diag_code_{code_col}",
            "quarantine",
            df[mask],
            ["BENE_ID", "CLM_ID"],
            [code_col, ver_col]
        )
    # ------------------------------------------------------------------------
    # DIAGNOSIS WITHOUT VERSION
    # ------------------------------------------------------------------------
    if (
        diag_code_cols_no_version
        and "CLM_FROM_DT" in df.columns
    ):
        inferred_ver = (
            infer_icd_version_from_date(
                df["CLM_FROM_DT"]
            )
        )
        for code_col in diag_code_cols_no_version:
            codes = df[code_col]
            checkable = (
                inferred_ver.notna()
                &
                ~is_blank(codes)
            )
            if not checkable.any():
                continue
            valid_mask = pd.Series(
                True,
                index=df.index
            )
            valid_mask.loc[checkable] = [
                valid_diag_code(
                    c,
                    v
                )
                for c, v in zip(
                    codes[checkable],
                    inferred_ver[checkable]
                )
           ]
            bad_mask = (
                checkable
                &
                ~valid_mask
            )
            if not bad_mask.any():
                continue
            bad = df.loc[
                bad_mask
           ].copy()
            bad[
                "_INFERRED_ICD_VRSN"
           ] = inferred_ver[
                bad_mask
           ]
            SINK.add(
                file,
                "Correctness",
                f"invalid_diag_code_inferred_{code_col}",
                "flag_for_review_inferred_version",
                bad,
                ["BENE_ID", "CLM_ID"],
                [
                    code_col,
                    "CLM_FROM_DT",
                    "_INFERRED_ICD_VRSN"
               ]
            )
    # ------------------------------------------------------------------------
    # HCPCS
    # ------------------------------------------------------------------------
    if "HCPCS_CD" in df.columns:
        present = ~is_blank(
            df["HCPCS_CD"]
        )
        # Missing HCPCS -> its own Correctness rule.
        SINK.add(
            file,
            "Correctness",
            "missing_HCPCS_CD",
            "quarantine",
            df[~present],
            ["BENE_ID", "CLM_ID"],
            ["HCPCS_CD"]
        )
        # Present but malformed HCPCS -> format rule (unchanged).
        bad = (
            present
            &
            ~df["HCPCS_CD"]
            .astype(str)
            .str.strip()
            .str.match(HCPCS_RE)
        )
        SINK.add(
            file,
            "Correctness",
            "invalid_hcpcs_format",
            "quarantine",
            df[bad],
            ["BENE_ID", "CLM_ID"],
            ["HCPCS_CD"]
        )
def check_correctness_bene(df):
    # ------------------------------------------------------------------------
    # SEX
    # ------------------------------------------------------------------------
    if "SEX_IDENT_CD" in df.columns:
        bad = ~df[
            "SEX_IDENT_CD"
       ].astype(str).str.strip().isin(
            ["0", "1", "2"]
        )
        SINK.add(
            "beneficiary_2025.csv",
            "Correctness",
            "invalid_sex_code",
            "quarantine",
            df[bad],
            ["BENE_ID"],
            ["SEX_IDENT_CD"]
        )
    # ------------------------------------------------------------------------
    # STATE
    # ------------------------------------------------------------------------
    if "STATE_CODE" in df.columns:
        bad = (
            ~df["STATE_CODE"]
            .astype(str)
            .str.strip()
            .str.match(SSA_STATE_RE)
        )
        SINK.add(
            "beneficiary_2025.csv",
            "Correctness",
            "invalid_state_code",
            "quarantine",
            df[bad],
            ["BENE_ID"],
            ["STATE_CODE"]
        )
# ============================================================================
# 3. REFERENTIAL INTEGRITY
# ============================================================================
#
# Foreign keys must exist in the beneficiary master.
# ============================================================================
def check_referential_integrity(df, file):
    if "BENE_ID" in df.columns:
        bad = df[
            ~df["BENE_ID"].isin(
                VALID_BENE_IDS
            )
            &
            ~is_blank(
                df["BENE_ID"]
            )
       ]
        SINK.add(
            file,
            "Referential Integrity",
            "bene_id_not_in_enrollment",
            "route_to_data_exception_queue",
            bad,
            ["BENE_ID", "CLM_ID"]
        )
    # ------------------------------------------------------------------------
    # DUPLICATE CLAIM LINE KEY
    # ------------------------------------------------------------------------
    line_col = next(
        (
            c
            for c in [
                "LINE_NUM",
                "CLM_LINE_NUM"
           ]
            if c in df.columns
        ),
        None
    )
    if "CLM_ID" in df.columns:
        key_cols = (
            ["BENE_ID", "CLM_ID"]
            +
            ([line_col] if line_col else [])
        )
        dup_mask = df.duplicated(
            subset=key_cols,
            keep=False
        )
        SINK.add(
            file,
            "Referential Integrity",
            "duplicate_claim_line_key",
            "quarantine_pend_before_payment",
            df[dup_mask],
            key_cols
        )
# ============================================================================
# 4. PLAUSIBILITY
# ============================================================================
#
# Values should make logical / clinical sense.
# ============================================================================
DATE_PAIRS = [
    (
        "CLM_FROM_DT",
        "CLM_THRU_DT"
    ),
    (
        "CLM_ADMSN_DT",
        "NCH_BENE_DSCHRG_DT"
    )
]
AMOUNT_FIELDS = [
    "CLM_PMT_AMT",
    "CLM_TOT_CHRG_AMT",
    "NCH_CLM_BENE_PMT_AMT",
    "LINE_NCH_PMT_AMT",
    "REV_CNTR_PMT_AMT_AMT",
    "REV_CNTR_TOT_CHRG_AMT"
]
UNIT_FIELDS = [
    "LINE_SRVC_CNT",
    "REV_CNTR_UNIT_CNT"
]
def check_plausibility(df, file):
    # ------------------------------------------------------------------------
    # DATE ORDER
    # ------------------------------------------------------------------------
    for f_col, t_col in DATE_PAIRS:
        if (
            f_col in df.columns
            and t_col in df.columns
        ):
            fdt = to_date(
                df[f_col]
            )
            tdt = to_date(
                df[t_col]
            )
            bad = df[
                fdt.notna()
                &
                tdt.notna()
                &
                (tdt < fdt)
           ]
            SINK.add(
                file,
                "Plausibility",
                f"{t_col}_before_{f_col}",
                "quarantine",
                bad,
                ["BENE_ID", "CLM_ID"],
                [f_col, t_col]
            )
        elif f_col in df.columns:
            malformed = df[
                ~is_blank(
                    df[f_col]
                )
                &
                to_date(
                    df[f_col]
                ).isna()
           ]
            SINK.add(
                file,
                "Plausibility",
                f"malformed_date_{f_col}",
                "quarantine",
                malformed,
                ["BENE_ID", "CLM_ID"],
                [f_col]
            )
    # ------------------------------------------------------------------------
    # NEGATIVE AMOUNTS
    # ------------------------------------------------------------------------
    for col in existing(
        df,
        AMOUNT_FIELDS
    ):
        vals = pd.to_numeric(
            df[col],
            errors="coerce"
        )
        bad = df[
            vals.notna()
            &
            (vals < 0)
       ]
        SINK.add(
            file,
            "Plausibility",
            f"negative_amount_{col}",
            "flag_for_review",
            bad,
            ["BENE_ID", "CLM_ID"],
            [col]
        )
    # ------------------------------------------------------------------------
    # NON-POSITIVE SERVICE UNITS
    # ------------------------------------------------------------------------
    for col in existing(
        df,
        UNIT_FIELDS
    ):
        vals = pd.to_numeric(
            df[col],
            errors="coerce"
        )
        bad = df[
            vals.notna()
            &
            (vals <= 0)
       ]
        SINK.add(
            file,
            "Plausibility",
            f"non_positive_units_{col}",
            "quarantine",
            bad,
            ["BENE_ID", "CLM_ID"],
            [col]
        )
    # ------------------------------------------------------------------------
    # UTILIZATION / LENGTH OF STAY
    # ------------------------------------------------------------------------
    if "CLM_UTLZTN_DAY_CNT" in df.columns:
        vals = pd.to_numeric(
            df[
                "CLM_UTLZTN_DAY_CNT"
           ],
            errors="coerce"
        )
        bad = df[
            vals.notna()
            &
            (
                (vals < 0)
                |
                (vals > 365)
            )
       ]
        SINK.add(
            file,
            "Plausibility",
            "implausible_utilization_days",
            "flag_for_review",
            bad,
            ["BENE_ID", "CLM_ID"],
            ["CLM_UTLZTN_DAY_CNT"]
        )
def check_plausibility_bene(df):
    # ------------------------------------------------------------------------
    # AGE
    # ------------------------------------------------------------------------
    if "AGE_AT_END_REF_YR" in df.columns:
        vals = pd.to_numeric(
            df[
                "AGE_AT_END_REF_YR"
           ],
            errors="coerce"
        )
        bad = df[
            vals.notna()
            &
            (
                (vals < 0)
                |
                (vals > 115)
            )
       ]
        SINK.add(
            "beneficiary_2025.csv",
            "Plausibility",
            "implausible_age",
            "quarantine",
            bad,
            ["BENE_ID"],
            ["AGE_AT_END_REF_YR"]
        )
    # ------------------------------------------------------------------------
    # BIRTH DATE
    # ------------------------------------------------------------------------
    if "BENE_BIRTH_DT" in df.columns:
        bd = to_date(
            df["BENE_BIRTH_DT"]
        )
        malformed = df[
            ~is_blank(
                df["BENE_BIRTH_DT"]
            )
            &
            bd.isna()
       ]
        SINK.add(
            "beneficiary_2025.csv",
            "Plausibility",
            "malformed_birth_date",
            "quarantine",
            malformed,
            ["BENE_ID"],
            ["BENE_BIRTH_DT"]
        )
        future = df[
            bd.notna()
            &
            (bd > TODAY)
       ]
        SINK.add(
            "beneficiary_2025.csv",
            "Plausibility",
            "birth_date_in_future",
            "quarantine",
            future,
            ["BENE_ID"],
            ["BENE_BIRTH_DT"]
        )
    # ------------------------------------------------------------------------
    # DEATH BEFORE BIRTH
    # ------------------------------------------------------------------------
    if (
        "BENE_DEATH_DT" in df.columns
        and "BENE_BIRTH_DT" in df.columns
    ):
        dd = to_date(
            df["BENE_DEATH_DT"]
        )
        bd = to_date(
            df["BENE_BIRTH_DT"]
        )
        bad = df[
            dd.notna()
            &
            bd.notna()
            &
            (dd < bd)
       ]
        SINK.add(
            "beneficiary_2025.csv",
            "Plausibility",
            "death_before_birth",
            "quarantine",
            bad,
            ["BENE_ID"],
            [
                "BENE_BIRTH_DT",
                "BENE_DEATH_DT"
           ]
        )
# ============================================================================
# 5. INTERNAL CONSISTENCY
# ============================================================================
#
# Claim must balance against its line items.
# ============================================================================
LINE_TO_HEADER = {
    # carrier / dme
    "LINE_NCH_PMT_AMT": (
        "CLM_PMT_AMT",
        1.00
    ),
    # hha / outpatient / snf style
    "REV_CNTR_PMT_AMT_AMT": (
        "CLM_PMT_AMT",
        1.00
    )
}
# Carry rows across chunk boundaries.
_carry = {}
def check_internal_consistency(df, file):
    line_col = None
    header_col = None
    tol = None
    for lc, (hc, t) in LINE_TO_HEADER.items():
        if (
            lc in df.columns
            and hc in df.columns
        ):
            line_col = lc
            header_col = hc
            tol = t
            break
    if (
        line_col is None
        or "CLM_ID" not in df.columns
    ):
        return
    # ------------------------------------------------------------------------
    # HANDLE CHUNK BOUNDARY
    # ------------------------------------------------------------------------
    work = df
    if file in _carry:
        work = pd.concat(
            [
                _carry[file],
                df
           ],
            ignore_index=True
        )
    # Keep the last claim's rows.
    # They may continue into the next chunk.
    if work.empty:
        return
    last_id = work[
        "CLM_ID"
   ].iloc[-1]
    _carry[file] = work[
        work["CLM_ID"] == last_id
   ]
    work = work[
        work["CLM_ID"] != last_id
   ]
    if work.empty:
        return
    # ------------------------------------------------------------------------
    # CALCULATE LINE SUM VS HEADER AMOUNT
    # ------------------------------------------------------------------------
    work = work.copy()
    work["_line_amt"] = (
        pd.to_numeric(
            work[line_col],
            errors="coerce"
        )
        .fillna(0)
    )
    work["_hdr_amt"] = pd.to_numeric(
        work[header_col],
        errors="coerce"
    )
    agg = (
        work.groupby("CLM_ID")
        .agg(
            line_sum=(
                "_line_amt",
                "sum"
            ),
            hdr_amt=(
                "_hdr_amt",
                "first"
            ),
            bene_id=(
                "BENE_ID",
                "first"
            )
        )
        .reset_index()
    )
    bad = agg[
        agg["hdr_amt"].notna()
        &
        (
            (
                agg["line_sum"]
                -
                agg["hdr_amt"]
            ).abs()
            > tol
        )
   ]
    SINK.add(
        file,
        "Internal Consistency",
        f"header_{header_col}_ne_sum_{line_col}",
        "pend_before_payment",
        bad,
        ["bene_id", "CLM_ID"],
        [
            "hdr_amt",
            "line_sum"
       ]
    )
    # ------------------------------------------------------------------------
    # PAYMENT CANNOT EXCEED TOTAL CHARGE
    # ------------------------------------------------------------------------
    if (
        "CLM_TOT_CHRG_AMT" in df.columns
        and "CLM_PMT_AMT" in df.columns
    ):
        chg = pd.to_numeric(
            df["CLM_TOT_CHRG_AMT"],
            errors="coerce"
        )
        pmt = pd.to_numeric(
            df["CLM_PMT_AMT"],
            errors="coerce"
        )
        bad2 = df[
            chg.notna()
            &
            pmt.notna()
            &
            (pmt > chg + tol)
       ]
        SINK.add(
            file,
            "Internal Consistency",
            "payment_exceeds_total_charge",
            "flag_for_review",
            bad2,
            ["BENE_ID", "CLM_ID"],
            [
                "CLM_TOT_CHRG_AMT",
                "CLM_PMT_AMT"
           ]
        )
    # ------------------------------------------------------------------------
    # ADMISSION <= FROM <= THRU <= DISCHARGE
    # ------------------------------------------------------------------------
    required = [
        "CLM_ADMSN_DT",
        "CLM_FROM_DT",
        "CLM_THRU_DT",
        "NCH_BENE_DSCHRG_DT"
   ]
    if all(
        c in df.columns
        for c in required
    ):
        adm = to_date(
            df["CLM_ADMSN_DT"]
        )
        frm = to_date(
            df["CLM_FROM_DT"]
        )
        thr = to_date(
            df["CLM_THRU_DT"]
        )
        dis = to_date(
            df["NCH_BENE_DSCHRG_DT"]
        )
        ok_mask = (
            adm.notna()
            &
            frm.notna()
            &
            thr.notna()
            &
            dis.notna()
        )
        bad3 = df[
            ok_mask
            &
            ~(
                (adm <= frm)
                &
                (frm <= thr)
                &
                (thr <= dis)
            )
       ]
        SINK.add(
            file,
            "Internal Consistency",
            "date_sequence_violation",
            "quarantine",
            bad3,
            ["BENE_ID", "CLM_ID"],
            required
        )
def flush_internal_consistency_carry():
    """
    Process remaining rows after the final chunk.
    """
    for file, work in list(
        _carry.items()
    ):
        if work.empty:
            continue
        line_col = None
        header_col = None
        tol = None
        for lc, (hc, t) in LINE_TO_HEADER.items():
            if (
                lc in work.columns
                and hc in work.columns
            ):
                line_col = lc
                header_col = hc
                tol = t
                break
        if line_col is None:
            continue
        w = work.copy()
        w["_line_amt"] = (
            pd.to_numeric(
                w[line_col],
                errors="coerce"
            )
            .fillna(0)
        )
        w["_hdr_amt"] = pd.to_numeric(
            w[header_col],
            errors="coerce"
        )
        agg = (
            w.groupby("CLM_ID")
            .agg(
                line_sum=(
                    "_line_amt",
                    "sum"
                ),
                hdr_amt=(
                    "_hdr_amt",
                    "first"
                ),
                bene_id=(
                    "BENE_ID",
                    "first"
                )
            )
            .reset_index()
        )
        bad = agg[
            agg["hdr_amt"].notna()
            &
            (
                (
                    agg["line_sum"]
                    -
                    agg["hdr_amt"]
                ).abs()
                > tol
            )
       ]
        SINK.add(
            file,
            "Internal Consistency",
            f"header_{header_col}_ne_sum_{line_col}",
            "pend_before_payment",
            bad,
            ["bene_id", "CLM_ID"],
            [
                "hdr_amt",
                "line_sum"
           ]
        )
    _carry.clear()
# ============================================================================
# 6. CONFORMANCE / STANDARDIZATION
# ============================================================================
#
# Approved code sets and formats.
# ============================================================================
VALID_DIAG_VERSIONS = {
    "0",
    "9",
    "10",
    ""
}
def check_conformance(df, file):
    # ------------------------------------------------------------------------
    # DIAGNOSIS VERSION
    # ------------------------------------------------------------------------
    for i in list(range(1, 26)) + [""]:
        suf = (
            ""
            if i == ""
            else str(i)
        )
        if suf == "":
            ver_col = (
                "PRNCPAL_DGNS_VRSN_CD"
            )
        else:
            ver_col = (
                f"ICD_DGNS_VRSN_CD{suf}"
            )
        if ver_col in df.columns:
            bad = df[
                ~df[ver_col]
                .astype(str)
                .str.strip()
                .isin(
                    VALID_DIAG_VERSIONS
                )
           ]
            SINK.add(
                file,
                "Conformance",
                f"invalid_diag_version_{ver_col}",
                "quarantine",
                bad,
                ["BENE_ID", "CLM_ID"],
                [ver_col]
            )
    # ------------------------------------------------------------------------
    # DATE FORMAT
    # ------------------------------------------------------------------------
    date_like = [
        c
        for c in df.columns
        if (
            c.endswith("_DT")
            or c.endswith("_DT_ID")
        )
   ]
    for col in date_like:
        present = ~is_blank(
            df[col]
        )
        bad = (
            present
            &
            to_date(
                df[col]
            ).isna()
        )
        SINK.add(
            file,
            "Conformance",
            f"nonstandard_date_format_{col}",
            "quarantine",
            df[bad],
            ["BENE_ID", "CLM_ID"],
            [col]
        )
    # ------------------------------------------------------------------------
    # PROVIDER STATE
    # ------------------------------------------------------------------------
    if "PRVDR_STATE_CD" in df.columns:
        present = ~is_blank(
            df["PRVDR_STATE_CD"]
        )
        bad = (
            present
            &
            ~df[
                "PRVDR_STATE_CD"
           ]
            .astype(str)
            .str.strip()
            .str.upper()
            .str.match(
                USPS_STATE_RE
            )
        )
        SINK.add(
            file,
            "Conformance",
            "nonstandard_state_code",
            "quarantine",
            df[bad],
            ["BENE_ID", "CLM_ID"],
            ["PRVDR_STATE_CD"]
        )
# ============================================================================
# ORCHESTRATOR
# ============================================================================
def run_on_dataframe(df, file):
    # ------------------------------------------------------------------------
    # PROVIDER-LEVEL DQ TRACKING (ADDITIONAL OUTPUT ONLY)
    # ------------------------------------------------------------------------
    # Use the provider NPI column defined for this source file. Existing DQ
    # rule execution below is unchanged.
    provider_npi_col = provider_npi_column(file, df)
    if file != "beneficiary_2025.csv" and provider_npi_col is not None:
        provider_mask = ~is_blank(df[provider_npi_col])
        if provider_mask.any():
            provider_counts = (
                df.loc[provider_mask, provider_npi_col]
                .astype(str)
                .str.strip()
                .value_counts()
            )
            for npi, count in provider_counts.items():
                PROVIDER_DQ_TOTAL_ROWS[(file, str(npi))] += int(count)

    check_completeness(
        df,
        file
    )
    check_correctness(
        df,
        file
    )
    check_referential_integrity(
        df,
        file
    )
    check_plausibility(
        df,
        file
    )
    check_internal_consistency(
        df,
        file
    )
    check_conformance(
        df,
        file
    )
# ============================================================================
# RUN CLAIM TABLES
# ============================================================================
def run_claims(
    conn,
    tables=CLAIM_TABLES,
    chunksize=CHUNKSIZE
):
    for table in tables:
        file = f"{table}.csv"
        print(
            f"\nProcessing {table} ..."
        )
        # Order rows by CLM_ID, LINE_NUM so that all lines belonging to
        # the same claim stay contiguous and in a stable order across
        # chunk boundaries. This matters for the internal-consistency
        # chunk-carry logic above, which assumes a claim's rows are not
        # split apart by an arbitrary read order.
        cols = table_columns(conn, table)
        line_col = next(
            (c for c in ["LINE_NUM", "CLM_LINE_NUM"] if c in cols),
            None
        )
        order_cols = ["CLM_ID"] + ([line_col] if line_col else [])
        if "CLM_ID" in cols:
            query = (
                f"SELECT * FROM `{table}` "
                f"ORDER BY {', '.join(order_cols)}"
            )
        else:
            query = f"SELECT * FROM `{table}`"
        # Pandas reads directly from SQLite.
        reader = pd.read_sql_query(
            query,
            conn,
            chunksize=chunksize
        )
        row_count = 0
        for i, chunk in enumerate(reader):
            chunk = chunk.fillna("")
            for col in chunk.columns:
                chunk[col] = (
                    chunk[col]
                    .astype(str)
                )
            run_on_dataframe(
                chunk,
                file
            )
            row_count += len(chunk)
            print(
                f"  chunk {i + 1} "
                f"({len(chunk):,} rows) done"
            )
        print(
            f"  Total rows processed: "
            f"{row_count:,}"
        )
        # Record the total row count for this file so it can be used
        # later to compute affected_pct / pass-fail counts when persisting
        # results. This is bookkeeping only — it does not affect any rule.
        TABLE_ROW_COUNTS[file] = row_count
    # Process remaining claim
    # rows after final chunk.
    flush_internal_consistency_carry()
# ============================================================================
# RUN BENEFICIARY TABLE
# ============================================================================
def run_beneficiary(conn):
    print(
        "\nProcessing beneficiary ..."
    )
    df = read_sql_as_str(
        conn,
        "SELECT * FROM `beneficiary`"
    )
    check_completeness_bene(
        df
    )
    check_correctness_bene(
        df
    )
    check_plausibility_bene(
        df
    )
    # ------------------------------------------------------------------------
    # DUPLICATE BENEFICIARY ID
    # ------------------------------------------------------------------------
    if "BENE_ID" in df.columns:
        dup = df[
            df.duplicated(
                subset=["BENE_ID"],
                keep=False
            )
       ]
        SINK.add(
            "beneficiary_2025.csv",
            "Referential Integrity",
            "duplicate_bene_id",
            "quarantine",
            dup,
            ["BENE_ID"]
        )
    # Record row count for beneficiary, same purpose as TABLE_ROW_COUNTS
    # above for claim tables.
    TABLE_ROW_COUNTS["beneficiary_2025.csv"] = len(df)
# ============================================================================
# CREATE DATA QUALITY TABLE IN claim_dagster.db
# ============================================================================
# IMPORTANT:
#
# The DQ engine/rule logic above is NOT changed.
# Only the persistence layer is changed so that ALL output is stored in:
#
#     claim_dagster.db
#         └── dq_run_output
#
# The single table contains:
#   1. Dagster execution information
#   2. DQ rule/violation information
#   3. DQ summary information
#
# No separate dq_results, dq_dimension_weights, or dq_weighted_scores tables are
# created by this version. Weighted scores are appended to dq_run_output.
# ============================================================================
def create_dq_tables_sqlite():
    """
    Create the single Data Quality output table in claim_dagster.db.
    Table:
        dq_run_output
    Existing data is preserved because IF NOT EXISTS is used.
    """
    create_sql = """
        CREATE TABLE IF NOT EXISTS dq_run_output (
            -- ============================================================
            -- DAGSTER / PIPELINE EXECUTION INFORMATION
            -- ============================================================
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            step_name TEXT,
            status TEXT,
            started_at DATETIME,
            completed_at DATETIME,
            duration_seconds REAL,
            records_processed INTEGER,
            dataset_name TEXT,
            batch_id TEXT,
            error_message TEXT,
            -- ============================================================
            -- DATA QUALITY RULE INFORMATION
            -- ============================================================
            dimension TEXT,
            field_name TEXT,
            rule_name TEXT,
            affected_rows INTEGER,
            affected_pct REAL,
            severity TEXT,
            message TEXT,
            -- ============================================================
            -- DATA QUALITY SUMMARY INFORMATION
            -- ============================================================
            total_records INTEGER,
            passed_records INTEGER,
            failed_records INTEGER,
            total_rules_checked INTEGER,
            total_violations INTEGER,
            critical_count INTEGER,
            high_count INTEGER,
            warning_count INTEGER,
            info_count INTEGER,
            quality_score REAL,
            overall_status TEXT,
            -- ============================================================
            -- ROOT CAUSE AND RECOMMENDATION
            -- ============================================================
            root_cause TEXT,
            recommendation TEXT,
            -- ============================================================
            -- PROVIDER-LEVEL COMPLETENESS INFORMATION
            -- ============================================================
            npi TEXT,
            npi_total_rows INTEGER,
            npi_affected_rows INTEGER,
            npi_affected_pct REAL,
            npi_completeness_score REAL,
            -- ============================================================
            -- FINAL DQ QUALITY SCORE
            -- ============================================================
            created_at DATETIME
        )
    """
    print("\n" + "=" * 80)
    print("CREATING CLAIMCARE DQ DATABASE")
    print("=" * 80)
    print(f"SQLite DB : {DQ_SQLITE_DATABASE}")
    print("Table     : dq_run_output")
    with DQ_SQLITE_ENGINE.begin() as conn:
        conn.exec_driver_sql(create_sql)
        # Safely upgrade an existing dq_run_output table created by the
        # previous version. This avoids "no such column" errors when the
        # database already exists.
        existing_columns = {
            row[1]
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(dq_run_output)"
            ).fetchall()
        }
        new_columns = {
            "quality_score": "REAL",
            "root_cause": "TEXT",
            "recommendation": "TEXT",
            "npi": "TEXT",
            "npi_total_rows": "INTEGER",
            "npi_affected_rows": "INTEGER",
            "npi_affected_pct": "REAL",
            "npi_completeness_score": "REAL",
            "npi_dimension_score": "REAL",
        }
        for column_name, column_type in new_columns.items():
            if column_name not in existing_columns:
                conn.exec_driver_sql(
                    f"ALTER TABLE dq_run_output ADD COLUMN "
                    f"{column_name} {column_type}"
                )
        # Remove obsolete weighted-detail columns from an older database.
        # The final database stores only quality_score; weighted details are
        # used internally to calculate that score and are not persisted.
        obsolete_columns = [
            "dimension_weight",
            "dimension_score",
            "weighted_contribution",
            "weighted_quality_score_10",
            "weighted_risk_score_10",
       ]
        for column_name in obsolete_columns:
            if column_name in existing_columns:
                conn.exec_driver_sql(
                    f"ALTER TABLE dq_run_output DROP COLUMN {column_name}"
                )
    inspector = inspect(DQ_SQLITE_ENGINE)
    available = set(inspector.get_table_names())
    if "dq_run_output" not in available:
        raise RuntimeError(
            "Failed to create SQLite table: dq_run_output"
        )
    print("\n" + "=" * 80)
    print("CLAIMCARE DQ TABLE READY")
    print("=" * 80)
    print(f"✓ Database : {DQ_SQLITE_DATABASE}")
    print("✓ Table    : dq_run_output")
    # Display only the expected table. This is useful in VS Code/SQLite Viewer.
    print("\nSQLite tables:")
    for table_name in sorted(available):
        print(f"  - {table_name}")
    print("=" * 80)
# ============================================================================
# PERSISTENCE LAYER — writes ALL pipeline/DQ results into ONE SQLite table
# ============================================================================
BATCH_ID = TODAY.strftime("%Y%m%d")
# Map each Dagster run_id to the unique batch_id created for that run,
# so every execution is identifiable as its own batch in dq_run_output.
RUN_BATCH_IDS = {}
# Track the actual start time of each Dagster run so stored DQ rows have
# the true run start/end timestamps instead of NULL.
RUN_START_TIMES = {}
def resolve_batch_id(run_id):
    """Return the unique batch_id created for this Dagster run."""
    return RUN_BATCH_IDS.get(run_id, BATCH_ID)
# Maps the remediation `action` recorded by each rule to a severity bucket.
# This is reporting only and DOES NOT change any DQ rule logic.
ACTION_SEVERITY_MAP = {
    "quarantine": "critical",
    "quarantine_pend_before_payment": "critical",
    "route_to_data_exception_queue": "high",
    "pend_before_payment": "high",
    "flag_for_review": "warning",
    "flag_for_review_inferred_version": "warning",
}
# ============================================================================
# WEIGHTED DQ SCORE CONFIGURATION — ADDITIONAL OUTPUT ONLY
# ============================================================================
# These weights are applied AFTER all existing DQ rules have finished.
# No rule/check logic is changed.
#
# The six dimensions already implemented by this code are weighted as follows:
#   Completeness           = 0.20
#   Correctness            = 0.20
#   Referential Integrity  = 0.15
#   Plausibility           = 0.15
#   Internal Consistency   = 0.15
#   Conformance            = 0.15
#
# Total = 1.00
#
# Dimension score is normalized to 0-1, then the weighted quality score is
# multiplied by 10 so the next SLA-risk layer receives a 0-10 score.
# ============================================================================
DIMENSION_WEIGHTS = {
    "Completeness": 0.20,
    "Correctness": 0.20,
    "Referential Integrity": 0.15,
    "Plausibility": 0.15,
    "Internal Consistency": 0.15,
    "Conformance": 0.15,
}
WEIGHT_TOTAL = round(sum(DIMENSION_WEIGHTS.values()), 10)
if WEIGHT_TOTAL != 1.0:
    raise ValueError(
        f"DQ dimension weights must total 1.0, but total={WEIGHT_TOTAL}"
    )
def timestamp_string(value=None):
    """Return timestamps in the requested YYYY-MM-DD HH\\:MM\\:SS format."""
    if value is None:
        value = datetime.now()
    return value.strftime("%Y-%m-%d %H:%M:%S")
def severity_for_action(action):
    return ACTION_SEVERITY_MAP.get(action, "info")
# ============================================================================
# ROOT CAUSE + RECOMMENDATION
# ============================================================================
# This layer explains an already-detected DQ failure. It does not change any
# of the existing DQ validation rules.
# ============================================================================
ROOT_CAUSE_RECOMMENDATION_MAP = {
    "missing": (
        "A required data value is missing from the affected field.",
        "Make the field mandatory during ingestion, validate it before downstream processing, "
        "and route incomplete records for correction."
    ),
    "invalid_npi": (
        "The provider NPI does not follow the expected format or reference validation.",
        "Validate the NPI format and verify it against the approved provider reference data."
    ),
    "npi": (
        "The provider NPI failed the configured provider-identification validation.",
        "Validate the NPI format and cross-check it against the provider reference data."
    ),
    "diag_code": (
        "The diagnosis code is missing, malformed, or outside the expected ICD coding standard.",
        "Validate diagnosis codes against the appropriate ICD reference set and correct invalid values."
    ),
    "icd": (
        "The diagnosis value does not satisfy the configured ICD format, version, or completeness rule.",
        "Validate the diagnosis code against the applicable ICD version and reference data."
    ),
    "hcpcs": (
        "The HCPCS procedure or service code is missing or does not conform to the expected format.",
        "Validate HCPCS completeness and format against the approved HCPCS reference set before processing."
    ),
    "bene_id": (
        "The beneficiary identifier is missing, duplicated, or cannot be linked to the enrollment master.",
        "Validate BENE_ID for completeness and uniqueness and cross-check it against the enrollment master."
    ),
    "duplicate": (
        "The affected claim or beneficiary key appears more than once in the source data.",
        "Apply duplicate-key validation during ingestion and quarantine or reconcile duplicate records."
    ),
    "negative": (
        "A numeric or monetary field contains an unexpected negative value.",
        "Validate the allowed numeric range and review or correct records containing unexpected negative values."
    ),
    "amount": (
        "A claim amount failed the configured financial consistency or plausibility check.",
        "Reconcile the affected financial fields and validate amount ranges before payment processing."
    ),
    "date": (
        "A date value is missing, malformed, out of range, or inconsistent with a related date.",
        "Standardize date formats and validate chronological relationships before downstream processing."
    ),
    "age": (
        "The beneficiary age or related demographic value falls outside the configured plausible range.",
        "Validate age against the beneficiary birth date and correct inconsistent demographic information."
    ),
    "state_code": (
        "The state code does not conform to the expected standard or approved value set.",
        "Validate the state code against the approved state-code reference values."
    ),
    "state": (
        "The state value does not conform to the configured state-code standard.",
        "Validate the state value against the approved state-code reference set."
    ),
    "sex": (
        "The beneficiary sex value is outside the configured approved code set.",
        "Validate the sex code against the approved beneficiary code set and correct invalid values."
    ),
    "utilization": (
        "The utilization or length-of-stay value falls outside the configured plausible range.",
        "Validate utilization values against the expected range and review outliers before processing."
    ),
    "payment": (
        "The claim payment value is inconsistent with another claim financial field.",
        "Reconcile payment, charge, and related financial fields before payment or downstream processing."
    ),
    "conformance": (
        "One or more values do not conform to the required data standard.",
        "Standardize the affected field against the approved format, code set, or reference standard."
    ),
}
def get_root_cause_and_recommendation(rule_name, dimension):
    """Return a deterministic explanation for an already-failed DQ rule."""
    rule_lower = str(rule_name or "").strip().lower()
    dimension = str(dimension or "").strip()
    # More specific patterns are checked first.
    ordered_patterns = [
        "invalid_npi", "npi", "bene_id", "duplicate",
        "diag_code", "icd", "hcpcs", "negative", "payment",
        "amount", "utilization", "state_code", "state", "sex",
        "date", "age", "missing", "conformance"
    ]
    for pattern in ordered_patterns:
        if pattern in rule_lower:
            return ROOT_CAUSE_RECOMMENDATION_MAP[pattern]
    # Fallback ensures a root cause and recommendation are still available
    # for a newly-added rule that is not yet in the mapping above.
    dimension_defaults = {
        "Completeness": (
            "A required data field is missing or incomplete.",
            "Validate mandatory fields during ingestion and route incomplete records for correction."
        ),
        "Correctness": (
            "A data value does not satisfy the expected format, code set, or business validation rule.",
            "Validate the affected field against the appropriate format, code set, or reference data."
        ),
        "Referential Integrity": (
            "A claim or beneficiary reference cannot be correctly linked to its corresponding master data.",
            "Validate the relationship against the corresponding master/reference table and correct unmatched records."
        ),
        "Plausibility": (
            "A value falls outside the configured logical or plausible range.",
            "Review the affected value and apply range validation during ingestion."
        ),
        "Internal Consistency": (
            "Related fields within the record contain inconsistent values.",
            "Reconcile the related fields and validate their business relationship before downstream processing."
        ),
        "Conformance": (
            "A value does not conform to the required data standard.",
            "Standardize the affected value against the approved format or reference standard."
        )
    }
    return dimension_defaults.get(
        dimension,
        (
            "A configured data-quality rule has failed.",
            "Review and correct the affected records before downstream processing."
        )
    )
def log_execution_step(
    run_id,
    step_name,
    status,
    started_at,
    completed_at,
    records_processed=None,
    dataset_name=None,
    batch_id=None,
    error_message=None
):
    """
    Insert one Dagster execution row into the SINGLE dq_run_output table.
    Execution rows use the Dagster fields. DQ-specific fields remain NULL
    for these rows.
    """
    duration_seconds = (
        (completed_at - started_at).total_seconds()
        if started_at and completed_at
        else None
    )
    row = {
        "run_id": run_id,
        "step_name": step_name,
        "status": status,
        "started_at": timestamp_string(started_at) if started_at else None,
        "completed_at": timestamp_string(completed_at) if completed_at else None,
        "duration_seconds": duration_seconds,
        "records_processed": records_processed,
        "dataset_name": dataset_name,
        "batch_id": batch_id or resolve_batch_id(run_id),
        "error_message": error_message,
        # DQ fields are intentionally NULL for execution-log rows.
        "dimension": None,
        "field_name": None,
        "rule_name": None,
        "affected_rows": None,
        "affected_pct": None,
        "severity": None,
        "message": None,
        "total_records": None,
        "passed_records": None,
        "failed_records": None,
        "total_rules_checked": None,
        "total_violations": None,
        "critical_count": None,
        "high_count": None,
        "warning_count": None,
        "info_count": None,
        "quality_score": None,
        "overall_status": None,
        "root_cause": None,
        "recommendation": None,
        "created_at": timestamp_string(),
    }
    pd.DataFrame([row]).to_sql(
        "dq_run_output",
        DQ_SQLITE_ENGINE,
        if_exists="append",
        index=False
    )
def _compute_file_summary(file, file_rules):
    """
    Computes the same per-file summary numbers as the existing DQ logic.
    This function only prepares reporting fields for storage. It does not
    change any rule/check logic.
    """
    total_records = TABLE_ROW_COUNTS.get(file, 0)
    total_rules_checked = len(file_rules)
    total_violations = (
        int(file_rules["violation_count"].sum())
        if not file_rules.empty
        else 0
    )
    severities = (
        file_rules["action"].apply(severity_for_action)
        if not file_rules.empty
        else pd.Series(dtype=str)
    )
    critical_count = int((severities == "critical").sum())
    high_count = int((severities == "high").sum())
    warning_count = int((severities == "warning").sum())
    info_count = int((severities == "info").sum())
    failed_records = (
        min(total_violations, total_records)
        if total_records
        else total_violations
    )
    passed_records = max(
        total_records - failed_records,
        0
    )
    quality_score = (
        round(
            (passed_records / total_records) * 100,
            2
        )
        if total_records
        else None
    )
    overall_status = (
        "PASS"
        if total_violations == 0
        else "FAIL"
    )
    return {
        "total_records": total_records,
        "passed_records": passed_records,
        "failed_records": failed_records,
        "total_rules_checked": total_rules_checked,
        "total_violations": total_violations,
        "critical_count": critical_count,
        "high_count": high_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "quality_score": quality_score,
        "overall_status": overall_status,
    }
def compute_weighted_scores(summary_df, started_at=None, completed_at=None, batch_id=None):
    """
    Compute the additional weighted DQ output for every dataset.
    This function does NOT alter any existing DQ rule result. It only reads
    the already-produced summary_df and calculates a normalized dimension
    score, weighted contribution, a final 0-10 quality score, and a 0-10
    risk score for the next SLA-risk layer.
    Dimension score:
        max(0, min(1, 1 - dimension_violations / total_records))
    Weighted quality score (0-10):
        sum(dimension_score * dimension_weight) * 10
    Weighted risk score (0-10):
        10 - weighted_quality_score_10
    """
    if summary_df is None:
        summary_df = pd.DataFrame()
    files = set(TABLE_ROW_COUNTS.keys())
    if not summary_df.empty and "file" in summary_df.columns:
        files |= set(summary_df["file"].dropna().astype(str))
    output_rows = []
    for file in sorted(files):
        total_records = int(TABLE_ROW_COUNTS.get(file, 0))
        if not summary_df.empty:
            file_rules = summary_df[
                summary_df["file"].astype(str) == str(file)
           ]
        else:
            file_rules = pd.DataFrame()
        dimension_scores = {}
        for dimension, weight in DIMENSION_WEIGHTS.items():
            if file_rules.empty:
                dim_violations = 0
            else:
                dim_rows = file_rules[
                    file_rules["dimension"].astype(str) == dimension
               ]
                if dim_rows.empty:
                    dim_violations = 0
                else:
                    # Union of unique records affected by any rule in this dimension.
                    dim_violations = SINK.unique_dimension_count(
                        file,
                        dimension
                    )
            if total_records > 0:
                dimension_score = max(
                    0.0,
                    min(
                        1.0,
                        1.0 - (dim_violations / total_records)
                    )
                )
            else:
                dimension_score = 1.0 if dim_violations == 0 else 0.0
            weighted_contribution = (
                dimension_score * weight
            )
            dimension_scores[dimension] = {
                "weight": weight,
                "violations": dim_violations,
                "score": dimension_score,
                "contribution": weighted_contribution,
            }
        weighted_quality_normalized = sum(
            item["contribution"]
            for item in dimension_scores.values()
        )
        weighted_quality_score_10 = round(
            weighted_quality_normalized * 10.0,
            4
        )
        weighted_risk_score_10 = round(
            10.0 - weighted_quality_score_10,
            4
        )
        generated_at = timestamp_string(completed_at) if completed_at else timestamp_string()
        run_started_text = timestamp_string(started_at) if started_at else None
        run_completed_text = timestamp_string(completed_at) if completed_at else generated_at
        run_duration = ((completed_at - started_at).total_seconds() if started_at and completed_at else None)
        # ---------------------------------------------------------------
        # One transparent row for EACH of the six dimensions.
        # ---------------------------------------------------------------
        for dimension, values in dimension_scores.items():
            output_rows.append({
                "run_id": None,
                "step_name": "weighted_dimension_score",
                "status": "SUCCESS",
                "started_at": run_started_text,
                "completed_at": run_completed_text,
                "duration_seconds": run_duration,
                "records_processed": total_records,
                "dataset_name": file,
                "batch_id": batch_id or BATCH_ID,
                "error_message": None,
                "dimension": dimension,
                "field_name": None,
                "rule_name": None,
                "affected_rows": values["violations"],
                "affected_pct": round(
                    (values["violations"] / total_records) * 100,
                    4
                ) if total_records else 0.0,
                "severity": "info",
                "message": (
                    f"Weight={values['weight']:.2f}; "
                    f"dimension_score={values['score']:.4f}; "
                    f"weighted_contribution={values['contribution']:.4f}"
                ),
                "total_records": total_records,
                "passed_records": None,
                "failed_records": None,
                "total_rules_checked": None,
                "total_violations": None,
                "critical_count": None,
                "high_count": None,
                "warning_count": None,
                "info_count": None,
                # quality_score is the FINAL weighted 0-10 score for the dataset.
                # The per-dimension 0-1 score remains in dimension_score.
                "quality_score": weighted_quality_score_10,
                "overall_status": "CALCULATED",
                "created_at": generated_at,
            })
        # ---------------------------------------------------------------
        # One final aggregate row for the next SLA-risk layer.
        # ---------------------------------------------------------------
        output_rows.append({
            "run_id": None,
            "step_name": "weighted_sla_score",
            "status": "SUCCESS",
            "started_at": run_started_text,
            "completed_at": run_completed_text,
            "duration_seconds": run_duration,
            "records_processed": total_records,
            "dataset_name": file,
            "batch_id": batch_id or BATCH_ID,
            "error_message": None,
            "dimension": "ALL_6_DIMENSIONS",
            "field_name": None,
            "rule_name": None,
            "affected_rows": None,
            "affected_pct": None,
            "severity": "info",
            "message": (
                "Weighted DQ quality score calculated from all 6 dimensions "
                "and normalized to a 0-10 scale for the SLA risk layer."
            ),
            "total_records": total_records,
            "passed_records": None,
            "failed_records": None,
            "total_rules_checked": None,
            "total_violations": None,
            "critical_count": None,
            "high_count": None,
            "warning_count": None,
            "info_count": None,
            "quality_score": weighted_quality_score_10,
            # This is an input to the next SLA-risk layer, so do not apply
            # an SLA threshold here. The next layer can use the 0-10 scores.
            "overall_status": "CALCULATED",
            "created_at": generated_at,
        })
    return pd.DataFrame(output_rows)
def write_weighted_scores(run_id, summary_df, started_at=None, completed_at=None):
    """Append weighted dimension + final SLA-risk scores to dq_run_output."""
    weighted_df = compute_weighted_scores(
        summary_df,
        started_at=started_at,
        completed_at=completed_at,
        batch_id=resolve_batch_id(run_id),
    )
    if weighted_df.empty:
        print("\n✓ No weighted DQ score rows to store.")
        return weighted_df
    weighted_df["run_id"] = run_id
    weighted_df.to_sql(
        "dq_run_output",
        DQ_SQLITE_ENGINE,
        if_exists="append",
        index=False
    )
    print(
        f"\n✓ {len(weighted_df):,} weighted score row(s) "
        "stored in dq_run_output"
    )
    # Print the final score that the next SLA-risk layer can consume.
    final_scores = weighted_df[
        weighted_df["step_name"] == "weighted_sla_score"
   ][[
        "dataset_name",
        "quality_score"
   ]]
    if not final_scores.empty:
        print("\nFinal DQ Quality Scores (0-10):")
        print(final_scores.to_string(index=False))
    return weighted_df
def build_provider_completeness_rows(run_id, started_at=None, completed_at=None):
    """
    Build provider-level Completeness output grouped by the file-specific provider NPI column.

    This is additional output only. Existing dataset-level DQ rows and all
    existing DQ rule logic remain unchanged.
    """
    if not PROVIDER_COMPLETENESS_COUNTS:
        return []

    created_at = timestamp_string(completed_at) if completed_at else timestamp_string()
    started_text = timestamp_string(started_at) if started_at else None
    completed_text = timestamp_string(completed_at) if completed_at else created_at
    run_duration = (
        (completed_at - started_at).total_seconds()
        if started_at and completed_at
        else None
    )

    provider_rows = []

    for (file, npi), values in sorted(PROVIDER_COMPLETENESS_COUNTS.items()):
        total_rows = int(values["total_rows"])
        rule_counts = values["rules"]

        # Only create provider-level Completeness rows for completeness rules
        # that apply to this source table. The total provider row count is the
        # denominator for every rule for that provider.
        for rule_name, affected_rows in sorted(rule_counts.items()):
            affected_rows = int(affected_rows)
            affected_pct = (
                round((affected_rows / total_rows) * 100, 4)
                if total_rows
                else 0.0
            )
            completeness_score = round(
                100.0 - affected_pct,
                4
            )

            action = "quarantine" if affected_rows > 0 else "info"
            severity = severity_for_action(action)

            root_cause, recommendation = get_root_cause_and_recommendation(
                rule_name=rule_name,
                dimension="Completeness"
            )

            provider_rows.append({
                # Execution/context fields
                "run_id": run_id,
                "step_name": "provider_completeness",
                "status": "SUCCESS" if affected_rows == 0 else "FAIL",
                "started_at": started_text,
                "completed_at": completed_text,
                "duration_seconds": run_duration,
                "records_processed": total_rows,
                "dataset_name": file,
                "batch_id": resolve_batch_id(run_id),
                "error_message": None,
                # DQ fields
                "dimension": "Completeness",
                "field_name": rule_name.replace("missing_", "", 1),
                "rule_name": rule_name,
                "affected_rows": affected_rows,
                "affected_pct": affected_pct,
                "severity": severity,
                "message": (
                    f"NPI {npi}: {affected_rows:,} row(s) out of "
                    f"{total_rows:,} are missing the required field "
                    f"'{rule_name.replace('missing_', '', 1)}'. "
                    f"Provider completeness = {completeness_score:.4f}%."
                ),
                "root_cause": root_cause if affected_rows > 0 else None,
                "recommendation": recommendation if affected_rows > 0 else None,
                # Summary fields at provider level
                "total_records": total_rows,
                "passed_records": max(total_rows - affected_rows, 0),
                "failed_records": affected_rows,
                "total_rules_checked": 1,
                "total_violations": affected_rows,
                "critical_count": 1 if affected_rows > 0 else 0,
                "high_count": 0,
                "warning_count": 0,
                "info_count": 1 if affected_rows == 0 else 0,
                # Keep the existing quality_score semantics unchanged.
                "quality_score": None,
                "overall_status": "PASS" if affected_rows == 0 else "FAIL",
                # New provider-level fields
                "npi": npi,
                "npi_total_rows": total_rows,
                "npi_affected_rows": affected_rows,
                "npi_affected_pct": affected_pct,
                "npi_completeness_score": completeness_score,
                "created_at": created_at,
            })

    return provider_rows

def build_provider_dimension_rows(run_id, started_at=None, completed_at=None):
    """
    Build provider-level DQ output for all six DQ dimensions, grouped by
    PRVDR_NPI.

    Existing DQ rule logic and existing dataset-level output are unchanged.
    The provider-level score follows the same normalized logic used by the
    existing weighted DQ calculation:
        dimension_score = max(0, 1 - affected_rows / total_rows)
    and is stored as a 0-100 percentage in npi_dimension_score.

    Completeness is already emitted by build_provider_completeness_rows(),
    so this function emits the remaining five dimensions to avoid duplicate
    provider-level Completeness rows.
    """
    if not PROVIDER_DQ_TOTAL_ROWS:
        return []

    created_at = (
        timestamp_string(completed_at)
        if completed_at
        else timestamp_string()
    )
    started_text = (
        timestamp_string(started_at)
        if started_at
        else None
    )
    completed_text = (
        timestamp_string(completed_at)
        if completed_at
        else created_at
    )
    run_duration = (
        (completed_at - started_at).total_seconds()
        if started_at and completed_at
        else None
    )

    dimensions = [
        "Correctness",
        "Referential Integrity",
        "Plausibility",
        "Internal Consistency",
        "Conformance",
    ]

    provider_rows = []

    for (file, npi), total_rows in sorted(
        PROVIDER_DQ_TOTAL_ROWS.items()
    ):
        total_rows = int(total_rows)

        for dimension in dimensions:
            affected_rows = len(
                PROVIDER_DQ_RECORD_KEYS.get(
                    (file, npi, dimension),
                    set()
                )
            )

            affected_pct = (
                round(
                    (affected_rows / total_rows) * 100,
                    4
                )
                if total_rows
                else 0.0
            )

            dimension_score = round(
                max(
                    0.0,
                    min(
                        100.0,
                        100.0 - affected_pct
                    )
                ),
                4
            )

            if affected_rows > 0:
                action = "quarantine"
                severity = severity_for_action(action)
                root_cause, recommendation = (
                    get_root_cause_and_recommendation(
                        rule_name=dimension,
                        dimension=dimension
                    )
                )
                status = "FAIL"
            else:
                action = "info"
                severity = "info"
                root_cause = None
                recommendation = None
                status = "SUCCESS"

            provider_rows.append({
                "run_id": run_id,
                "step_name": "provider_dq_dimension",
                "status": status,
                "started_at": started_text,
                "completed_at": completed_text,
                "duration_seconds": run_duration,
                "records_processed": total_rows,
                "dataset_name": file,
                "batch_id": resolve_batch_id(run_id),
                "error_message": None,

                "dimension": dimension,
                "field_name": None,
                "rule_name": None,
                "affected_rows": affected_rows,
                "affected_pct": affected_pct,
                "severity": severity,
                "message": (
                    f"NPI {npi}: {affected_rows:,} affected row(s) "
                    f"out of {total_rows:,} for {dimension}. "
                    f"Provider {dimension} score = "
                    f"{dimension_score:.4f}%."
                ),
                "root_cause": root_cause,
                "recommendation": recommendation,

                "total_records": total_rows,
                "passed_records": max(total_rows - affected_rows, 0),
                "failed_records": affected_rows,
                "total_rules_checked": None,
                "total_violations": affected_rows,
                "critical_count": 1 if affected_rows > 0 and severity == "critical" else 0,
                "high_count": 1 if affected_rows > 0 and severity == "high" else 0,
                "warning_count": 1 if affected_rows > 0 and severity == "warning" else 0,
                "info_count": 1 if affected_rows == 0 else 0,
                "quality_score": dimension_score,
                "overall_status": status,

                "npi": str(npi),
                "npi_total_rows": total_rows,
                "npi_affected_rows": affected_rows,
                "npi_affected_pct": affected_pct,
                "npi_completeness_score": (
                    dimension_score
                    if dimension == "Completeness"
                    else None
                ),
                "npi_dimension_score": dimension_score,
                "created_at": created_at,
            })

    return provider_rows


def write_dq_results(run_id, summary_df, weighted_df=None, started_at=None, completed_at=None):
    """
    Store ALL DQ results in the SINGLE dq_run_output table.
    Existing rule output is preserved:
      - One row per (file, dimension, rule) violation.
      - Per-file summary numbers are repeated on each DQ row.
      - Files with zero violations receive one summary-only row.
    No separate dq_results table is created.
    """
    created_at = timestamp_string(completed_at) if completed_at else timestamp_string()
    started_text = timestamp_string(started_at) if started_at else None
    completed_text = timestamp_string(completed_at) if completed_at else created_at
    run_duration = ((completed_at - started_at).total_seconds() if started_at and completed_at else None)
    weighted_score_map = {}
    if weighted_df is not None and not weighted_df.empty:
        final_rows = weighted_df[weighted_df["step_name"] == "weighted_sla_score"]
        if not final_rows.empty:
            weighted_score_map = {
                str(r["dataset_name"]): float(r["quality_score"])
                for _, r in final_rows.iterrows()
            }
    files = (
        set(TABLE_ROW_COUNTS.keys())
        | (
            set(summary_df["file"])
            if summary_df is not None and not summary_df.empty
            else set()
        )
    )
    rows = []
    for file in sorted(files):
        if summary_df is not None and not summary_df.empty:
            file_rules = summary_df[
                summary_df["file"] == file
           ]
        else:
            file_rules = pd.DataFrame(
                columns=[
                    "dimension",
                    "rule",
                    "action",
                    "violation_count"
               ]
            )
        file_summary = _compute_file_summary(
            file,
            file_rules
        )
        total = file_summary["total_records"]
        # ================================================================
        # NO VIOLATIONS
        # ================================================================
        if file_rules.empty:
            rows.append({
                # Execution/context fields
                "run_id": run_id,
                "step_name": "dq_validation",
                "status": "SUCCESS",
                "started_at": started_text,
                "completed_at": completed_text,
                "duration_seconds": run_duration,
                "records_processed": total,
                "dataset_name": file,
                "batch_id": resolve_batch_id(run_id),
                "error_message": None,
                # DQ fields
                "dimension": None,
                "field_name": None,
                "rule_name": None,
                "affected_rows": 0,
                "affected_pct": 0.0,
                "severity": "info",
                "message": "No violations found.",
                "root_cause": None,
                "recommendation": None,
                # Summary fields
                **file_summary,
                # Store the final weighted 0-10 DQ score, not the old
                # per-file pass-rate score.
                "quality_score": weighted_score_map.get(str(file)),
                "created_at": created_at,
            })
            continue
        # ================================================================
        # VIOLATION ROWS
        # ================================================================
        for _, r in file_rules.iterrows():
            affected_rows = int(
                r["violation_count"]
            )
            affected_pct = (
                round(
                    (affected_rows / total) * 100,
                    4
                )
                if total
                else None
            )
            action = r.get(
                "action",
                ""
            )
            severity = severity_for_action(
                action
            )
            root_cause, recommendation = get_root_cause_and_recommendation(
                rule_name=r["rule"],
                dimension=r["dimension"]
            )
            print("\n" + "-" * 80)
            print(f"DATASET       : {file}")
            print(f"DIMENSION     : {r['dimension']}")
            print(f"FAILED RULE   : {r['rule']}")
            print(f"AFFECTED ROWS : {affected_rows:,}")
            print(f"SEVERITY      : {severity}")
            print(f"ROOT CAUSE    : {root_cause}")
            print(f"RECOMMENDATION: {recommendation}")
            print("-" * 80)
            rows.append({
                # Execution/context fields
                "run_id": run_id,
                "step_name": "dq_validation",
                "status": "SUCCESS",
                "started_at": started_text,
                "completed_at": completed_text,
                "duration_seconds": run_duration,
                "records_processed": total,
                "dataset_name": file,
                "batch_id": resolve_batch_id(run_id),
                "error_message": None,
                # DQ fields
                "dimension": r["dimension"],
                "field_name": r["rule"],
                "rule_name": r["rule"],
                "affected_rows": affected_rows,
                "affected_pct": affected_pct,
                "severity": severity,
                "message": (
                    f"{affected_rows} row(s) failed rule "
                    f"'{r['rule']}' ({r['dimension']}) — "
                    f"action: {action}"
                ),
                "root_cause": root_cause,
                "recommendation": recommendation,
                # Summary fields
                **file_summary,
                # Store the final weighted 0-10 DQ score, not the old
                # per-file pass-rate score.
                "quality_score": weighted_score_map.get(str(file)),
                "created_at": created_at,
            })
    # ------------------------------------------------------------------------
    # PROVIDER-LEVEL COMPLETENESS OUTPUT (ADDITIONAL ONLY)
    # ------------------------------------------------------------------------
    provider_rows = build_provider_completeness_rows(
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
    )
    rows.extend(provider_rows)

    # ------------------------------------------------------------------------
    # PROVIDER-LEVEL OUTPUT FOR THE OTHER FIVE DQ DIMENSIONS (ADDITIONAL ONLY)
    # ------------------------------------------------------------------------
    provider_dimension_rows = build_provider_dimension_rows(
        run_id=run_id,
        started_at=started_at,
        completed_at=completed_at,
    )
    rows.extend(provider_dimension_rows)

    if rows:
        output_df = pd.DataFrame(rows)
        output_df.to_sql(
            "dq_run_output",
            DQ_SQLITE_ENGINE,
            if_exists="append",
            index=False
        )
        print(
            f"\n✓ {len(output_df):,} DQ result row(s) "
            "stored in dq_run_output"
        )
        if provider_rows:
            print(
                f"✓ {len(provider_rows):,} provider-level Completeness "
                "row(s) stored in dq_run_output"
            )
        if provider_dimension_rows:
            print(
                f"✓ {len(provider_dimension_rows):,} provider-level "
                "dimension row(s) stored in dq_run_output"
            )
    else:
        print("\n✓ No DQ result rows to store.")
# DAGSTER OPS
# ============================================================================
# Each op wraps one stage of the existing pipeline. The rule-check functions
# themselves (check_completeness, check_correctness, ...) are called exactly
# as before, unmodified, via run_beneficiary()/run_claims(). Every op logs
# its start/finish into dq_run_output so the run is fully auditable in
# the database, not just in stdout.
# ============================================================================
@op(out=Out(str))
def start_run(context: OpExecutionContext) -> str:
    """
    Generates the run_id for this Dagster run and makes sure the DQ
    tables exist in claim_dagster.db.
    """
    run_id = context.run_id or str(uuid.uuid4())
    # Create a unique batch_id for THIS run so every execution is its
    # own batch in dq_run_output (date + short run fragment).
    batch_id = f"{TODAY:%Y%m%d}_{run_id[:8]}"
    RUN_BATCH_IDS[run_id] = batch_id
    RUN_START_TIMES[run_id] = datetime.now()
    # Reset only the additional provider-level Completeness aggregation for
    # this run. Existing DQ rule state/logic is unchanged.
    PROVIDER_COMPLETENESS_COUNTS.clear()
    PROVIDER_COMPLETENESS_RECORD_KEYS.clear()
    PROVIDER_DQ_TOTAL_ROWS.clear()
    PROVIDER_DQ_DIMENSION_COUNTS.clear()
    PROVIDER_DQ_RECORD_KEYS.clear()
    SINK.counts.clear()
    SINK.unique_record_keys.clear()
    SINK.dimension_record_keys.clear()
    SINK.samples.clear()
    SINK.actions.clear()
    _carry.clear()
    # Create the single SQLite output table.
    create_dq_tables_sqlite()
    context.log.info(f"Starting DQ run {run_id} (batch {batch_id})")
    return run_id
@op(ins={"run_id": In(str)}, out=Out(str))
def validate_source_tables(context: OpExecutionContext, run_id: str) -> str:
    started_at = datetime.now()
    status = "SUCCESS"
    error_message = None
    try:
        with SOURCE_SQLITE_ENGINE.connect() as conn:
            inspector = inspect(conn)
            available_tables = set(inspector.get_table_names())
            required_tables = ["beneficiary"] + CLAIM_TABLES
            missing_tables = [
                t for t in required_tables if t not in available_tables
            ]
            if missing_tables:
                raise RuntimeError(
                    "The following required SQLite tables are missing: "
                    + ", ".join(missing_tables)
                )
        context.log.info(
            f"All required SQLite tables found in {SOURCE_SQLITE_DATABASE}."
        )
    except Exception as e:
        status = "FAILED"
        error_message = str(e)
        raise
    finally:
        log_execution_step(
            run_id=run_id,
            step_name="validate_source_tables",
            status=status,
            started_at=started_at,
            completed_at=datetime.now(),
            dataset_name=None,
            error_message=error_message,
        )
    return run_id
@op(ins={"run_id": In(str)}, out=Out(str))
def run_beneficiary_checks(context: OpExecutionContext, run_id: str) -> str:
    global VALID_BENE_IDS
    started_at = datetime.now()
    status = "SUCCESS"
    error_message = None
    records_processed = None
    try:
        with SOURCE_SQLITE_ENGINE.connect() as conn:
            context.log.info("Loading enrollment master ...")
            enroll = load_enrollment_master(conn)
            if "BENE_ID" not in enroll.columns:
                raise RuntimeError(
                    "BENE_ID column was not found in the beneficiary table."
                )
            VALID_BENE_IDS = set(enroll["BENE_ID"])
            context.log.info(
                f"{len(VALID_BENE_IDS):,} unique BENE_ID in enrollment master"
            )
            run_beneficiary(conn)
            records_processed = TABLE_ROW_COUNTS.get("beneficiary_2025.csv")
    except Exception as e:
        status = "FAILED"
        error_message = str(e)
        raise
    finally:
        log_execution_step(
            run_id=run_id,
            step_name="run_beneficiary_checks",
            status=status,
            started_at=started_at,
            completed_at=datetime.now(),
            records_processed=records_processed,
            dataset_name="beneficiary_2025.csv",
            error_message=error_message,
        )
    return run_id
@op(ins={"run_id": In(str)}, out=Out(str))
def run_claims_checks(context: OpExecutionContext, run_id: str) -> str:
    started_at = datetime.now()
    status = "SUCCESS"
    error_message = None
    try:
        with SOURCE_SQLITE_ENGINE.connect() as conn:
            run_claims(conn)
    except Exception as e:
        status = "FAILED"
        error_message = str(e)
        raise
    finally:
        completed_at = datetime.now()
        records_processed = sum(
            TABLE_ROW_COUNTS.get(f"{t}.csv", 0) for t in CLAIM_TABLES
        )
        log_execution_step(
            run_id=run_id,
            step_name="run_claims_checks",
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            records_processed=records_processed,
            dataset_name="claims (carrier/dme/hha/inpatient/outpatient/snf)",
            error_message=error_message,
        )
    return run_id
@op(ins={"run_id": In(str)})
def finalize_and_persist_results(context: OpExecutionContext, run_id: str) -> None:
    """
    Flushes SINK to CSV/JSON (unchanged behavior) and writes all DQ results
    into the single dq_run_output table in claim_dagster.db.
    No DQ rule logic is changed here.
    """
    # Use the actual start timestamp captured in start_run().
    started_at = RUN_START_TIMES.get(run_id, datetime.now())
    status = "SUCCESS"
    error_message = None
    try:
        summary = SINK.flush(OUT_DIR)
        if not summary.empty:
            summary.to_csv(
                os.path.join(OUT_DIR, "dq_summary.csv"),
                index=False
            )
            context.log.info(
                f"\n{summary.to_string(index=False)}"
            )
        else:
            context.log.info("No violations found.")
        # Capture one actual run-end timestamp and use it for all stored rows.
        completed_at = datetime.now()
        # Calculate the weighted scores first so the same final 0-10 score
        # can be stored in quality_score for every DQ row of that dataset.
        weighted_df = write_weighted_scores(
            run_id,
            summary,
            started_at=started_at,
            completed_at=completed_at
        )
        # Store all existing DQ result information in the ONE table.
        write_dq_results(
            run_id,
            summary,
            weighted_df=weighted_df,
            started_at=started_at,
            completed_at=completed_at
        )
        context.log.info(
            f"Results persisted to {DQ_SQLITE_DATABASE} "
            f"(dq_run_output) for run_id={run_id}"
        )
    except Exception as e:
        status = "FAILED"
        error_message = str(e)
        raise
    finally:
        finalize_completed_at = locals().get("completed_at", datetime.now())
        log_execution_step(
            run_id=run_id,
            step_name="finalize_and_persist_results",
            status=status,
            started_at=started_at,
            completed_at=finalize_completed_at,
            error_message=error_message
        )
# ============================================================================
# DAGSTER JOB
# ============================================================================
@job
def medicare_dq_pipeline():
    """
    Dagster job wiring together every step of the existing pipeline, in the
    same order the old `if __name__ == "__main__":` block ran them:
        1. start_run                    -> create DQ tables, get run_id
        2. validate_source_tables       -> check required SQLite tables exist
        3. run_beneficiary_checks       -> load enrollment + beneficiary DQ
        4. run_claims_checks            -> DQ across all claim tables
        5. finalize_and_persist_results -> flush files + write to database
                                            (dq_results)
    """
    run_id = start_run()
    run_id = validate_source_tables(run_id)
    run_id = run_beneficiary_checks(run_id)
    run_id = run_claims_checks(run_id)
    finalize_and_persist_results(run_id)
# ============================================================================
# MAIN PROGRAM
# ============================================================================
#
# Running this file directly now executes the pipeline THROUGH Dagster
# (`medicare_dq_pipeline.execute_in_process()`), so every run is logged to
# dq_run_output and its results land in dq_results —
# exactly as it would if triggered from `dagster dev` / a Dagster schedule.
# ============================================================================
if __name__ == "__main__":
    print("=" * 80)
    print("MEDICARE FFS DATA QUALITY ENGINE — DAGSTER")
    print("=" * 80)
    print(f"\nSource SQLite DB : {SOURCE_SQLITE_DATABASE}")
    print(f"SQLite DB      : {DQ_SQLITE_DATABASE}")
    result = medicare_dq_pipeline.execute_in_process(raise_on_error=False)
    if result.success:
        print("\nProcessing completed successfully.")
        print(f"Detailed rule outputs written to: {OUT_DIR}")
        print(
            f"DQ results persisted to: {DQ_SQLITE_DATABASE} "
            "(dq_run_output)"
        )
    else:
        print("\n" + "=" * 80)
        print("PIPELINE FAILED")
        print("=" * 80)
        for event in result.all_events:
            if event.is_failure:
                print(event.message)
        print("\nPlease check:")
        print("1. claim_sentinel.db exists in the same folder as this script.")
        print("2. Required SQLite tables exist: beneficiary, carrier, dme, hha, hospice, inpatient, outpatient.")
        print("3. sqlalchemy, pandas, and dagster are installed.")