
# ============================================================
# CLAIMS ANOMALY DETECTION
#
# Input:
#   claim_sentinel.db
#   Tables:
#     inpatient
#     snf
#     dme
#     hha
#     hospice
#     outpatient
#     carrier
#
# Output:
#   anomalies.db
#
# Tables:
#   claims_anomalies
#   claims_individual_metrics
#
# Methods:
#   Robust Z-score
#   Rolling historical PSI
#   Rule-based validation
#
# IMPORTANT:
#   - Claim files are line-level in several CMS/SynPUF-style files.
#   - Duplicate detection therefore uses (CLM_ID, line_id) when a
#     line identifier exists. Repeated CLM_ID alone is NOT treated
#     as a duplicate in line-level data.
#   - Robust Z is calculated at PROVIDER-MONTH level and compared
#     with peers within the same claim type and month.
#   - PSI uses a rolling historical baseline of previous valid months.
#   - The current month is never included in its own PSI baseline.
#   - All individual metrics (normal and anomalous) are stored.
#   - Historical runs are preserved using run_id/run_timestamp.
# ============================================================

import os
import re
import sqlite3
import uuid
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# ============================================================
# 1. PATHS
# ============================================================

DATA_FOLDER = r"C:/Users/sweth/OneDrive/Pictures/Desktop/Congnizant"

# INPUT SQLite database
INPUT_DB = os.path.join(
    DATA_FOLDER,
    "claim_sentinel.db"
)


OUTPUT_DB = os.path.join(
    DATA_FOLDER,
    "anomalies.db"
)


# ============================================================
# 2. SETTINGS
# ============================================================

Z_THRESHOLD = 3.5

PSI_NORMAL = 0.10
PSI_MODERATE = 0.25

BASELINE_BATCHES = 6
BASELINE_MIN_ROWS = 1000
PSI_MIN_BATCH_ROWS = 300
MIN_CATEGORY_SHARE = 0.02

MIN_PEERS_FOR_Z = 5

# SQLite tables expected in claim_sentinel.db.
CLAIM_TABLES = {
    "inpatient": "inpatient",
    "snf": "snf",
    "outpatient": "outpatient",
    "hha": "hha",
    "hospice": "hospice",
    "dme": "dme",
    "carrier": "carrier",
}


RUN_TIMESTAMP = datetime.now().strftime(
    "%Y-%m-%d %H:%M:%S"
)

RUN_ID = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
) + "_" + uuid.uuid4().hex[:8]


# ============================================================
# 3. HELPERS
# ============================================================

def norm_name(value):
    return (
        str(value)
        .strip()
        .upper()
        .replace(" ", "_")
    )


def get_sqlite_tables(conn):
    """Return all user tables in the input SQLite database."""
    rows = conn.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
    """).fetchall()

    return [row[0] for row in rows]


def find_sqlite_table(conn, expected_name):
    """Find a SQLite table case-insensitively."""
    expected = str(expected_name).strip().lower()

    for table in get_sqlite_tables(conn):
        if str(table).strip().lower() == expected:
            return table

    return None


def read_sqlite_header(conn, table_name):
    """Read column names from a SQLite table."""
    safe_table = '"' + str(table_name).replace('"', '""') + '"'

    rows = conn.execute(
        f"PRAGMA table_info({safe_table})"
    ).fetchall()

    return [row[1] for row in rows]


def read_selected_sqlite_columns(conn, table_name, columns):
    """Read only the columns needed by the anomaly layer."""
    available = read_sqlite_header(conn, table_name)

    wanted = [
        c for c in columns
        if c in available
    ]

    if not wanted:
        return pd.DataFrame()

    safe_table = '"' + str(table_name).replace('"', '""') + '"'

    safe_columns = [
        '"' + str(c).replace('"', '""') + '"'
        for c in wanted
    ]

    query = f"""
        SELECT {", ".join(safe_columns)}
        FROM {safe_table}
    """

    return pd.read_sql_query(query, conn)


def first_existing(df, candidates):
    """
    Return the first candidate column that exists.
    """
    for c in candidates:
        if c in df.columns:
            return c
    return None


def existing_columns(df, candidates):
    return [c for c in candidates if c in df.columns]


def to_numeric(df, columns):
    for c in columns:
        if c in df.columns:
            df[c] = pd.to_numeric(
                df[c],
                errors="coerce"
            )


def robust_z_from_series(series):
    """
    Robust Z:
        0.6745 * (x - median) / MAD

    If MAD is zero/undefined, score is NaN rather than
    falsely treating every observation as normal.
    """
    s = pd.to_numeric(
        series,
        errors="coerce"
    )

    median = s.median()

    if pd.isna(median):
        return pd.Series(
            np.nan,
            index=s.index
        )

    mad = np.nanmedian(
        np.abs(s - median)
    )

    if pd.isna(mad) or mad == 0:
        return pd.Series(
            np.nan,
            index=s.index
        )

    return (
        0.6745
        * (s - median)
        / mad
    )


def grouped_robust_z(
    df,
    feature,
    group_columns,
    min_group_size=MIN_PEERS_FOR_Z
):
    """
    Calculate Robust Z within peer groups.

    Example:
        claim_type + batch_month

    For specialty behavior:
        claim_type + batch_month + specialty
    """
    result = pd.Series(
        np.nan,
        index=df.index,
        dtype=float
    )

    if feature not in df.columns:
        return result

    temp = df[
        group_columns + [feature]
    ].copy()

    temp["_valid"] = pd.to_numeric(
        temp[feature],
        errors="coerce"
    ).notna()

    for _, idx in temp[temp["_valid"]].groupby(
        group_columns
    ).groups.items():

        if len(idx) < min_group_size:
            continue

        result.loc[idx] = robust_z_from_series(
            df.loc[idx, feature]
        )

    return result


def calculate_psi(
    baseline_series,
    current_series
):
    """
    Standard PSI with a small floor for zero proportions.
    """
    baseline = (
        baseline_series
        .astype(str)
        .value_counts(normalize=True)
    )

    current = (
        current_series
        .astype(str)
        .value_counts(normalize=True)
    )

    categories = sorted(
        set(baseline.index)
        | set(current.index)
    )

    baseline = baseline.reindex(
        categories,
        fill_value=0
    )

    current = current.reindex(
        categories,
        fill_value=0
    )

    epsilon = 0.0001

    expected = np.clip(
        baseline.values,
        epsilon,
        None
    )

    actual = np.clip(
        current.values,
        epsilon,
        None
    )

    return float(
        np.sum(
            (actual - expected)
            * np.log(actual / expected)
        )
    )


def bucket_rare_categories(
    baseline_values,
    current_values
):
    """
    Keep categories with at least MIN_CATEGORY_SHARE in
    baseline. Everything else becomes OTHER_RARE.
    """
    baseline_counts = (
        baseline_values
        .value_counts()
    )

    if baseline_counts.empty:
        return None, None, set()

    shares = (
        baseline_counts
        / baseline_counts.sum()
    )

    keep = set(
        shares[
            shares >= MIN_CATEGORY_SHARE
        ].index
    )

    if len(keep) < 2:
        return None, None, keep

    def bucket(x):
        return (
            x
            if x in keep
            else "OTHER_RARE"
        )

    return (
        baseline_values.map(bucket),
        current_values.map(bucket),
        keep
    )


def psi_interpretation(score):
    if pd.isna(score):
        return "NOT_AVAILABLE"

    if score < PSI_NORMAL:
        return "NORMAL"

    if score < PSI_MODERATE:
        return "MODERATE DRIFT"

    return "SIGNIFICANT DRIFT"


def clean_code_series(series):
    return (
        series
        .astype("string")
        .str.strip()
        .str.upper()
    )


def valid_icd_series(series):
    """
    Vectorized structural ICD validation.
    """
    s = (
        series.astype("string")
        .str.strip()
        .str.upper()
    )
    return (
        s.notna()
        & s.str.fullmatch(
            r"[A-Z0-9]{3,7}",
            na=False
        )
    )


def valid_hcpcs_series(series):
    """
    Vectorized structural HCPCS/CPT-like validation.
    """
    s = (
        series.astype("string")
        .str.strip()
        .str.upper()
    )
    return (
        s.notna()
        & s.str.fullmatch(
            r"[A-Z0-9]{5}",
            na=False
        )
    )


def safe_float(value):
    if pd.isna(value):
        return None
    try:
        return float(value)
    except Exception:
        return None


# ============================================================
# 4. COLUMN DEFINITIONS
# ============================================================

COMMON_COLUMNS = [
    "BENE_ID",
    "CLM_ID",
    "CLM_FROM_DT",
    "CLM_THRU_DT",
    "CLM_ADMSN_DT",
    "NCH_BENE_DSCHRG_DT",

    "CLM_PMT_AMT",
    "CLM_TOT_CHRG_AMT",

    "NCH_CARR_CLM_SBMTD_CHRG_AMT",
    "NCH_CARR_CLM_ALOWD_AMT",

    "NCH_PRMRY_PYR_CD",
    "LINE_BENE_PRMRY_PYR_CD",

    "PTNT_DSCHRG_STUS_CD",
    "CLM_DISP_CD",
    "CLM_MDCR_NON_PMT_RSN_CD",

    "PRVDR_SPCLTY",
    "PRVDR_STATE_CD",

    "ORG_NPI_NUM",
    "PRVDR_NPI",
    "PRVDR_NUM",

    "CLM_UTLZTN_DAY_CNT",
    "CLM_HHA_TOT_VISIT_CNT",

    "LINE_NUM",
    "CLM_LINE_NUM",

    "REV_CNTR",
    "REV_CNTR_UNIT_CNT",
    "REV_CNTR_TOT_CHRG_AMT",
    "REV_CNTR_PMT_AMT_AMT",
    "REV_CNTR_PRVDR_PMT_AMT",
    "REV_CNTR_BENE_PMT_AMT",
    "REV_CNTR_NCVRD_CHRG_AMT",

    "LINE_SRVC_CNT",
    "LINE_NCH_PMT_AMT",
    "LINE_PRVDR_PMT_AMT",
    "LINE_BENE_PMT_AMT",
    "LINE_SBMTD_CHRG_AMT",
    "LINE_ALOWD_CHRG_AMT",
    "LINE_PRMRY_ALOWD_CHRG_AMT",
    "LINE_BENE_PRMRY_PYR_CD",

    "DMERC_LINE_MTUS_CNT",
    "DMERC_LINE_MTUS_CD",

    "HCPCS_CD",

    "LINE_PRCSG_IND_CD",
    "REV_CNTR_STUS_IND_CD",

    "CLM_FAC_TYPE_CD",
    "CLM_SRVC_CLSFCTN_TYPE_CD",
    "CLM_FREQ_CD",
]

# All diagnosis fields.
DIAGNOSIS_PATTERN = re.compile(
    r"^(PRNCPAL_DGNS_CD|ADMTG_DGNS_CD|"
    r"ICD_DGNS_CD\d+|FST_DGNS_E_CD|ICD_DGNS_E_CD\d+)$",
    re.IGNORECASE
)

# Inpatient/SNF procedure fields.
PROCEDURE_PATTERN = re.compile(
    r"^ICD_PRCDR_CD\d+$",
    re.IGNORECASE
)

PROCEDURE_DATE_PATTERN = re.compile(
    r"^PRCDR_DT\d+$",
    re.IGNORECASE
)


# ============================================================
# 5. LOAD ONE CLAIM TABLE FROM SQLITE
# ============================================================

def load_claim_file(
    claim_type,
    conn,
    table_name
):

    print("\n" + "=" * 80)
    print(
        f"LOADING {claim_type.upper()} CLAIM DATA"
    )
    print("=" * 80)

    headers = read_sqlite_header(
    conn,
    table_name
)

    diagnosis_columns = [
        c for c in headers
        if DIAGNOSIS_PATTERN.match(
            str(c)
        )
    ]

    procedure_columns = [
        c for c in headers
        if PROCEDURE_PATTERN.match(
            str(c)
        )
    ]

    procedure_date_columns = [
        c for c in headers
        if PROCEDURE_DATE_PATTERN.match(
            str(c)
        )
    ]

    required = list(
        dict.fromkeys(
            COMMON_COLUMNS
            + diagnosis_columns
            + procedure_columns
            + procedure_date_columns
        )
    )

    df = read_selected_sqlite_columns(
        conn,
        table_name,
        required
    )

    if df.empty:
        print("No usable columns/data.")
        return None

    df.columns = [
        str(c).strip()
        for c in df.columns
    ]

    print(
        "Raw rows:",
        len(df)
    )

    # --------------------------------------------------------
    # Date
    # --------------------------------------------------------

    date_col = first_existing(
        df,
        [
            "CLM_FROM_DT",
            "SERVICE_DATE",
            "SRVC_DT",
            "LINE_1ST_EXPNS_DT"
        ]
    )

    if date_col is None:
        print(
            "WARNING: no claim/service date found. "
            "Skipping file."
        )
        return None

    df["BATCH_DATE"] = pd.to_datetime(
        df[date_col],
        errors="coerce"
    )

    df = df[
        df["BATCH_DATE"].notna()
    ].copy()

    if df.empty:
        print(
            "No valid dates. Skipping."
        )
        return None

    df["BATCH_MONTH"] = (
        df["BATCH_DATE"]
        .dt.to_period("M")
        .astype(str)
    )

    # --------------------------------------------------------
    # Claim ID
    # --------------------------------------------------------

    claim_id_col = first_existing(
        df,
        [
            "CLM_ID",
            "CLAIM_ID",
            "CLAIMID"
        ]
    )

    if claim_id_col is None:
        print(
            "WARNING: no CLM_ID found. "
            "Using row index as claim ID."
        )
        df["_CLAIM_ID"] = (
            df.index.astype(str)
        )
        claim_id_col = "_CLAIM_ID"

    # --------------------------------------------------------
    # Provider ID
    # --------------------------------------------------------

    provider_col = first_existing(
        df,
        [
            "ORG_NPI_NUM",
            "PRVDR_NPI",
            "PRVDR_NUM",
            "RFR_PHYSN_NPI"
        ]
    )

    if provider_col is None:
        print(
            "WARNING: no provider identifier found."
        )
        df["_PROVIDER_ID"] = (
            "UNKNOWN_"
            + df.index.astype(str)
        )
        provider_col = "_PROVIDER_ID"

    # --------------------------------------------------------
    # Line ID
    # --------------------------------------------------------

    line_col = first_existing(
        df,
        [
            "CLM_LINE_NUM",
            "LINE_NUM"
        ]
    )

    if line_col is None:
        df["_LINE_ID"] = (
            df.index.astype(str)
        )
        line_col = "_LINE_ID"

    # --------------------------------------------------------
    # Standard names
    # --------------------------------------------------------

    df["CLAIM_ID_STD"] = (
        df[claim_id_col]
        .astype("string")
    )

    df["PROVIDER_ID_STD"] = (
        df[provider_col]
        .astype("string")
    )

    df["LINE_ID_STD"] = (
        df[line_col]
        .astype("string")
    )

    # --------------------------------------------------------
    # Provider state
    # --------------------------------------------------------

    state_col = first_existing(
        df,
        [
            "PRVDR_STATE_CD",
            "DMERC_LINE_PRCNG_STATE_CD"
        ]
    )

    if state_col:
        df["STATE_STD"] = (
            df[state_col]
            .astype("string")
        )
    else:
        df["STATE_STD"] = pd.NA

    # --------------------------------------------------------
    # Specialty
    # --------------------------------------------------------

    specialty_col = first_existing(
        df,
        [
            "PRVDR_SPCLTY"
        ]
    )

    if specialty_col:
        df["SPECIALTY_STD"] = (
            df[specialty_col]
            .astype("string")
        )
    else:
        df["SPECIALTY_STD"] = pd.NA

    # --------------------------------------------------------
    # Numeric conversion
    # --------------------------------------------------------

    numeric_candidates = [
        "CLM_PMT_AMT",
        "CLM_TOT_CHRG_AMT",
        "NCH_CARR_CLM_SBMTD_CHRG_AMT",
        "NCH_CARR_CLM_ALOWD_AMT",
        "CLM_UTLZTN_DAY_CNT",
        "CLM_HHA_TOT_VISIT_CNT",
        "REV_CNTR_UNIT_CNT",
        "REV_CNTR_TOT_CHRG_AMT",
        "REV_CNTR_PMT_AMT_AMT",
        "REV_CNTR_PRVDR_PMT_AMT",
        "REV_CNTR_BENE_PMT_AMT",
        "REV_CNTR_NCVRD_CHRG_AMT",
        "LINE_SRVC_CNT",
        "LINE_NCH_PMT_AMT",
        "LINE_PRVDR_PMT_AMT",
        "LINE_BENE_PMT_AMT",
        "LINE_SBMTD_CHRG_AMT",
        "LINE_ALOWD_CHRG_AMT",
        "LINE_PRMRY_ALOWD_CHRG_AMT",
        "DMERC_LINE_MTUS_CNT",
        "DMERC_LINE_MTUS_CD",
    ]

    to_numeric(
        df,
        numeric_candidates
    )

    # --------------------------------------------------------
    # Claim-level payment
    # --------------------------------------------------------

    claim_payment_col = first_existing(
        df,
        [
            "CLM_PMT_AMT",
            "NCH_PRVDR_PMT_AMT"
        ]
    )

    if claim_payment_col:
        df["CLAIM_PAYMENT"] = pd.to_numeric(
            df[claim_payment_col],
            errors="coerce"
        )
    else:
        line_payment_col = first_existing(
            df,
            [
                "LINE_NCH_PMT_AMT",
                "REV_CNTR_PMT_AMT_AMT"
            ]
        )

        if line_payment_col:
            df["CLAIM_PAYMENT"] = pd.to_numeric(
                df[line_payment_col],
                errors="coerce"
            )
        else:
            df["CLAIM_PAYMENT"] = np.nan

    # --------------------------------------------------------
    # Claim-level charge
    # --------------------------------------------------------

    claim_charge_col = first_existing(
        df,
        [
            "CLM_TOT_CHRG_AMT",
            "NCH_CARR_CLM_SBMTD_CHRG_AMT"
        ]
    )

    if claim_charge_col:
        df["CLAIM_CHARGE"] = pd.to_numeric(
            df[claim_charge_col],
            errors="coerce"
        )
    else:
        line_charge_col = first_existing(
            df,
            [
                "LINE_SBMTD_CHRG_AMT",
                "REV_CNTR_TOT_CHRG_AMT"
            ]
        )

        if line_charge_col:
            df["CLAIM_CHARGE"] = pd.to_numeric(
                df[line_charge_col],
                errors="coerce"
            )
        else:
            df["CLAIM_CHARGE"] = np.nan

    # --------------------------------------------------------
    # Allowed amount
    # --------------------------------------------------------

    allowed_col = first_existing(
        df,
        [
            "NCH_CARR_CLM_ALOWD_AMT",
            "LINE_ALOWD_CHRG_AMT",
            "LINE_PRMRY_ALOWD_CHRG_AMT"
        ]
    )

    if allowed_col:
        df["ALLOWED_AMOUNT"] = pd.to_numeric(
            df[allowed_col],
            errors="coerce"
        )
    else:
        df["ALLOWED_AMOUNT"] = np.nan

    # --------------------------------------------------------
    # Service units
    # --------------------------------------------------------

    unit_col = first_existing(
        df,
        [
            "LINE_SRVC_CNT",
            "REV_CNTR_UNIT_CNT",
            "DMERC_LINE_MTUS_CNT"
        ]
    )

    if unit_col:
        df["SERVICE_UNITS"] = pd.to_numeric(
            df[unit_col],
            errors="coerce"
        )
    else:
        df["SERVICE_UNITS"] = np.nan

    # --------------------------------------------------------
    # Utilization days
    # --------------------------------------------------------

    util_day_col = first_existing(
        df,
        [
            "CLM_UTLZTN_DAY_CNT"
        ]
    )

    if util_day_col:
        df["UTILIZATION_DAYS"] = pd.to_numeric(
            df[util_day_col],
            errors="coerce"
        )
    else:
        df["UTILIZATION_DAYS"] = np.nan

    # --------------------------------------------------------
    # HHA visits
    # --------------------------------------------------------

    hha_visit_col = first_existing(
        df,
        [
            "CLM_HHA_TOT_VISIT_CNT"
        ]
    )

    if hha_visit_col:
        df["HHA_VISITS"] = pd.to_numeric(
            df[hha_visit_col],
            errors="coerce"
        )
    else:
        df["HHA_VISITS"] = np.nan

    # --------------------------------------------------------
    # Discharge date
    # --------------------------------------------------------

    discharge_col = first_existing(
        df,
        [
            "NCH_BENE_DSCHRG_DT",
            "CLM_THRU_DT"
        ]
    )

    if discharge_col:
        df["DISCHARGE_DATE"] = pd.to_datetime(
            df[discharge_col],
            errors="coerce"
        )
    else:
        df["DISCHARGE_DATE"] = pd.NaT

    # --------------------------------------------------------
    # Admission date
    # --------------------------------------------------------

    admission_col = first_existing(
        df,
        [
            "CLM_ADMSN_DT",
            "CLM_FROM_DT"
        ]
    )

    if admission_col:
        df["ADMISSION_DATE"] = pd.to_datetime(
            df[admission_col],
            errors="coerce"
        )
    else:
        df["ADMISSION_DATE"] = pd.NaT

    # --------------------------------------------------------
    # Claim type-specific flag
    # --------------------------------------------------------

    df["CLAIM_TYPE"] = claim_type

    print(
        "Valid rows:",
        len(df),
        "| unique claims:",
        df["CLAIM_ID_STD"].nunique(),
        "| providers:",
        df["PROVIDER_ID_STD"].nunique()
    )

    return {
        "df": df,
        "claim_type": claim_type,
        "diagnosis_columns": diagnosis_columns,
        "procedure_columns": procedure_columns,
        "procedure_date_columns": procedure_date_columns,
    }


# ============================================================
# 6. CREATE CLAIM-LEVEL DATA
# ============================================================

def create_claim_level(data):
    df = data["df"].copy()

    # --------------------------------------------------------
    # Claim-level first record.
    #
    # This prevents repeated claim-level payment/charge values
    # from being summed across multiple revenue-center lines.
    # --------------------------------------------------------

    sort_columns = [
        "CLAIM_ID_STD",
        "LINE_ID_STD"
    ]

    claim_level = (
        df.sort_values(sort_columns)
        .drop_duplicates(
            subset=["CLAIM_ID_STD"],
            keep="first"
        )
        .copy()
    )

    # --------------------------------------------------------
    # Number of lines per claim
    # --------------------------------------------------------

    line_counts = (
        df.groupby(
            "CLAIM_ID_STD"
        )
        .size()
        .rename("CLAIM_LINE_COUNT")
    )

    claim_level = claim_level.merge(
        line_counts,
        left_on="CLAIM_ID_STD",
        right_index=True,
        how="left"
    )

    # --------------------------------------------------------
    # Duplicate line records
    # --------------------------------------------------------

    duplicate_mask = (
        df.duplicated(
            subset=[
                "CLAIM_ID_STD",
                "LINE_ID_STD"
            ],
            keep=False
        )
    )

    duplicate_pairs = (
        df.loc[duplicate_mask]
        .groupby(
            "CLAIM_ID_STD"
        )
        .size()
        .rename(
            "DUPLICATE_LINE_ROWS"
        )
    )

    claim_level = claim_level.merge(
        duplicate_pairs,
        left_on="CLAIM_ID_STD",
        right_index=True,
        how="left"
    )

    claim_level[
        "DUPLICATE_LINE_ROWS"
    ] = claim_level[
        "DUPLICATE_LINE_ROWS"
    ].fillna(0)

    # --------------------------------------------------------
    # Length of stay
    # --------------------------------------------------------

    claim_level["LOS_DAYS"] = (
        claim_level["DISCHARGE_DATE"]
        - claim_level["ADMISSION_DATE"]
    ).dt.days

    # --------------------------------------------------------
    # Ratio
    # --------------------------------------------------------

    claim_level[
        "PAYMENT_TO_CHARGE"
    ] = (
        claim_level["CLAIM_PAYMENT"]
        /
        claim_level["CLAIM_CHARGE"]
        .replace(0, np.nan)
    )

    # --------------------------------------------------------
    # Payment-to-allowed
    # --------------------------------------------------------

    claim_level[
        "PAYMENT_TO_ALLOWED"
    ] = (
        claim_level["CLAIM_PAYMENT"]
        /
        claim_level["ALLOWED_AMOUNT"]
        .replace(0, np.nan)
    )

    return claim_level


# ============================================================
# 7. PROVIDER-MONTH BEHAVIORAL METRICS
# ============================================================

def create_provider_month_metrics(
    data,
    claim_level
):
    df = data["df"]
    claim_type = data["claim_type"]

    # --------------------------------------------------------
    # Claim-level provider/month metrics
    # --------------------------------------------------------

    group_cols = [
        "PROVIDER_ID_STD",
        "BATCH_MONTH"
    ]

    provider = (
        claim_level
        .groupby(group_cols)
        .agg(
            claim_count=(
                "CLAIM_ID_STD",
                "nunique"
            ),
            beneficiary_count=(
                "BENE_ID",
                "nunique"
            ),
            avg_claim_payment=(
                "CLAIM_PAYMENT",
                "mean"
            ),
            median_claim_payment=(
                "CLAIM_PAYMENT",
                "median"
            ),
            avg_claim_charge=(
                "CLAIM_CHARGE",
                "mean"
            ),
            median_claim_charge=(
                "CLAIM_CHARGE",
                "median"
            ),
            avg_payment_to_charge=(
                "PAYMENT_TO_CHARGE",
                "mean"
            ),
            avg_los=(
                "LOS_DAYS",
                "mean"
            ),
            avg_utilization_days=(
                "UTILIZATION_DAYS",
                "mean"
            ),
            avg_hha_visits=(
                "HHA_VISITS",
                "mean"
            ),
            total_payment=(
                "CLAIM_PAYMENT",
                "sum"
            ),
            total_charge=(
                "CLAIM_CHARGE",
                "sum"
            ),
            total_allowed=(
                "ALLOWED_AMOUNT",
                "sum"
            ),
        )
        .reset_index()
    )

    # --------------------------------------------------------
    # Provider utilization
    # --------------------------------------------------------

    provider[
        "claims_per_beneficiary"
    ] = (
        provider["claim_count"]
        /
        provider["beneficiary_count"]
        .replace(0, np.nan)
    )

    # --------------------------------------------------------
    # Duplicate rate at line level
    # --------------------------------------------------------

    duplicate_flags = (
        df[
            [
                "PROVIDER_ID_STD",
                "BATCH_MONTH",
                "CLAIM_ID_STD",
                "LINE_ID_STD"
            ]
        ]
        .duplicated(
            subset=[
                "PROVIDER_ID_STD",
                "BATCH_MONTH",
                "CLAIM_ID_STD",
                "LINE_ID_STD"
            ],
            keep="first"
        )
        .astype(float)
    )

    duplicate_base = df[
        [
            "PROVIDER_ID_STD",
            "BATCH_MONTH"
        ]
    ].copy()

    duplicate_base[
        "duplicate_flag"
    ] = duplicate_flags.values

    duplicate_by_provider = (
        duplicate_base
        .groupby(
            [
                "PROVIDER_ID_STD",
                "BATCH_MONTH"
            ],
            sort=False
        )["duplicate_flag"]
        .mean()
        .rename(
            "duplicate_rate"
        )
        .reset_index()
    )

    provider = provider.merge(
        duplicate_by_provider,
        on=[
            "PROVIDER_ID_STD",
            "BATCH_MONTH"
        ],
        how="left"
    )

    # --------------------------------------------------------
    # DME service units
    # --------------------------------------------------------

    service_units = (
        df.groupby(
            [
                "PROVIDER_ID_STD",
                "BATCH_MONTH"
            ]
        )["SERVICE_UNITS"]
        .mean()
        .rename(
            "avg_service_units"
        )
        .reset_index()
    )

    provider = provider.merge(
        service_units,
        on=[
            "PROVIDER_ID_STD",
            "BATCH_MONTH"
        ],
        how="left"
    )

    # --------------------------------------------------------
    # DME payment/allowed charge
    # --------------------------------------------------------

    payment_allowed = (
        df.groupby(
            [
                "PROVIDER_ID_STD",
                "BATCH_MONTH"
            ]
        )
        .agg(
            line_payment=(
                "CLAIM_PAYMENT",
                "mean"
            ),
            line_allowed=(
                "ALLOWED_AMOUNT",
                "mean"
            )
        )
        .reset_index()
    )

    payment_allowed[
        "payment_to_allowed"
    ] = (
        payment_allowed["line_payment"]
        /
        payment_allowed["line_allowed"]
        .replace(0, np.nan)
    )

    provider = provider.merge(
        payment_allowed[
            [
                "PROVIDER_ID_STD",
                "BATCH_MONTH",
                "payment_to_allowed"
            ]
        ],
        on=[
            "PROVIDER_ID_STD",
            "BATCH_MONTH"
        ],
        how="left"
    )

    # --------------------------------------------------------
    # Specialty
    # --------------------------------------------------------

    specialty_map = (
        df[
            [
                "PROVIDER_ID_STD",
                "BATCH_MONTH",
                "SPECIALTY_STD"
            ]
        ]
        .dropna(
            subset=["SPECIALTY_STD"]
        )
        .drop_duplicates(
            subset=[
                "PROVIDER_ID_STD",
                "BATCH_MONTH"
            ]
        )
    )

    provider = provider.merge(
        specialty_map,
        on=[
            "PROVIDER_ID_STD",
            "BATCH_MONTH"
        ],
        how="left"
    )

    # --------------------------------------------------------
    # State
    # --------------------------------------------------------

    state_map = (
        df[
            [
                "PROVIDER_ID_STD",
                "BATCH_MONTH",
                "STATE_STD"
            ]
        ]
        .dropna(
            subset=["STATE_STD"]
        )
        .drop_duplicates(
            subset=[
                "PROVIDER_ID_STD",
                "BATCH_MONTH"
            ]
        )
    )

    provider = provider.merge(
        state_map,
        on=[
            "PROVIDER_ID_STD",
            "BATCH_MONTH"
        ],
        how="left"
    )

    # --------------------------------------------------------
    # Keep anomaly features limited to the claim types for which
    # they are meaningful.
    #
    # #6 HHA visit count -> HHA only
    # #7 DME service units -> DME only
    # #8 DME payment/allowed -> DME only
    # --------------------------------------------------------

    if claim_type != "hha":
        provider["avg_hha_visits"] = np.nan

    if claim_type != "dme":
        provider["avg_service_units"] = np.nan
        provider["payment_to_allowed"] = np.nan

    provider["claim_type"] = claim_type

    return provider


# ============================================================
# 8. ADD ROBUST Z-SCORES
# ============================================================

ROBUST_FEATURES = [
    "avg_claim_payment",
    "avg_claim_charge",
    "avg_payment_to_charge",
    "duplicate_rate",
    "avg_los",
    "avg_utilization_days",
    "avg_hha_visits",
    "avg_service_units",
    "payment_to_allowed",
    "claims_per_beneficiary",
]

ROBUST_ANOMALY_NAMES = {
    "avg_claim_payment":
        "Claim payment anomaly",

    "avg_claim_charge":
        "Claim charge anomaly",

    "avg_payment_to_charge":
        "Payment-to-charge ratio anomaly",

    "duplicate_rate":
        "Duplicate claim anomaly",

    "avg_los":
        "Length-of-stay / utilization-day anomaly",

    "avg_hha_visits":
        "HHA visit-count anomaly",

    "avg_service_units":
        "DME service-unit/quantity anomaly",

    "payment_to_allowed":
        "DME payment/allowed-charge anomaly",

    "claims_per_beneficiary":
        "Provider utilization anomaly",
}


def add_robust_z_scores(provider_df):

    provider_df = provider_df.copy()

    # --------------------------------------------------------
    # Standard peer group:
    # same claim type + same month
    # --------------------------------------------------------

    for feature in ROBUST_FEATURES:

        if feature not in provider_df.columns:
            continue

        provider_df[
            feature + "_Z"
        ] = grouped_robust_z(
            provider_df,
            feature,
            [
                "claim_type",
                "BATCH_MONTH"
            ]
        )

    # --------------------------------------------------------
    # Provider specialty behavior:
    # use utilization within specialty where available.
    # --------------------------------------------------------

    provider_df[
        "specialty_behavior_Z"
    ] = np.nan

    if "SPECIALTY_STD" in provider_df.columns:

        valid = provider_df[
            "SPECIALTY_STD"
        ].notna()

        if valid.any():

            z = grouped_robust_z(
                provider_df.loc[valid].copy(),
                "claims_per_beneficiary",
                [
                    "claim_type",
                    "BATCH_MONTH",
                    "SPECIALTY_STD"
                ]
            )

            provider_df.loc[
                valid,
                "specialty_behavior_Z"
            ] = z.values

    return provider_df


# ============================================================
# 9. PSI
# ============================================================

PSI_FIELDS = {
    "Specialty distribution drift":
        "SPECIALTY_STD",

    "Geographic/state distribution drift":
        "STATE_STD",

    "Diagnosis distribution drift":
        "PRINCIPAL_DIAGNOSIS",

    "Procedure distribution drift":
        "PROCEDURE_CODE",

    "HCPCS/service distribution drift":
        "HCPCS_CODE",

    "Revenue-center distribution drift":
        "REV_CNTR_CODE",

    "Primary-payer distribution drift":
        "PRIMARY_PAYER",

    "Claim-status distribution drift":
        "CLAIM_STATUS",

    "Discharge-status distribution drift":
        "DISCHARGE_STATUS",
}


def prepare_psi_population(data):

    df = data["df"].copy()

    # --------------------------------------------------------
    # Principal diagnosis
    # --------------------------------------------------------

    diagnosis_columns = data[
        "diagnosis_columns"
    ]

    principal_diagnosis = first_existing(
        df,
        [
            "PRNCPAL_DGNS_CD",
            "ADMTG_DGNS_CD"
        ]
    )

    if principal_diagnosis:
        df["PRINCIPAL_DIAGNOSIS"] = (
            clean_code_series(
                df[principal_diagnosis]
            )
        )
    elif diagnosis_columns:
        df["PRINCIPAL_DIAGNOSIS"] = (
            clean_code_series(
                df[diagnosis_columns[0]]
            )
        )
    else:
        df["PRINCIPAL_DIAGNOSIS"] = pd.NA

    # --------------------------------------------------------
    # Procedure
    # --------------------------------------------------------

    procedure_columns = data[
        "procedure_columns"
    ]

    if procedure_columns:
        df["PROCEDURE_CODE"] = (
            clean_code_series(
                df[procedure_columns[0]]
            )
        )
    else:
        df["PROCEDURE_CODE"] = pd.NA

    # --------------------------------------------------------
    # HCPCS
    # --------------------------------------------------------

    hcpcs = first_existing(
        df,
        ["HCPCS_CD"]
    )

    if hcpcs:
        df["HCPCS_CODE"] = (
            clean_code_series(
                df[hcpcs]
            )
        )
    else:
        df["HCPCS_CODE"] = pd.NA

    # --------------------------------------------------------
    # Revenue center
    # --------------------------------------------------------

    rev = first_existing(
        df,
        ["REV_CNTR"]
    )

    if rev:
        df["REV_CNTR_CODE"] = (
            df[rev]
            .astype("string")
        )
    else:
        df["REV_CNTR_CODE"] = pd.NA

    # --------------------------------------------------------
    # Primary payer
    # --------------------------------------------------------

    payer = first_existing(
        df,
        [
            "NCH_PRMRY_PYR_CD",
            "LINE_BENE_PRMRY_PYR_CD"
        ]
    )

    if payer:
        df["PRIMARY_PAYER"] = (
            df[payer]
            .astype("string")
        )
    else:
        df["PRIMARY_PAYER"] = pd.NA

    # --------------------------------------------------------
    # Claim status
    # --------------------------------------------------------

    status = first_existing(
        df,
        [
            "CLM_DISP_CD",
            "CLM_MDCR_NON_PMT_RSN_CD",
            "LINE_PRCSG_IND_CD",
            "REV_CNTR_STUS_IND_CD"
        ]
    )

    if status:
        df["CLAIM_STATUS"] = (
            df[status]
            .astype("string")
        )
    else:
        df["CLAIM_STATUS"] = pd.NA

    # --------------------------------------------------------
    # Discharge status
    # --------------------------------------------------------

    discharge = first_existing(
        df,
        ["PTNT_DSCHRG_STUS_CD"]
    )

    if discharge:
        df["DISCHARGE_STATUS"] = (
            df[discharge]
            .astype("string")
        )
    else:
        df["DISCHARGE_STATUS"] = pd.NA

    return df


def calculate_rolling_psi(
    df,
    claim_type
):

    psi_records = []

    months = sorted(
        df["BATCH_MONTH"]
        .dropna()
        .unique()
    )

    # Need at least baseline + current month
    if len(months) <= BASELINE_BATCHES:
        return psi_records

    for field_name, column in PSI_FIELDS.items():

        if column not in df.columns:
            continue

        for current_index in range(
            BASELINE_BATCHES,
            len(months)
        ):

            current_month = (
                months[current_index]
            )

            baseline_months = months[
                current_index
                - BASELINE_BATCHES:
                current_index
            ]

            baseline_df = df[
                df["BATCH_MONTH"].isin(
                    baseline_months
                )
            ]

            current_df = df[
                df["BATCH_MONTH"]
                == current_month
            ]

            if (
                len(baseline_df)
                < BASELINE_MIN_ROWS
            ):
                continue

            if (
                len(current_df)
                < PSI_MIN_BATCH_ROWS
            ):
                continue

            baseline_values = (
                baseline_df[column]
                .dropna()
                .astype(str)
            )

            current_values = (
                current_df[column]
                .dropna()
                .astype(str)
            )

            if (
                baseline_values.empty
                or current_values.empty
            ):
                continue

            if (
                baseline_values.nunique()
                < 2
            ):
                continue

            (
                baseline_bucketed,
                current_bucketed,
                keep_categories
            ) = bucket_rare_categories(
                baseline_values,
                current_values
            )

            if (
                baseline_bucketed is None
                or current_bucketed is None
            ):
                continue

            score = calculate_psi(
                baseline_bucketed,
                current_bucketed
            )

            psi_records.append({
                "claim_type":
                    claim_type,

                "feature":
                    field_name,

                "column":
                    column,

                "current_month":
                    current_month,

                "baseline_periods":
                    ",".join(
                        baseline_months
                    ),

                "baseline_rows":
                    len(baseline_df),

                "current_rows":
                    len(current_df),

                "baseline_categories":
                    len(keep_categories) + 1,

                "psi_score":
                    score,

                "psi_anomaly":
                    int(
                        score
                        >= PSI_MODERATE
                    ),

                "interpretation":
                    psi_interpretation(
                        score
                    ),
            })

    return psi_records


# ============================================================
# 10. RULE-BASED VALIDATION
# ============================================================

def calculate_rule_metrics(data):

    df = data["df"].copy()

    diagnosis_columns = data[
        "diagnosis_columns"
    ]

    procedure_columns = data[
        "procedure_columns"
    ]

    procedure_date_columns = data[
        "procedure_date_columns"
    ]

    # --------------------------------------------------------
    # Diagnosis/procedure presence
    # --------------------------------------------------------

    if diagnosis_columns:
        diagnosis_present = (
            df[diagnosis_columns]
            .notna()
            .any(axis=1)
        )
    else:
        diagnosis_present = pd.Series(
            False,
            index=df.index
        )

    if procedure_columns:
        procedure_present = (
            df[procedure_columns]
            .notna()
            .any(axis=1)
        )
    else:
        procedure_present = pd.Series(
            False,
            index=df.index
        )

    # Structural diagnosis-procedure mismatch:
    # one side is present while the other is completely absent.
    # This is intentionally labelled structural; a true clinical
    # diagnosis/procedure compatibility check requires a reference
    # mapping or ML model.
    df[
        "DIAGNOSIS_PROCEDURE_MISMATCH"
    ] = (
        diagnosis_present
        != procedure_present
    )

    # --------------------------------------------------------
    # Invalid ICD diagnosis code format
    # --------------------------------------------------------

    if diagnosis_columns:

        invalid_diag = pd.Series(
            False,
            index=df.index
        )

        for c in diagnosis_columns:

            nonempty = df[c].notna()

            invalid_here = (
                nonempty
                &
                ~valid_icd_series(
                    df[c]
                )
            )

            invalid_diag |= invalid_here

    else:
        invalid_diag = pd.Series(
            False,
            index=df.index
        )

    df["INVALID_ICD"] = invalid_diag

    # --------------------------------------------------------
    # Invalid procedure format
    # --------------------------------------------------------

    if procedure_columns:

        invalid_proc = pd.Series(
            False,
            index=df.index
        )

        for c in procedure_columns:

            nonempty = df[c].notna()

            invalid_here = (
                nonempty
                &
                ~valid_icd_series(
                    df[c]
                )
            )

            invalid_proc |= invalid_here

    else:
        invalid_proc = pd.Series(
            False,
            index=df.index
        )

    # --------------------------------------------------------
    # Invalid HCPCS format
    # --------------------------------------------------------

    if "HCPCS_CD" in df.columns:

        hcpcs_nonempty = (
            df["HCPCS_CD"].notna()
        )

        invalid_hcpcs = (
            hcpcs_nonempty
            &
            ~valid_hcpcs_series(
                df["HCPCS_CD"]
            )
        )

    else:
        invalid_hcpcs = pd.Series(
            False,
            index=df.index
        )

    df["INVALID_HCPCS"] = (
        invalid_proc
        | invalid_hcpcs
    )

    # --------------------------------------------------------
    # Impossible admission/discharge/date relationship
    # --------------------------------------------------------

    date_error = (
        (
            df["ADMISSION_DATE"].notna()
            &
            df["DISCHARGE_DATE"].notna()
            &
            (
                df["DISCHARGE_DATE"]
                <
                df["ADMISSION_DATE"]
            )
        )
        |
        (
            df["CLM_FROM_DT_TMP"]
            if "CLM_FROM_DT_TMP" in df.columns
            else pd.Series(False, index=df.index)
        )
    )

    # Also check CLM_THRU/CLM_FROM where available.
    if (
        "CLM_FROM_DT" in df.columns
        and "CLM_THRU_DT" in df.columns
    ):

        from_dt = pd.to_datetime(
            df["CLM_FROM_DT"],
            errors="coerce"
        )

        thru_dt = pd.to_datetime(
            df["CLM_THRU_DT"],
            errors="coerce"
        )

        date_error |= (
            from_dt.notna()
            &
            thru_dt.notna()
            &
            (
                thru_dt < from_dt
            )
        )

    df[
        "IMPOSSIBLE_DATE_RELATION"
    ] = date_error

    return df


# ============================================================
# 11. DATABASE
# ============================================================

def initialize_database(conn):

    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS claims_anomalies (
        anomaly_id INTEGER PRIMARY KEY AUTOINCREMENT,
        claim_type TEXT,
        provider_id TEXT,
        batch_month TEXT,

        robust_z_score REAL,
        robust_z_anomaly INTEGER,

        psi_score REAL,
        psi_anomaly INTEGER,

        anomaly_count INTEGER,
        severity TEXT,

        anomaly_reason TEXT,

        run_id TEXT,
        run_timestamp TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS claims_individual_metrics (
        metric_id INTEGER PRIMARY KEY AUTOINCREMENT,

        anomaly_id INTEGER,

        claim_type TEXT,
        provider_id TEXT,
        batch_month TEXT,

        anomaly_name TEXT,
        metric_name TEXT,
        metric_type TEXT,

        actual_value REAL,
        score REAL,
        threshold REAL,

        is_anomalous INTEGER,

        peer_group TEXT,
        baseline_periods TEXT,

        anomaly_reason TEXT,

        run_id TEXT,
        run_timestamp TEXT,

        FOREIGN KEY(anomaly_id)
            REFERENCES claims_anomalies(anomaly_id)
    )
    """)

    # Helpful indexes
    cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    idx_claim_anomaly_provider
    ON claims_anomalies(provider_id)
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    idx_claim_anomaly_type_month
    ON claims_anomalies(
        claim_type,
        batch_month
    )
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    idx_claim_metric_anomaly
    ON claims_individual_metrics(
        anomaly_id
    )
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    idx_claim_metric_provider
    ON claims_individual_metrics(
        provider_id
    )
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS
    idx_claim_metric_run
    ON claims_individual_metrics(
        run_id
    )
    """)

    conn.commit()


# ============================================================
# 12. BUILD ANOMALY REASONS
# ============================================================

def severity_from_count(
    count,
    max_z=None,
    max_psi=None
):

    if count <= 0:
        return "NORMAL"

    if (
        count >= 4
        or (
            max_z is not None
            and max_z >= 7
        )
        or (
            max_psi is not None
            and max_psi >= 0.75
        )
    ):
        return "HIGH"

    if count >= 2:
        return "MEDIUM"

    return "LOW"


def make_detailed_reason(
    anomaly_items
):

    if not anomaly_items:
        return ""

    return " | ".join(
        anomaly_items
    )


# ============================================================
# 13. MAIN
# ============================================================

def main():

    print("\n" + "=" * 80)
    print("CLAIMS ANOMALY DETECTION")
    print("=" * 80)

    print(
        "Run ID:",
        RUN_ID
    )

    print(
        "Output DB:",
        OUTPUT_DB
    )

    # --------------------------------------------------------
    # Open input SQLite database
    # --------------------------------------------------------

    print("\n" + "=" * 80)
    print("OPENING CLAIM SENTINEL INPUT DATABASE")
    print("=" * 80)

    if not os.path.isfile(INPUT_DB):
        raise FileNotFoundError(
            f"Input database not found:\n{INPUT_DB}"
        )

    input_conn = sqlite3.connect(INPUT_DB)

    print(
        "Input DB:",
        INPUT_DB
    )

    available_tables = get_sqlite_tables(input_conn)

    print("\nAvailable claim tables:")
    for table in available_tables:
        print("  -", table)

    # --------------------------------------------------------
    # Load all available claim types from SQLite
    # --------------------------------------------------------

    datasets = {}

    for claim_type, expected_table in CLAIM_TABLES.items():

        table_name = find_sqlite_table(
            input_conn,
            expected_table
        )

        if table_name is None:
            print(
                f"\nWARNING: {claim_type} table not found."
            )
            print(
                f"Expected table: {expected_table}"
            )
            continue

        data = load_claim_file(
            claim_type,
            input_conn,
            table_name
        )

        if data is not None:
            datasets[
                claim_type
            ] = data

    if not datasets:
        input_conn.close()
        raise RuntimeError(
            "No claim datasets could be loaded "
            "from claim_sentinel.db."
        )

    # --------------------------------------------------------
    # Open output anomaly DB
    # --------------------------------------------------------

    print("\n" + "=" * 80)
    print("OPENING ANOMALY DATABASE")
    print("=" * 80)

    conn = sqlite3.connect(
        OUTPUT_DB
    )

    initialize_database(
        conn
    )

    # --------------------------------------------------------
    # Global buffers
    # --------------------------------------------------------

    anomaly_rows = []
    metric_rows = []

    psi_population_records = []

    # --------------------------------------------------------
    # Process each claim type
    # --------------------------------------------------------

    for claim_type, data in datasets.items():

        print("\n" + "=" * 80)
        print(
            f"PROCESSING {claim_type.upper()}"
        )
        print("=" * 80)

        # ----------------------------------------------------
        # Claim-level
        # ----------------------------------------------------

        claim_level = create_claim_level(
            data
        )

        print(
            "Unique claims:",
            len(claim_level)
        )

        # ----------------------------------------------------
        # Provider-month
        # ----------------------------------------------------

        provider = (
            create_provider_month_metrics(
                data,
                claim_level
            )
        )

        print(
            "Provider-month rows:",
            len(provider)
        )

        # ----------------------------------------------------
        # Robust Z
        # ----------------------------------------------------

        provider = add_robust_z_scores(
            provider
        )

        # ----------------------------------------------------
        # PSI preparation
        # ----------------------------------------------------

        psi_df = prepare_psi_population(
            data
        )

        # ----------------------------------------------------
        # Rules
        # ----------------------------------------------------

        rule_df = calculate_rule_metrics(
            data
        )

        # ----------------------------------------------------
        # Aggregate rule anomalies to provider/month
        # ----------------------------------------------------

        rule_agg = (
            rule_df
            .groupby(
                [
                    "PROVIDER_ID_STD",
                    "BATCH_MONTH"
                ]
            )
            .agg(
                diagnosis_procedure_mismatch=(
                    "DIAGNOSIS_PROCEDURE_MISMATCH",
                    "sum"
                ),
                invalid_icd=(
                    "INVALID_ICD",
                    "sum"
                ),
                invalid_hcpcs=(
                    "INVALID_HCPCS",
                    "sum"
                ),
                impossible_date=(
                    "IMPOSSIBLE_DATE_RELATION",
                    "sum"
                ),
            )
            .reset_index()
        )

        provider = provider.merge(
            rule_agg,
            on=[
                "PROVIDER_ID_STD",
                "BATCH_MONTH"
            ],
            how="left"
        )

        for c in [
            "diagnosis_procedure_mismatch",
            "invalid_icd",
            "invalid_hcpcs",
            "impossible_date"
        ]:
            provider[c] = (
                provider[c]
                .fillna(0)
                .astype(int)
            )

        # ----------------------------------------------------
        # PSI
        # ----------------------------------------------------

        psi_records = calculate_rolling_psi(
            psi_df,
            claim_type
        )

        psi_population_records.extend(
            psi_records
        )

        psi_lookup = {}

        for record in psi_records:

            psi_lookup[
                (
                    record["claim_type"],
                    record["current_month"],
                    record["feature"]
                )
            ] = record

        # ----------------------------------------------------
        # Provider-month anomaly processing
        # ----------------------------------------------------

        psi_by_month = {}

        for p in psi_records:
            psi_by_month.setdefault(
                p["current_month"],
                []
            ).append(p)

        for _, row in provider.iterrows():

            provider_id = str(
                row["PROVIDER_ID_STD"]
            )

            month = str(
                row["BATCH_MONTH"]
            )

            robust_items = []
            psi_items = []
            rule_items = []

            robust_scores = []
            psi_scores = []

            # =================================================
            # Robust Z anomalies 1-10
            # =================================================

            for feature, anomaly_name in (
                ROBUST_ANOMALY_NAMES.items()
            ):

                z_col = (
                    feature
                    + "_Z"
                )

                if z_col not in row:
                    continue

                z = row[z_col]
                actual = row.get(
                    feature,
                    np.nan
                )

                is_anomaly = (
                    pd.notna(z)
                    and abs(float(z))
                    >= Z_THRESHOLD
                )

                if is_anomaly:

                    robust_scores.append(
                        abs(float(z))
                    )

                    robust_items.append(
                        f"{anomaly_name}: "
                        f"actual={safe_float(actual):.4f}; "
                        f"Robust_Z={float(z):.4f}; "
                        f"threshold=±{Z_THRESHOLD}; "
                        f"peer_group="
                        f"{claim_type}+{month}"
                    )

                metric_rows.append((
                    None,
                    claim_type,
                    provider_id,
                    month,
                    anomaly_name,
                    feature,
                    "ROBUST_Z",
                    safe_float(actual),
                    safe_float(z),
                    Z_THRESHOLD,
                    int(is_anomaly),
                    (
                        f"{claim_type}+{month}"
                    ),
                    (
                        f"Previous peer providers in "
                        f"same claim type/month; "
                        f"minimum peers={MIN_PEERS_FOR_Z}"
                    ),
                    (
                        robust_items[-1]
                        if is_anomaly
                        else (
                            "Normal relative to peer providers"
                            if pd.notna(z)
                            else
                            "Robust Z unavailable: "
                            "insufficient valid peer observations "
                            "or MAD=0"
                        )
                    ),
                    RUN_ID,
                    RUN_TIMESTAMP
                ))

            # ------------------------------------------------
            # Provider specialty behavior (#10)
            # ------------------------------------------------

            specialty_z = row.get(
                "specialty_behavior_Z",
                np.nan
            )

            specialty_actual = row.get(
                "claims_per_beneficiary",
                np.nan
            )

            specialty_anomaly = (
                pd.notna(specialty_z)
                and abs(float(specialty_z))
                >= Z_THRESHOLD
            )

            if specialty_anomaly:

                robust_scores.append(
                    abs(float(specialty_z))
                )

                robust_items.append(
                    "Provider specialty behavior anomaly: "
                    f"claims_per_beneficiary="
                    f"{safe_float(specialty_actual):.4f}; "
                    f"specialty Robust_Z="
                    f"{float(specialty_z):.4f}; "
                    f"threshold=±{Z_THRESHOLD}; "
                    f"specialty="
                    f"{row.get('SPECIALTY_STD', 'UNKNOWN')}"
                )

            metric_rows.append((
                None,
                claim_type,
                provider_id,
                month,
                "Provider specialty behavior anomaly",
                "specialty_behavior",
                "ROBUST_Z",
                safe_float(specialty_actual),
                safe_float(specialty_z),
                Z_THRESHOLD,
                int(specialty_anomaly),
                (
                    f"{claim_type}+{month}+"
                    f"specialty="
                    f"{row.get('SPECIALTY_STD', 'UNKNOWN')}"
                ),
                (
                    f"Previous providers in same "
                    f"claim type/month/specialty; "
                    f"minimum peers={MIN_PEERS_FOR_Z}"
                ),
                (
                    robust_items[-1]
                    if specialty_anomaly
                    else (
                        "Normal relative to providers "
                        "within the same specialty"
                        if pd.notna(specialty_z)
                        else
                        "Specialty Robust Z unavailable"
                    )
                ),
                RUN_ID,
                RUN_TIMESTAMP
            ))

            # =================================================
            # PSI 11-19
            #
            # PSI is population-level for claim type/month.
            # Store one metric record with provider_id NULL
            # for each PSI feature/month, rather than copying
            # the same population score to every provider.
            # =================================================

            current_psi_records = psi_by_month.get(
                month,
                []
            )

            for p in current_psi_records:

                psi_score = p["psi_score"]

                if psi_score >= PSI_MODERATE:

                    psi_scores.append(
                        float(psi_score)
                    )

                    psi_items.append(
                        f"{p['feature']}: "
                        f"PSI={psi_score:.4f}; "
                        f"threshold={PSI_MODERATE}; "
                        f"baseline="
                        f"{p['baseline_periods']}"
                    )

            # =================================================
            # Rule-based metrics 21-23
            # =================================================

            rule_values = [
                (
                    "Diagnosis–procedure mismatch",
                    "diagnosis_procedure_mismatch",
                    int(
                        row[
                            "diagnosis_procedure_mismatch"
                        ]
                    ),
                    (
                        "Rule-based structural mismatch: "
                        "diagnosis and procedure presence "
                        "do not agree."
                    )
                ),
                (
                    "Invalid ICD/HCPCS code",
                    "invalid_icd_hcpcs",
                    int(
                        row["invalid_icd"]
                        + row["invalid_hcpcs"]
                    ),
                    (
                        "Rule-based structural code validation "
                        "found ICD/HCPCS values that do not "
                        "match the expected code format."
                    )
                ),
                (
                    "Impossible admission/discharge/date relationship",
                    "impossible_date_relation",
                    int(
                        row["impossible_date"]
                    ),
                    (
                        "Admission/from date occurs after "
                        "discharge/through date."
                    )
                )
            ]

            for (
                anomaly_name,
                metric_name,
                actual,
                reason
            ) in rule_values:

                is_anomaly = actual > 0

                if is_anomaly:

                    rule_items.append(
                        f"{anomaly_name}: "
                        f"affected_rows={actual}; "
                        f"{reason}"
                    )

                metric_rows.append((
                    None,
                    claim_type,
                    provider_id,
                    month,
                    anomaly_name,
                    metric_name,
                    "RULE_BASED",
                    float(actual),
                    float(actual),
                    0.0,
                    int(is_anomaly),
                    "PROVIDER_MONTH",
                    "Current provider-month data",
                    (
                        reason
                        if is_anomaly
                        else "No rule violation detected"
                    ),
                    RUN_ID,
                    RUN_TIMESTAMP
                ))

            # =================================================
            # Provider-diagnosis behavior (#20)
            #
            # Robust signal:
            # provider's claims-per-beneficiary.
            #
            # PSI signal:
            # diagnosis distribution drift.
            # =================================================

            diagnosis_psi = next(
                (
                    r
                    for r in current_psi_records
                    if r["feature"]
                    == "Diagnosis distribution drift"
                ),
                None
            )

            provider_diagnosis_z = row.get(
                "claims_per_beneficiary_Z",
                np.nan
            )

            provider_diag_signal = (
                pd.notna(provider_diagnosis_z)
                and abs(
                    float(provider_diagnosis_z)
                ) >= Z_THRESHOLD
            )

            diagnosis_psi_signal = (
                diagnosis_psi is not None
                and diagnosis_psi["psi_score"]
                >= PSI_MODERATE
            )

            combined_provider_diagnosis = (
                provider_diag_signal
                and diagnosis_psi_signal
            )

            if combined_provider_diagnosis:

                z_value = abs(
                    float(provider_diagnosis_z)
                )

                psi_value = float(
                    diagnosis_psi[
                        "psi_score"
                    ]
                )

                robust_scores.append(
                    z_value
                )

                psi_scores.append(
                    psi_value
                )

                robust_items.append(
                    "Provider–diagnosis behavior anomaly: "
                    f"provider utilization Robust_Z="
                    f"{float(provider_diagnosis_z):.4f}"
                )

                psi_items.append(
                    "Provider–diagnosis behavior anomaly: "
                    f"diagnosis PSI="
                    f"{psi_value:.4f}"
                )

            metric_rows.append((
                None,
                claim_type,
                provider_id,
                month,
                "Provider–diagnosis behavior anomaly",
                "provider_diagnosis_combined",
                "ROBUST_Z + PSI",
                safe_float(
                    row.get(
                        "claims_per_beneficiary",
                        np.nan
                    )
                ),
                safe_float(
                    provider_diagnosis_z
                ),
                Z_THRESHOLD,
                int(combined_provider_diagnosis),
                (
                    f"{claim_type}+{month}"
                ),
                (
                    diagnosis_psi[
                        "baseline_periods"
                    ]
                    if diagnosis_psi
                    else
                    "No diagnosis PSI baseline"
                ),
                (
                    "Both provider utilization behavior "
                    "and diagnosis population distribution "
                    "were anomalous."
                    if combined_provider_diagnosis
                    else
                    "Combined condition not met."
                ),
                RUN_ID,
                RUN_TIMESTAMP
            ))

            # =================================================
            # Multi-metric provider anomaly (#24)
            # =================================================

            multi_count = (
                len(robust_items)
                + len(rule_items)
                + len(psi_items)
            )

            multi_anomaly = (
                multi_count >= 2
            )

            if multi_anomaly:

                combined_reason = (
                    "Multi-metric provider anomaly: "
                    f"{multi_count} independent signals "
                    "were abnormal."
                )

            else:

                combined_reason = (
                    "Fewer than two independent anomaly "
                    "signals."
                )

            metric_rows.append((
                None,
                claim_type,
                provider_id,
                month,
                "Multi-metric provider anomaly",
                "multi_metric_signal_count",
                "RULE_BASED_COMBINATION",
                float(multi_count),
                float(multi_count),
                2.0,
                int(multi_anomaly),
                "PROVIDER_MONTH",
                "Current provider-month anomaly signals",
                combined_reason,
                RUN_ID,
                RUN_TIMESTAMP
            ))

            # =================================================
            # Final provider-month anomaly record
            # =================================================

            anomaly_count = multi_count

            robust_z_anomaly = (
                len(robust_items) > 0
            )

            psi_anomaly = (
                len(psi_items) > 0
            )

            max_z = (
                max(robust_scores)
                if robust_scores
                else None
            )

            max_psi = (
                max(psi_scores)
                if psi_scores
                else None
            )

            final_anomaly = (
                anomaly_count > 0
            )

            if not final_anomaly:
                continue

            severity = severity_from_count(
                anomaly_count,
                max_z,
                max_psi
            )

            reason_parts = []

            if robust_items:
                reason_parts.append(
                    "ROBUST Z: "
                    + " ; ".join(
                        robust_items
                    )
                )

            if psi_items:
                reason_parts.append(
                    "PSI: "
                    + " ; ".join(
                        psi_items
                    )
                )

            if rule_items:
                reason_parts.append(
                    "RULE-BASED: "
                    + " ; ".join(
                        rule_items
                    )
                )

            reason_parts.append(
                "Multi-metric combination: "
                f"{anomaly_count} abnormal signals; "
                f"severity={severity}."
            )

            anomaly_rows.append({
                "claim_type":
                    claim_type,

                "provider_id":
                    provider_id,

                "batch_month":
                    month,

                "robust_z_score":
                    max_z,

                "robust_z_anomaly":
                    int(robust_z_anomaly),

                "psi_score":
                    max_psi,

                "psi_anomaly":
                    int(psi_anomaly),

                "anomaly_count":
                    anomaly_count,

                "severity":
                    severity,

                "anomaly_reason":
                    " | ".join(
                        reason_parts
                    ),

                "run_id":
                    RUN_ID,

                "run_timestamp":
                    RUN_TIMESTAMP
            })

        print(
            "Finished:",
            claim_type
        )

    # ========================================================
    # STORE POPULATION-LEVEL PSI METRICS ONCE PER
    # CLAIM TYPE / MONTH / FEATURE
    #
    # PSI is a population-distribution metric, so it is not
    # duplicated for every provider.
    # ========================================================

    for p in psi_records:

        psi_score = p["psi_score"]

        psi_anomaly = (
            psi_score >= PSI_MODERATE
        )

        metric_rows.append((
            None,
            claim_type,
            None,
            p["current_month"],
            p["feature"],
            p["column"],
            "PSI",
            None,
            safe_float(psi_score),
            PSI_MODERATE,
            int(psi_anomaly),
            "CLAIM_TYPE_POPULATION",
            p["baseline_periods"],
            (
                f"{p['interpretation']}; "
                f"baseline_rows={p['baseline_rows']}; "
                f"current_rows={p['current_rows']}; "
                f"baseline_categories="
                f"{p['baseline_categories']}"
            ),
            RUN_ID,
            RUN_TIMESTAMP
        ))

    # ========================================================
    # 14. INSERT FINAL ANOMALIES
    # ========================================================

    print("\n" + "=" * 80)
    print("STORING CLAIM ANOMALIES")
    print("=" * 80)

    cursor = conn.cursor()

    if anomaly_rows:

        cursor.executemany("""
        INSERT INTO claims_anomalies (
            claim_type,
            provider_id,
            batch_month,
            robust_z_score,
            robust_z_anomaly,
            psi_score,
            psi_anomaly,
            anomaly_count,
            severity,
            anomaly_reason,
            run_id,
            run_timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                r["claim_type"],
                r["provider_id"],
                r["batch_month"],
                r["robust_z_score"],
                r["robust_z_anomaly"],
                r["psi_score"],
                r["psi_anomaly"],
                r["anomaly_count"],
                r["severity"],
                r["anomaly_reason"],
                r["run_id"],
                r["run_timestamp"]
            )
            for r in anomaly_rows
        ])

        # Retrieve anomaly IDs for this run and map them
        # back to provider/month/type.
        rows = cursor.execute("""
        SELECT
            anomaly_id,
            claim_type,
            provider_id,
            batch_month
        FROM claims_anomalies
        WHERE run_id = ?
        """, (RUN_ID,)).fetchall()

        anomaly_id_map = {
            (
                str(r[1]),
                str(r[2]),
                str(r[3])
            ): r[0]
            for r in rows
        }

        # Fill anomaly_id for provider-level metric rows.
        # Population PSI rows intentionally remain NULL because
        # they are claim-type/month population metrics.
        updated_metric_rows = []

        for metric in metric_rows:

            claim_type = str(
                metric[1]
            )

            provider_id = (
                None
                if metric[2] is None
                else str(metric[2])
            )

            month = str(
                metric[3]
            )

            anomaly_id = anomaly_id_map.get(
                (
                    claim_type,
                    provider_id,
                    month
                )
            )

            updated_metric_rows.append(
                (
                    anomaly_id,
                    *metric[1:]
                )
            )

        metric_rows = updated_metric_rows

    else:

        print(
            "No provider-month anomalies found."
        )

        # There may still be individual metric rows.
        # Keep them with NULL anomaly_id.

    # ========================================================
    # 15. VALIDATE METRIC ROWS
    # ========================================================

    print(
        "\nPrepared individual metric records:",
        len(metric_rows)
    )

    bad_rows = [
        (
            i,
            len(row),
            row
        )
        for i, row in enumerate(
            metric_rows
        )
        if len(row) != 16
    ]

    if bad_rows:

        print(
            "\nERROR: Invalid metric rows:"
        )

        for i, length, row in bad_rows[:10]:

            print(
                f"Row {i}: contains {length} values"
            )

            print(row)

        raise ValueError(
            f"{len(bad_rows)} metric rows do not "
            f"contain exactly 16 values."
        )

    print(
        "All metric rows validated:",
        len(metric_rows),
        "rows x 16 columns"
    )

    # ========================================================
    # 16. INSERT INDIVIDUAL METRICS
    # ========================================================

    if metric_rows:

        cursor.executemany("""
        INSERT INTO claims_individual_metrics (
            anomaly_id,
            claim_type,
            provider_id,
            batch_month,
            anomaly_name,
            metric_name,
            metric_type,
            actual_value,
            score,
            threshold,
            is_anomalous,
            peer_group,
            baseline_periods,
            anomaly_reason,
            run_id,
            run_timestamp
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?
        )
        """, metric_rows)

    conn.commit()

    # ========================================================
    # 17. POPULATION PSI-ONLY ANOMALIES
    #
    # PSI is population-level. If there is significant PSI
    # drift in a month but no provider-specific anomaly row,
    # create a population anomaly record with provider_id=NULL.
    # ========================================================

    existing_population = set()

    existing = cursor.execute("""
    SELECT
        claim_type,
        batch_month
    FROM claims_anomalies
    WHERE run_id = ?
      AND provider_id IS NULL
    """, (RUN_ID,)).fetchall()

    for r in existing:
        existing_population.add(
            (
                str(r[0]),
                str(r[1])
            )
        )

    population_rows = []

    psi_by_month = {}

    for p in psi_population_records:

        if p["psi_anomaly"]:

            key = (
                p["claim_type"],
                p["current_month"]
            )

            psi_by_month.setdefault(
                key,
                []
            ).append(p)

    for key, records in psi_by_month.items():

        claim_type, month = key

        if key in existing_population:
            continue

        max_psi = max(
            float(
                r["psi_score"]
            )
            for r in records
        )

        reasons = []

        for r in records:

            reasons.append(
                f"{r['feature']}: "
                f"PSI={r['psi_score']:.4f}; "
                f"baseline="
                f"{r['baseline_periods']}"
            )

        count = len(records)

        severity = severity_from_count(
            count,
            None,
            max_psi
        )

        population_rows.append((
            claim_type,
            None,
            month,
            None,
            0,
            max_psi,
            1,
            count,
            severity,
            (
                "Population-level distribution drift: "
                + " ; ".join(reasons)
            ),
            RUN_ID,
            RUN_TIMESTAMP
        ))

    if population_rows:

        cursor.executemany("""
        INSERT INTO claims_anomalies (
            claim_type,
            provider_id,
            batch_month,
            robust_z_score,
            robust_z_anomaly,
            psi_score,
            psi_anomaly,
            anomaly_count,
            severity,
            anomaly_reason,
            run_id,
            run_timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, population_rows)

        conn.commit()

    # ========================================================
    # 18. SUMMARY
    # ========================================================

    total_anomalies = cursor.execute("""
    SELECT COUNT(*)
    FROM claims_anomalies
    WHERE run_id = ?
    """, (RUN_ID,)).fetchone()[0]

    robust_anomalies = cursor.execute("""
    SELECT COUNT(*)
    FROM claims_anomalies
    WHERE run_id = ?
      AND robust_z_anomaly = 1
    """, (RUN_ID,)).fetchone()[0]

    psi_anomalies = cursor.execute("""
    SELECT COUNT(*)
    FROM claims_anomalies
    WHERE run_id = ?
      AND psi_anomaly = 1
    """, (RUN_ID,)).fetchone()[0]

    high_count = cursor.execute("""
    SELECT COUNT(*)
    FROM claims_anomalies
    WHERE run_id = ?
      AND severity = 'HIGH'
    """, (RUN_ID,)).fetchone()[0]

    medium_count = cursor.execute("""
    SELECT COUNT(*)
    FROM claims_anomalies
    WHERE run_id = ?
      AND severity = 'MEDIUM'
    """, (RUN_ID,)).fetchone()[0]

    low_count = cursor.execute("""
    SELECT COUNT(*)
    FROM claims_anomalies
    WHERE run_id = ?
      AND severity = 'LOW'
    """, (RUN_ID,)).fetchone()[0]

    metric_count = cursor.execute("""
    SELECT COUNT(*)
    FROM claims_individual_metrics
    WHERE run_id = ?
    """, (RUN_ID,)).fetchone()[0]

    print("\n" + "=" * 80)
    print("CLAIMS ANOMALY DETECTION COMPLETE")
    print("=" * 80)

    print(
        "Database:",
        OUTPUT_DB
    )

    print(
        "Run ID:",
        RUN_ID
    )

    print(
        "Claim datasets processed:",
        ", ".join(
            datasets.keys()
        )
    )

    print(
        "Current-run anomaly records:",
        total_anomalies
    )

    print(
        "  Robust Z anomaly records:",
        robust_anomalies
    )

    print(
        "  PSI anomaly records:",
        psi_anomalies
    )

    print(
        "  HIGH:",
        high_count
    )

    print(
        "  MEDIUM:",
        medium_count
    )

    print(
        "  LOW:",
        low_count
    )

    print(
        "Current-run individual metric records:",
        metric_count
    )

    # --------------------------------------------------------
    # Show top anomalies
    # --------------------------------------------------------

    top = cursor.execute("""
    SELECT
        anomaly_id,
        claim_type,
        provider_id,
        batch_month,
        robust_z_score,
        psi_score,
        anomaly_count,
        severity,
        anomaly_reason
    FROM claims_anomalies
    WHERE run_id = ?
    ORDER BY anomaly_count DESC,
             severity DESC
    LIMIT 20
    """, (RUN_ID,)).fetchall()

    if top:

        print("\n" + "=" * 80)
        print("TOP CLAIM ANOMALIES")
        print("=" * 80)

        for r in top:

            print(
                "\n",
                "anomaly_id:",
                r[0],
                "| type:",
                r[1],
                "| provider:",
                r[2],
                "| month:",
                r[3],
                "| Robust Z:",
                r[4],
                "| PSI:",
                r[5],
                "| count:",
                r[6],
                "| severity:",
                r[7]
            )

            print(
                "Reason:",
                r[8]
            )

    conn.close()
    input_conn.close()

    print(
        "\nInput and output database connections closed."
    )


if __name__ == "__main__":
    main()
