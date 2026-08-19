# ============================================================
# DRUG ANOMALY DETECTION
# ============================================================
#
# INPUTS
#
# 1. claim_sentinel.db
#       part_d_prescriber_drug
#       part_d_drug_lists
#       part_d_grand_totals
#
# The SQLite tables replace the old:
#       Drug-provider_50000.xlsx
#       Drug-list.xlsx
#       Grand-total.xlsx
#
# OUTPUT
#
# anomalies.db
#
# TABLES
#
#   drug_anomalies
#   drug_individual_metrics
#
# ============================================================
#
# ANOMALIES
#
# 1. Provider-drug utilization anomaly
#       Robust Z
#
# 2. Cost-per-claim anomaly
#       Robust Z
#
# 3. Claims-per-beneficiary anomaly
#       Robust Z
#
# 4. Days-supply anomaly
#       Robust Z
#
# 6. Multi-metric provider anomaly
#       Robust Z + rule combination
#
# 7. Provider specialty anomaly
#       PSI
#
# 8. Geographic/provider anomaly
#       PSI
#
# 12. Yearly population/trend anomaly
#       Robust Z using part_d_grand_totals
#
# ============================================================


import os
import sqlite3
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# ============================================================
# 1. PATHS
# ============================================================

DATA_FOLDER = r"C:/Users/sweth/OneDrive/Pictures/Desktop/Congnizant"

# ============================================================
# INPUT SQLITE DATABASE
# ============================================================

INPUT_DB = os.path.join(
    DATA_FOLDER,
    "claim_sentinel.db"
)

# SQLite source tables replacing the old Excel inputs.
SOURCE_TABLES = {
    "provider_drug": "part_d_prescriber_drug",
    "drug_list": "medicare_part_d_drug_lists",
    "yearly": "part_d_grand_totals",
}

OUTPUT_DB = os.path.join(
    DATA_FOLDER,
    "anomalies.db"
)


# ============================================================
# 2. SETTINGS
# ============================================================

Z_THRESHOLD = 3.5

MIN_GROUP_SIZE = 5

MIN_ROBUST_ANOMALIES = 2

PSI_MODERATE = 0.25

MIN_CATEGORY_SHARE = 0.02

MIN_PSI_CATEGORIES = 2

MIN_YEARLY_POINTS = 5


# ============================================================
# 3. RUN ID
# ============================================================

RUN_TIMESTAMP = datetime.now().strftime(
    "%Y-%m-%d %H:%M:%S"
)

RUN_ID = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)

# ============================================================
# INPUT SQLITE CONNECTION
# ============================================================

if not os.path.exists(INPUT_DB):
    raise FileNotFoundError(
        f"Input SQLite database not found:\n{INPUT_DB}"
    )

input_conn = sqlite3.connect(INPUT_DB)


def sqlite_table_exists(conn, table_name):
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,)
    ).fetchone()

    return row is not None


def read_sqlite_table(conn, table_name):
    """Read a complete SQLite table into a pandas DataFrame."""
    if not sqlite_table_exists(conn, table_name):
        available = [
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                ORDER BY name
                """
            ).fetchall()
        ]

        raise ValueError(
            f"Required SQLite table '{table_name}' was not found. "
            f"Available tables: {available}"
        )

    safe_table = '"' + table_name.replace('"', '""') + '"'

    return pd.read_sql_query(
        f"SELECT * FROM {safe_table}",
        conn
    )


print("\n" + "=" * 80)
print("INPUT SQLITE DATABASE")
print("=" * 80)
print("Input DB:", INPUT_DB)

available_input_tables = [
    row[0]
    for row in input_conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        ORDER BY name
        """
    ).fetchall()
]

print("Available tables:")
for table in available_input_tables:
    print("  -", table)



conn = sqlite3.connect(OUTPUT_DB)
cursor = conn.cursor()


cursor.execute("""
CREATE TABLE IF NOT EXISTS drug_individual_metrics (
    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
    anomaly_id INTEGER,
    provider_id TEXT,
    drug TEXT,
    metric_name TEXT,
    metric_type TEXT,
    actual_value REAL,
    score REAL,
    threshold REAL,
    is_anomalous INTEGER,
    peer_group TEXT,
    baseline_periods TEXT,
    run_timestamp TEXT,
    run_id TEXT,
    FOREIGN KEY(anomaly_id)
        REFERENCES drug_anomalies(anomaly_id)
)
""")
# ============================================================
# 4. FRIENDLY FEATURE NAMES
# ============================================================

FEATURE_LABELS = {

    "Tot_Clms":
        "Total claims",

    "Tot_30day_Fills":
        "30-day fills",

    "Tot_Day_Suply":
        "Days supplied",

    "Tot_Benes":
        "Beneficiaries",

    "Tot_Drug_Cst":
        "Total drug cost",

    "Cost_Per_Claim":
        "Cost per claim",

    "Claims_Per_Beneficiary":
        "Claims per beneficiary",

    "DaySupply_Per_Claim":
        "Days supply per claim",

    "Cost_Per_Beneficiary":
        "Cost per beneficiary"

}


# ============================================================
# 5. REQUIRED PROVIDER COLUMNS
# ============================================================

REQUIRED_PROVIDER_COLUMNS = [

    "Prscrbr_NPI",
    "Prscrbr_City",
    "Prscrbr_State_Abrvtn",
    "Prscrbr_Type",
    "Brnd_Name",
    "Gnrc_Name",
    "Tot_Clms",
    "Tot_30day_Fills",
    "Tot_Day_Suply",
    "Tot_Drug_Cst",
    "Tot_Benes"

]


# ============================================================
# 6. ROBUST Z-SCORE
# ============================================================

def robust_zscore(series):

    series = pd.to_numeric(
        series,
        errors="coerce"
    )

    median = series.median()

    mad = np.nanmedian(
        np.abs(series - median)
    )

    if pd.isna(mad) or mad == 0:

        return pd.Series(
            np.nan,
            index=series.index
        )

    return (
        0.6745
        *
        (series - median)
        /
        mad
    )


# ============================================================
# 7. GROUPED ROBUST Z-SCORE
# ============================================================

def grouped_robust_zscore(
    df,
    feature,
    group_column
):

    result = pd.Series(
        np.nan,
        index=df.index,
        dtype=float
    )

    for _, indexes in df.groupby(
        group_column
    ).groups.items():

        if len(indexes) < MIN_GROUP_SIZE:
            continue

        values = df.loc[
            indexes,
            feature
        ]

        result.loc[indexes] = (
            robust_zscore(values)
        )

    return result


# ============================================================
# 8. PSI FUNCTION
# ============================================================

def calculate_psi(
    baseline_series,
    current_series
):

    baseline = (
        baseline_series
        .dropna()
        .astype(str)
        .str.strip()
    )

    current = (
        current_series
        .dropna()
        .astype(str)
        .str.strip()
    )

    if baseline.empty or current.empty:
        return np.nan, None

    if baseline.nunique() < MIN_PSI_CATEGORIES:
        return np.nan, None

    # --------------------------------------------------------
    # Baseline distribution
    # --------------------------------------------------------

    baseline_counts = (
        baseline.value_counts()
    )

    baseline_share = (
        baseline_counts
        /
        baseline_counts.sum()
    )

    # --------------------------------------------------------
    # Keep meaningful baseline categories.
    # Rare categories are combined into OTHER_RARE.
    # --------------------------------------------------------

    keep_categories = set(
        baseline_share[
            baseline_share >= MIN_CATEGORY_SHARE
        ].index
    )

    if len(keep_categories) < MIN_PSI_CATEGORIES:
        return np.nan, None

    def bucket(value):

        if value in keep_categories:
            return value

        return "OTHER_RARE"

    baseline_bucketed = (
        baseline.map(bucket)
    )

    current_bucketed = (
        current.map(bucket)
    )

    baseline_distribution = (
        baseline_bucketed
        .value_counts(normalize=True)
    )

    current_distribution = (
        current_bucketed
        .value_counts(normalize=True)
    )

    categories = sorted(
        set(
            baseline_distribution.index
        )
        |
        set(
            current_distribution.index
        )
    )

    baseline_distribution = (
        baseline_distribution
        .reindex(
            categories,
            fill_value=0
        )
    )

    current_distribution = (
        current_distribution
        .reindex(
            categories,
            fill_value=0
        )
    )

    epsilon = 0.0001

    expected = np.clip(
        baseline_distribution.values,
        epsilon,
        None
    )

    actual = np.clip(
        current_distribution.values,
        epsilon,
        None
    )

    contribution = (
        (actual - expected)
        *
        np.log(
            actual / expected
        )
    )

    psi = contribution.sum()

    return float(psi), {
        "baseline_distribution":
            baseline_distribution,

        "current_distribution":
            current_distribution,

        "categories":
            categories
    }


# ============================================================
# ============================================================
# 9. LOAD PROVIDER-DRUG DATA FROM SQLITE
# ============================================================

print("\n" + "=" * 80)
print("1. LOADING PART D PRESCRIBER-DRUG DATA")
print("=" * 80)

provider_table = SOURCE_TABLES["provider_drug"]

provider_df = read_sqlite_table(
    input_conn,
    provider_table
)

# Clean column names.
provider_df.columns = [
    str(c).strip()
    for c in provider_df.columns
]

print(
    "SQLite table:",
    provider_table
)

print(
    "Provider-drug rows:",
    len(provider_df)
)

print(
    "Provider-drug columns:",
    provider_df.columns.tolist()
)

missing = [
    c
    for c in REQUIRED_PROVIDER_COLUMNS
    if c not in provider_df.columns
]

if missing:
    raise ValueError(
        "Missing provider-drug columns in "
        f"'{provider_table}':\n"
        + "\n".join(missing)
    )


# 10. CLEAN PROVIDER DATA
# ============================================================

provider_df = provider_df.dropna(
    subset=[
        "Prscrbr_NPI",
        "Gnrc_Name"
    ]
).copy()


numeric_columns = [

    "Tot_Clms",
    "Tot_30day_Fills",
    "Tot_Day_Suply",
    "Tot_Drug_Cst",
    "Tot_Benes"

]


for column in numeric_columns:

    provider_df[column] = pd.to_numeric(
        provider_df[column],
        errors="coerce"
    )


# Negative values are invalid
for column in numeric_columns:

    provider_df.loc[
        provider_df[column] < 0,
        column
    ] = np.nan


# ============================================================
# 11. DERIVED METRICS
# ============================================================

print(
    "\nCreating provider behavioral metrics..."
)


provider_df[
    "Cost_Per_Claim"
] = (

    provider_df["Tot_Drug_Cst"]
    /
    provider_df["Tot_Clms"].replace(
        0,
        np.nan
    )

)


provider_df[
    "Claims_Per_Beneficiary"
] = (

    provider_df["Tot_Clms"]
    /
    provider_df["Tot_Benes"].replace(
        0,
        np.nan
    )

)


provider_df[
    "DaySupply_Per_Claim"
] = (

    provider_df["Tot_Day_Suply"]
    /
    provider_df["Tot_Clms"].replace(
        0,
        np.nan
    )

)


provider_df[
    "Cost_Per_Beneficiary"
] = (

    provider_df["Tot_Drug_Cst"]
    /
    provider_df["Tot_Benes"].replace(
        0,
        np.nan
    )

)


# ============================================================
# ============================================================
# 12. LOAD MEDICARE PART D DRUG LIST
#     Replaces the old Drug-list Excel input.
# ============================================================

print("\n" + "=" * 80)
print("2. LOADING MEDICARE PART D DRUG LIST")
print("=" * 80)

drug_list_table = SOURCE_TABLES["drug_list"]

drug_list_df = read_sqlite_table(
    input_conn,
    drug_list_table
)

# Clean column names.
drug_list_df.columns = [
    str(c).strip()
    for c in drug_list_df.columns
]

# Remove completely empty columns/rows.
drug_list_df = drug_list_df.dropna(
    axis=1,
    how="all"
)

drug_list_df = drug_list_df.dropna(
    axis=0,
    how="all"
)

print(
    "\nSQLite table:",
    drug_list_table
)

print(
    "Drug-list rows:",
    len(drug_list_df)
)

print(
    "Drug-list columns:"
)

print(
    drug_list_df.columns.tolist()
)


# ============================================================
# NORMALIZE COLUMN NAMES
# ============================================================
# IMPORTANT:
# The SQLite drug-list table uses snake_case names:
#
#   drug_name
#   generic_name
#   opioid_flag
#   la_opioid_flag
#   antibiotic_flag
#   antipsychotic_flag
#   ndc_conflict_flag
#
# The old code compared these directly with display names such as
# "Drug Name" and "Generic Name", so it incorrectly reported all
# seven columns as missing.
#
# We normalize BOTH sides by:
#   1. converting to lowercase
#   2. removing spaces, underscores, hyphens and punctuation
#
# Therefore:
#   "Drug Name"       -> "drugname"
#   "drug_name"       -> "drugname"
#   "NDC Conflict Flag" -> "ndcconflictflag"
#   "ndc_conflict_flag" -> "ndcconflictflag"
#
# This makes the mapping work for both SQLite snake_case columns
# and Excel/display-style column names.
# ============================================================

import re


def normalize_column_name(column):
    """
    Convert a column name into a comparison-safe canonical form.

    Examples:
        Drug Name           -> drugname
        drug_name           -> drugname
        Generic Name        -> genericname
        generic_name        -> genericname
        NDC Conflict Flag   -> ndcconflictflag
        ndc_conflict_flag   -> ndcconflictflag
    """
    return re.sub(
        r"[^a-z0-9]+",
        "",
        str(column).strip().lower()
    )


normalized_columns = {}

for column in drug_list_df.columns:

    normalized = normalize_column_name(column)

    normalized_columns[
        normalized
    ] = column


# ============================================================
# REQUIRED DRUG-LIST COLUMNS
# ============================================================

DLSUM_REQUIRED = [

    "Drug Name",
    "Generic Name",
    "Opioid Flag",
    "LA Opioid Flag",
    "Antibiotic Flag",
    "Antipsychotic Flag",
    "NDC Conflict Flag"

]


# ============================================================
# FIND COLUMNS FLEXIBLY
# ============================================================

dlsum_column_mapping = {}

for required_column in DLSUM_REQUIRED:

    required_normalized = normalize_column_name(
        required_column
    )

    actual_column = normalized_columns.get(
        required_normalized
    )

    if actual_column is not None:

        dlsum_column_mapping[
            required_column
        ] = actual_column


# ============================================================
# CHECK REQUIRED COLUMNS
# ============================================================

missing_dlsum = [

    column

    for column in DLSUM_REQUIRED

    if column not in dlsum_column_mapping

]


if missing_dlsum:

    print(
        "\nDrug-list columns actually found:"
    )

    for column in drug_list_df.columns:

        print(
            "  -",
            repr(column)
        )

    print(
        "\nDetected column mapping:"
    )

    for required_column, actual_column in dlsum_column_mapping.items():

        print(
            f"  {required_column}  <--  {actual_column}"
        )

    raise ValueError(
        "\nMissing drug-list columns in "
        f"'{drug_list_table}':\n"
        +
        "\n".join(
            missing_dlsum
        )
    )


# ============================================================
# PRINT SUCCESSFUL COLUMN MAPPING
# ============================================================

print(
    "\nDrug-list column mapping:"
)

for required_column in DLSUM_REQUIRED:

    print(
        f"  {required_column}  <--  "
        f"{dlsum_column_mapping[required_column]}"
    )


# ============================================================
# RENAME TO STANDARD COLUMN NAMES
# ============================================================

rename_mapping = {

    actual_name: standard_name

    for standard_name, actual_name

    in dlsum_column_mapping.items()

}


drug_list_df = drug_list_df.rename(
    columns=rename_mapping
)


# ============================================================
# CLEAN DRUG-LIST VALUES
# ============================================================

for column in DLSUM_REQUIRED:

    drug_list_df[column] = (

        drug_list_df[column]
        .astype("string")
        .str.strip()

    )


# Replace textual nulls with real missing values.
NULL_TEXT_VALUES = {
    "",
    "nan",
    "none",
    "null",
    "na",
    "n/a"
}


for column in DLSUM_REQUIRED:

    drug_list_df[column] = drug_list_df[column].apply(
        lambda value:
            np.nan
            if pd.isna(value)
            or str(value).strip().lower() in NULL_TEXT_VALUES
            else str(value).strip()
    )


# Remove rows where both drug and generic name are empty.
drug_list_df = drug_list_df[
    ~(
        drug_list_df["Drug Name"].isna()
        &
        drug_list_df["Generic Name"].isna()
    )
].copy()


# ============================================================
# NORMALIZE GENERIC NAME FOR LOOKUP
# ============================================================

drug_list_df["_Generic_Name_Key"] = (

    drug_list_df["Generic Name"]
    .astype("string")
    .str.strip()
    .str.upper()

)


provider_df["_Generic_Name_Key"] = (

    provider_df["Gnrc_Name"]
    .astype("string")
    .str.strip()
    .str.upper()

)


# ============================================================
# CREATE LOOKUP
# ============================================================

dlsum_lookup = (

    drug_list_df[
        [
            "_Generic_Name_Key",
            "Drug Name",
            "Generic Name",
            "Opioid Flag",
            "LA Opioid Flag",
            "Antibiotic Flag",
            "Antipsychotic Flag",
            "NDC Conflict Flag"
        ]
    ]

    .dropna(
        subset=["_Generic_Name_Key"]
    )

    .drop_duplicates(
        subset=["_Generic_Name_Key"]
    )

)


# ============================================================
# MERGE DRUG CLASSIFICATION FLAGS INTO PROVIDER-DRUG DATA
# ============================================================
# This does not change the anomaly logic. It simply attaches the
# drug-list classification fields to each provider-drug record when
# a Generic Name match exists.
# ============================================================

provider_df = provider_df.merge(

    dlsum_lookup,

    on="_Generic_Name_Key",

    how="left",

    suffixes=("", "_DrugList")

)


provider_df.drop(
    columns=["_Generic_Name_Key"],
    inplace=True,
    errors="ignore"
)


print(
    "\nDrug-list classification matching complete."
)

print(
    "Usable drug-list records:",
    len(drug_list_df)
)

print(
    "Provider-drug rows after classification merge:",
    len(provider_df)
)

for flag_column in [
    "Opioid Flag",
    "LA Opioid Flag",
    "Antibiotic Flag",
    "Antipsychotic Flag",
    "NDC Conflict Flag"
]:

    if flag_column in provider_df.columns:

        matched = int(
            provider_df[flag_column]
            .notna()
            .sum()
        )

        print(
            f"  {flag_column}: "
            f"{matched} matched provider-drug rows"
        )


# ============================================================
# 14. ROBUST Z FEATURES
# ============================================================


# ============================================================

ROBUST_FEATURES = [

    "Tot_Clms",
    "Tot_30day_Fills",
    "Tot_Day_Suply",
    "Tot_Benes",
    "Tot_Drug_Cst",
    "Cost_Per_Claim",
    "Claims_Per_Beneficiary",
    "DaySupply_Per_Claim",
    "Cost_Per_Beneficiary"

]


# ============================================================
# 15. CALCULATE GROUPED ROBUST Z
# ============================================================

print("\n" + "=" * 80)
print("3. CALCULATING GROUPED ROBUST Z-SCORES")
print("=" * 80)


for feature in ROBUST_FEATURES:

    print(
        "Processing:",
        feature
    )

    provider_df[
        feature + "_Robust_Z"
    ] = grouped_robust_zscore(
        provider_df,
        feature,
        "Gnrc_Name"
    )


# ============================================================
# 16. PSI — PROVIDER SPECIALTY
#
# Definition:
#
# For each generic drug:
#
# CURRENT:
#   specialty distribution of providers prescribing that drug
#
# BASELINE:
#   specialty distribution across all providers in dataset
#
# This tells us whether the provider specialty composition of
# a drug is substantially different from the overall provider
# population.
#
# This is PEER-POPULATION PSI, not historical rolling PSI.
# ============================================================

print("\n" + "=" * 80)
print("4. CALCULATING PROVIDER SPECIALTY PSI")
print("=" * 80)


specialty_psi_by_drug = {}


global_specialty = (
    provider_df[
        "Prscrbr_Type"
    ]
    .dropna()
    .astype(str)
    .str.strip()
)


for drug, drug_group in provider_df.groupby(
    "Gnrc_Name"
):

    current_specialty = (
        drug_group[
            "Prscrbr_Type"
        ]
        .dropna()
        .astype(str)
        .str.strip()
    )


    psi, details = calculate_psi(
        global_specialty,
        current_specialty
    )


    specialty_psi_by_drug[
        drug
    ] = {

        "psi_score":
            psi,

        "baseline_periods":
            "Current overall provider population",

        "baseline_type":
            "Peer-population baseline",

        "feature":
            "Provider Specialty",

        "details":
            details

    }


# ============================================================
# 17. PSI — GEOGRAPHIC / STATE
#
# Same logic:
#
# BASELINE:
# overall state distribution
#
# CURRENT:
# state distribution for each drug
# ============================================================

print("\n" + "=" * 80)
print("5. CALCULATING GEOGRAPHIC / STATE PSI")
print("=" * 80)


state_psi_by_drug = {}


global_state = (
    provider_df[
        "Prscrbr_State_Abrvtn"
    ]
    .dropna()
    .astype(str)
    .str.strip()
)


for drug, drug_group in provider_df.groupby(
    "Gnrc_Name"
):

    current_state = (
        drug_group[
            "Prscrbr_State_Abrvtn"
        ]
        .dropna()
        .astype(str)
        .str.strip()
    )


    psi, details = calculate_psi(
        global_state,
        current_state
    )


    state_psi_by_drug[
        drug
    ] = {

        "psi_score":
            psi,

        "baseline_periods":
            "Current overall provider population",

        "baseline_type":
            "Peer-population baseline",

        "feature":
            "Geographic State",

        "details":
            details

    }


# ============================================================
# 18. BUILD PROVIDER-LEVEL PSI VALUES
#
# A drug can have one specialty PSI and one state PSI.
# Every provider prescribing that drug receives the same
# drug-level distribution PSI.
#
# This is intentional because PSI measures a DISTRIBUTION,
# not an individual provider.
# ============================================================

provider_df[
    "Specialty_PSI"
] = provider_df[
    "Gnrc_Name"
].map(

    lambda x:
        specialty_psi_by_drug
        .get(
            x,
            {}
        )
        .get(
            "psi_score",
            np.nan
        )

)


provider_df[
    "State_PSI"
] = provider_df[
    "Gnrc_Name"
].map(

    lambda x:
        state_psi_by_drug
        .get(
            x,
            {}
        )
        .get(
            "psi_score",
            np.nan
        )

)


provider_df[
    "Specialty_PSI_Anomaly"
] = (

    provider_df[
        "Specialty_PSI"
    ]
    >= PSI_MODERATE

)


provider_df[
    "State_PSI_Anomaly"
] = (

    provider_df[
        "State_PSI"
    ]
    >= PSI_MODERATE

)


# ============================================================
# ============================================================
# 19. LOAD PART D GRAND TOTALS
#     Replaces the old Grand-total Excel input.
# ============================================================

print("\n" + "=" * 80)
print("6. LOADING PART D GRAND TOTALS YEARLY DATA")
print("=" * 80)

yearly_table = SOURCE_TABLES["yearly"]

yearly_df = read_sqlite_table(
    input_conn,
    yearly_table
)

yearly_df.columns = [
    str(c).strip()
    for c in yearly_df.columns
]

yearly_df = yearly_df.dropna(
    axis=1,
    how="all"
)

yearly_df = yearly_df.dropna(
    axis=0,
    how="all"
)

print(
    "SQLite table:",
    yearly_table
)

print(
    "Grand-total rows:",
    len(yearly_df)
)

print(
    "Grand-total columns:",
    list(yearly_df.columns)
)


# 20. FIND YEAR COLUMN
# ============================================================

year_column = None

for column in yearly_df.columns:
    normalized = (
        str(column)
        .strip()
        .lower()
    )

    if (
        normalized in ("calendar year", "year", "calendar_year")
        or "calendar year" in normalized
        or normalized.endswith(" year")
    ):
        year_column = column
        break


if year_column is None:

    print(
        "\nWARNING: No year column found."
    )

    yearly_df = pd.DataFrame()


else:

    yearly_df[
        year_column
    ] = pd.to_numeric(
        yearly_df[
            year_column
        ],
        errors="coerce"
    )


# ============================================================
# 21. YEARLY ROBUST-Z FEATURES
# ============================================================

YEARLY_FEATURES = [

    "Total Claims",
    "Total Standardized 30-Day Fills",
    "Total Drug Cost",
    "Total Beneficiaries",
    "Total Prescribers",
    "Total Claims for Brand Drugs",
    "Total Drug Cost for Brand Drugs",
    "Total Claims for Generic Drugs",
    "Total Drug Cost for Generic Drugs",
    "Total Claims for Other Drugs",
    "Total Drug Cost for Other Drugs",
    "Total Claims for Antibiotic Drugs",
    "Total Drug Cost for Antibiotic Drugs",
    "Total Beneficiaries for Antibiotic Drugs",
    "Total Claims for Antipsychotic Drugs (Age 65+)",
    "Total Drug Cost for Antipsychotic Drugs  (Age 65+)",
    "Total Beneficiaries for Antipsychotic Drugs  (Age 65+)",
    "Total Claims for Opioid Drugs",
    "Total Drug Cost  for Opioid Drugs",
    "Total Beneficiaries for Opioid Drugs",
    "Total Claims for LA Opioid Drugs",
    "Total Drug Cost  for LA Opioid Drugs",
    "Total Beneficiaries for LA Opioid Drugs"

]


# ============================================================
# 22. DATABASE
# ============================================================

print("\n" + "=" * 80)
print("7. OPENING ANOMALY DATABASE")
print("=" * 80)


conn = sqlite3.connect(
    OUTPUT_DB
)


cursor = conn.cursor()


# ============================================================
# 23. CREATE MAIN TABLE
# ============================================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS drug_anomalies (

    anomaly_id INTEGER PRIMARY KEY AUTOINCREMENT,

    provider_id TEXT,

    drug TEXT,

    robust_z_score REAL,

    robust_z_anomaly INTEGER,

    psi_score REAL,

    psi_anomaly INTEGER,

    anomaly_count INTEGER,

    severity TEXT,

    anomaly_reason TEXT,

    run_timestamp TEXT,
    run_id TEXT

)
""")


# ============================================================
# 24. CREATE INDIVIDUAL METRIC TABLE
# ============================================================

cursor.execute("""
CREATE TABLE IF NOT EXISTS drug_individual_metrics (

    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,

    anomaly_id INTEGER,

    provider_id TEXT,

    drug TEXT,

    metric_name TEXT,

    metric_type TEXT,

    actual_value REAL,

    score REAL,

    threshold REAL,

    is_anomalous INTEGER,

    peer_group TEXT,

    baseline_periods TEXT,

    run_timestamp TEXT,

    run_id TEXT,

    FOREIGN KEY(anomaly_id)
        REFERENCES drug_anomalies(anomaly_id)

)
""")


conn.commit()


# ============================================================
# 25. DATABASE MIGRATION
#
# Existing records are NOT deleted.
# ============================================================

def ensure_column(
    cursor,
    table,
    column,
    data_type
):

    info = cursor.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()


    existing = {
        row[1]
        for row in info
    }


    if column not in existing:

        cursor.execute(
            f"""
            ALTER TABLE {table}
            ADD COLUMN {column} {data_type}
            """
        )

        print(
            f"Added {column} to {table}"
        )


# Main table
ensure_column(
    cursor,
    "drug_anomalies",
    "run_timestamp",
    "TEXT"
)

ensure_column(
    cursor,
    "drug_anomalies",
    "run_id",
    "TEXT"
)


# Individual table
ensure_column(
    cursor,
    "drug_individual_metrics",
    "baseline_periods",
    "TEXT"
)


ensure_column(
    cursor,
    "drug_individual_metrics",
    "run_timestamp",
    "TEXT"
)

ensure_column(
    cursor,
    "drug_individual_metrics",
    "run_id",
    "TEXT"
)


conn.commit()


# ============================================================
# 26. PRECOMPUTE PEER STATISTICS
# ============================================================
# IMPORTANT PERFORMANCE FIX:
# The old code scanned the complete 50,000-row dataframe again
# for every provider and every abnormal metric. That made Section
# 27 extremely slow.
#
# Here we calculate median, MAD and peer_count ONCE for every
# (Gnrc_Name, feature) pair and reuse them.
# ============================================================

peer_stats = {}

for feature in ROBUST_FEATURES:

    temp = provider_df[
        ["Gnrc_Name", feature]
    ].copy()

    temp[feature] = pd.to_numeric(
        temp[feature],
        errors="coerce"
    )

    temp = temp.dropna(
        subset=["Gnrc_Name", feature]
    )

    feature_stats = {}

    for drug, group in temp.groupby(
        "Gnrc_Name",
        sort=False
    ):

        values = group[feature]

        if len(values) < MIN_GROUP_SIZE:
            continue

        median = float(values.median())

        mad = float(
            np.nanmedian(
                np.abs(values - median)
            )
        )

        if pd.isna(mad) or mad == 0:
            continue

        feature_stats[drug] = {
            "median": median,
            "mad": mad,
            "peer_count": int(len(values))
        }

    peer_stats[feature] = feature_stats


# ============================================================
# 27. BUILD AND STORE PROVIDER-DRUG ANOMALIES
# ============================================================
# Performance improvements:
#   1. No dataframe filtering inside the row loop.
#   2. Peer median/MAD come from peer_stats.
#   3. Individual metrics are accumulated and inserted with
#      executemany() rather than one SQLite INSERT per metric.
#
# IMPORTANT:
#   drug_anomalies = anomaly rows only.
#   drug_individual_metrics = ALL provider/drug metrics,
#                              including normal rows.
# ============================================================

print("\n" + "=" * 80)
print("8. BUILDING PROVIDER-DRUG ANOMALIES")
print("=" * 80)

anomaly_count_run = 0
current_anomaly_records = 0
current_metric_records = 0
metric_rows = []

for _, row in provider_df.iterrows():

    provider_id = str(
        row["Prscrbr_NPI"]
    )

    drug = str(
        row["Gnrc_Name"]
    )

    # --------------------------------------------------------
    # ROBUST Z
    # --------------------------------------------------------

    abnormal_metrics = []
    robust_scores = []

    for feature in ROBUST_FEATURES:

        z_column = (
            feature
            + "_Robust_Z"
        )

        z = row[z_column]

        if pd.isna(z):
            continue

        z = float(z)

        robust_scores.append(
            abs(z)
        )

        actual_value = row[feature]

        stats = peer_stats.get(
            feature,
            {}
        ).get(
            row["Gnrc_Name"]
        )

        peer_median = (
            stats["median"]
            if stats is not None
            else np.nan
        )

        peer_count = (
            stats["peer_count"]
            if stats is not None
            else 0
        )

        if abs(z) >= Z_THRESHOLD:

            direction = (
                "HIGH"
                if z > 0
                else "LOW"
            )

            feature_label = FEATURE_LABELS.get(
                feature,
                feature
            )

            if pd.notna(
                actual_value
            ):

                if pd.notna(
                    peer_median
                ):

                    reason = (
                        f"{feature_label} is unusually "
                        f"{direction}: "
                        f"provider={float(actual_value):.2f}, "
                        f"peer median={float(peer_median):.2f}, "
                        f"peer count={peer_count}, "
                        f"Robust Z={z:.2f}"
                    )

                else:

                    reason = (
                        f"{feature_label} is unusually "
                        f"{direction}: "
                        f"provider={float(actual_value):.2f}, "
                        f"Robust Z={z:.2f}"
                    )

            else:

                reason = (
                    f"{feature_label} is unusually "
                    f"{direction}: "
                    f"Robust Z={z:.2f}"
                )

            abnormal_metrics.append({
                "feature": feature,
                "reason": reason,
                "z": z,
                "actual": actual_value,
                "peer_median": peer_median,
                "peer_count": peer_count
            })


    # --------------------------------------------------------
    # Main Robust-Z anomaly
    # --------------------------------------------------------

    robust_anomaly = (
        len(abnormal_metrics)
        >= MIN_ROBUST_ANOMALIES
    )


    # --------------------------------------------------------
    # PSI
    # --------------------------------------------------------

    specialty_psi = row[
        "Specialty_PSI"
    ]

    state_psi = row[
        "State_PSI"
    ]

    specialty_psi_anomaly = (
        pd.notna(specialty_psi)
        and specialty_psi >= PSI_MODERATE
    )

    state_psi_anomaly = (
        pd.notna(state_psi)
        and state_psi >= PSI_MODERATE
    )

    psi_values = [
        float(x)
        for x in [
            specialty_psi,
            state_psi
        ]
        if pd.notna(x)
    ]

    max_psi = (
        max(psi_values)
        if psi_values
        else np.nan
    )

    psi_anomaly = (
        specialty_psi_anomaly
        or state_psi_anomaly
    )


    # --------------------------------------------------------
    # Combined anomaly count
    # --------------------------------------------------------

    anomaly_count = (
        len(abnormal_metrics)
        +
        int(specialty_psi_anomaly)
        +
        int(state_psi_anomaly)
    )


    # --------------------------------------------------------
    # Create main anomaly record only if abnormal
    # --------------------------------------------------------

    anomaly_id = None

    if anomaly_count > 0:

        if anomaly_count >= 5:
            severity = "HIGH"

        elif anomaly_count >= 3:
            severity = "MEDIUM"

        else:
            severity = "LOW"


        reasons = []

        # Detailed Robust-Z explanations
        for item in abnormal_metrics:
            reasons.append(
                item["reason"]
            )


        # Detailed specialty PSI explanation
        if specialty_psi_anomaly:

            specialty_baseline = (
                specialty_psi_by_drug[
                    drug
                ]
            )

            reasons.append(
                "Provider specialty distribution "
                "differs from the overall provider "
                "baseline: "
                f"PSI={float(specialty_psi):.4f}; "
                f"baseline={specialty_baseline['baseline_periods']}"
            )


        # Detailed geographic PSI explanation
        if state_psi_anomaly:

            state_baseline = (
                state_psi_by_drug[
                    drug
                ]
            )

            reasons.append(
                "Geographic/state distribution "
                "differs from the overall provider "
                "baseline: "
                f"PSI={float(state_psi):.4f}; "
                f"baseline={state_baseline['baseline_periods']}"
            )


        anomaly_reason = (
            "; ".join(reasons)
        )


        cursor.execute("""
        INSERT INTO drug_anomalies (
            provider_id,
            drug,
            robust_z_score,
            robust_z_anomaly,
            psi_score,
            psi_anomaly,
            anomaly_count,
            severity,
            anomaly_reason,
            run_timestamp,
            run_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (

            provider_id,

            drug,

            (
                max(robust_scores)
                if robust_scores
                else None
            ),

            int(
                robust_anomaly
            ),

            (
                float(max_psi)
                if pd.notna(max_psi)
                else None
            ),

            int(
                psi_anomaly
            ),

            int(
                anomaly_count
            ),

            severity,

            anomaly_reason,

            RUN_TIMESTAMP,

            RUN_ID

        ))

        anomaly_id = cursor.lastrowid

        anomaly_count_run += 1
        current_anomaly_records += 1


    # ========================================================
    # STORE ALL ROBUST METRICS
    # ========================================================
    #
    # Every provider/drug row gets its individual metrics.
    # anomaly_id is NULL if the provider/drug itself is normal.
    #
    # This is intentional so the database can later be used as
    # historical training/behavior data.
    # ========================================================

    for feature in ROBUST_FEATURES:

        z_column = (
            feature
            + "_Robust_Z"
        )

        z = row[z_column]

        actual_value = row[
            feature
        ]

        stats = peer_stats.get(
            feature,
            {}
        ).get(
            row["Gnrc_Name"]
        )

        peer_count = (
            stats["peer_count"]
            if stats is not None
            else 0
        )

        if pd.isna(z):

            score = None

            is_anomalous = 0

        else:

            score = float(z)

            is_anomalous = int(
                abs(float(z))
                >= Z_THRESHOLD
            )


        if peer_count > 0:

            baseline_text = (
                f"Generic drug peer group={drug}; "
                f"peer_count={peer_count}; "
                f"method=median/MAD grouped by Gnrc_Name"
            )

        else:

            baseline_text = (
                f"Generic drug peer group={drug}; "
                f"peer_count={peer_count}; "
                f"Robust Z unavailable because peer group "
                f"has fewer than {MIN_GROUP_SIZE} valid "
                f"observations or MAD=0"
            )


        metric_rows.append((

            anomaly_id,

            provider_id,

            drug,

            feature,

            "ROBUST_Z",

            (
                float(actual_value)
                if pd.notna(actual_value)
                else None
            ),

            score,

            Z_THRESHOLD,

            is_anomalous,

            "Gnrc_Name",

            baseline_text,

            RUN_TIMESTAMP,

            RUN_ID

        ))


    # ========================================================
    # STORE SPECIALTY PSI
    # ========================================================

    if pd.notna(
        specialty_psi
    ):

        specialty_baseline = (
            specialty_psi_by_drug[
                drug
            ]
        )

        metric_rows.append((

            anomaly_id,

            provider_id,

            drug,

            "Provider Specialty Distribution",

            "PSI",

            None,

            float(
                specialty_psi
            ),

            PSI_MODERATE,

            int(
                specialty_psi_anomaly
            ),

            "Prscrbr_Type",

            specialty_baseline[
                "baseline_periods"
            ],

            RUN_TIMESTAMP,

            RUN_ID

        ))


    # ========================================================
    # STORE STATE PSI
    # ========================================================

    if pd.notna(
        state_psi
    ):

        state_baseline = (
            state_psi_by_drug[
                drug
            ]
        )

        metric_rows.append((

            anomaly_id,

            provider_id,

            drug,

            "Geographic State Distribution",

            "PSI",

            None,

            float(
                state_psi
            ),

            PSI_MODERATE,

            int(
                state_psi_anomaly
            ),

            "Prscrbr_State_Abrvtn",

            state_baseline[
                "baseline_periods"
            ],

            RUN_TIMESTAMP,

            RUN_ID

        ))


# ============================================================
# BULK INSERT ALL PROVIDER-DRUG METRICS
# ============================================================

print(
    "\nPrepared individual metric records:",
    len(metric_rows)
)


# ============================================================
# VALIDATE METRIC ROWS BEFORE INSERT
# ============================================================

bad_rows = [
    (i, len(row), row)
    for i, row in enumerate(metric_rows)
    if len(row) != 13
]

if bad_rows:
    print("\nERROR: Invalid metric_rows detected:")

    for i, length, row in bad_rows[:10]:
        print(
            f"Row {i}: contains {length} values"
        )
        print(row)

    raise ValueError(
        f"{len(bad_rows)} metric rows do not contain "
        f"exactly 13 values."
    )


print(
    "All metric rows validated:",
    len(metric_rows),
    "rows × 13 columns"
)

cursor.executemany("""
INSERT INTO drug_individual_metrics (
    anomaly_id,
    provider_id,
    drug,
    metric_name,
    metric_type,
    actual_value,
    score,
    threshold,
    is_anomalous,
    peer_group,
    baseline_periods,
    run_timestamp,
    run_id
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", metric_rows)

conn.commit()

print(
    "Stored individual metric records:",
    len(metric_rows)
)

current_metric_records += len(metric_rows)


# ============================================================
# 28. PART D GRAND TOTALS YEARLY ROBUST Z
# ============================================================

print("\n" + "=" * 80)
print("9. YEARLY POPULATION / TREND ANOMALIES")
print("=" * 80)


yearly_anomaly_records = 0


if not yearly_df.empty:

    for feature in YEARLY_FEATURES:

        if feature not in yearly_df.columns:

            print(
                "Skipping missing:",
                feature
            )

            continue


        values = pd.to_numeric(
            yearly_df[
                feature
            ],
            errors="coerce"
        )


        if values.notna().sum() < MIN_YEARLY_POINTS:

            continue


        z_scores = robust_zscore(
            values
        )


        valid_years = (
            yearly_df[
                year_column
            ]
            .dropna()
            .astype(int)
            .tolist()
        )


        baseline_text = (

            "part_d_grand_totals historical yearly values; "
            f"years={','.join(map(str, valid_years))}"

        )


        for index in yearly_df.index:

            z = z_scores.loc[
                index
            ]


            if pd.isna(z):

                continue


            if abs(
                float(z)
            ) < Z_THRESHOLD:

                continue


            year = yearly_df.loc[
                index,
                year_column
            ]


            actual = values.loc[
                index
            ]


            direction = (
                "HIGH"
                if z > 0
                else "LOW"
            )


            if abs(z) >= 5:

                severity = "HIGH"

            elif abs(z) >= 4:

                severity = "MEDIUM"

            else:

                severity = "LOW"


            reason = (

                f"{feature} is unusually "
                f"{direction}: "
                f"year={int(year)}, "
                f"value={actual:.2f}, "
                f"Robust Z={z:.2f}"

            )


            cursor.execute("""
            INSERT INTO drug_anomalies (

                provider_id,
                drug,
                robust_z_score,
                robust_z_anomaly,
                psi_score,
                psi_anomaly,
                anomaly_count,
                severity,
                anomaly_reason,
                run_timestamp,
                run_id

            )

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            """, (

                None,

                "ALL_DRUGS_YEARLY",

                abs(float(z)),

                1,

                None,

                0,

                1,

                severity,

                reason,

                RUN_TIMESTAMP,

                RUN_ID

            ))


            anomaly_id = cursor.lastrowid


            cursor.execute("""
            INSERT INTO drug_individual_metrics (

                anomaly_id,
                provider_id,
                drug,
                metric_name,
                metric_type,
                actual_value,
                score,
                threshold,
                is_anomalous,
                peer_group,
                baseline_periods,
                run_timestamp,
                run_id

            )

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)

            """, (

                anomaly_id,

                None,

                "ALL_DRUGS_YEARLY",

                feature,

                "ROBUST_Z",

                float(actual),

                float(z),

                Z_THRESHOLD,

                1,

                "Calendar Year",

                baseline_text,

                RUN_TIMESTAMP,

                RUN_ID

            ))


            yearly_anomaly_records += 1

            current_anomaly_records += 1

            current_metric_records += 1


# ============================================================
# 29. INDEXES
# ============================================================

cursor.execute("""
CREATE INDEX IF NOT EXISTS
idx_drug_anomaly_provider
ON drug_anomalies(provider_id)
""")


cursor.execute("""
CREATE INDEX IF NOT EXISTS
idx_drug_anomaly_drug
ON drug_anomalies(drug)
""")


cursor.execute("""
CREATE INDEX IF NOT EXISTS
idx_drug_anomaly_run
ON drug_anomalies(run_timestamp)
""")


cursor.execute("""
CREATE INDEX IF NOT EXISTS
idx_drug_metric_anomaly
ON drug_individual_metrics(anomaly_id)
""")


cursor.execute("""
CREATE INDEX IF NOT EXISTS
idx_drug_metric_provider
ON drug_individual_metrics(provider_id)
""")


cursor.execute("""
CREATE INDEX IF NOT EXISTS
idx_drug_metric_type
ON drug_individual_metrics(metric_type)
""")


cursor.execute("""
CREATE INDEX IF NOT EXISTS
idx_drug_metric_run
ON drug_individual_metrics(run_timestamp)
""")


conn.commit()

# ============================================================
# 30. FINAL DATABASE COUNTS
# ============================================================

total_anomalies = cursor.execute("""
SELECT COUNT(*)
FROM drug_anomalies
""").fetchone()[0]


total_metrics = cursor.execute("""
SELECT COUNT(*)
FROM drug_individual_metrics
""").fetchone()[0]


total_robust = cursor.execute("""
SELECT COUNT(*)
FROM drug_anomalies
WHERE robust_z_anomaly = 1
""").fetchone()[0]


total_psi = cursor.execute("""
SELECT COUNT(*)
FROM drug_anomalies
WHERE psi_anomaly = 1
""").fetchone()[0]


high = cursor.execute("""
SELECT COUNT(*)
FROM drug_anomalies
WHERE severity = 'HIGH'
""").fetchone()[0]


medium = cursor.execute("""
SELECT COUNT(*)
FROM drug_anomalies
WHERE severity = 'MEDIUM'
""").fetchone()[0]


low = cursor.execute("""
SELECT COUNT(*)
FROM drug_anomalies
WHERE severity = 'LOW'
""").fetchone()[0]


# ============================================================
# 31. CURRENT RUN RESULTS
# ============================================================

current_results = pd.read_sql_query(
    """

    SELECT

        anomaly_id,
        provider_id,
        drug,
        robust_z_score,
        robust_z_anomaly,
        psi_score,
        psi_anomaly,
        anomaly_count,
        severity,
        anomaly_reason,
        run_timestamp

    FROM drug_anomalies

    WHERE run_id = ?

    ORDER BY

        CASE severity

            WHEN 'HIGH' THEN 1
            WHEN 'MEDIUM' THEN 2
            WHEN 'LOW' THEN 3
            ELSE 4

        END,

        anomaly_count DESC,

        robust_z_score DESC

    LIMIT 30

    """,

    conn,

    params=(
        RUN_ID,
    )

)


# ============================================================
# 32. PRINT FINAL SUMMARY
# ============================================================

print("\n" + "=" * 80)
print("DRUG ANOMALY DETECTION COMPLETE")
print("=" * 80)


print(
    "\nDatabase:",
    OUTPUT_DB
)


print(
    "Run timestamp:",
    RUN_TIMESTAMP
)


print(
    "Run ID:",
    RUN_ID
)


print(
    "\nProvider-drug rows:",
    len(provider_df)
)


print(
    "Drug-list rows:",
    len(drug_list_df)
)


print(
    "Grand-total rows:",
    len(yearly_df)
)


print(
    "\nTOTAL HISTORICAL ANOMALY RECORDS:",
    total_anomalies
)


print(
    "TOTAL HISTORICAL METRIC RECORDS:",
    total_metrics
)


print(
    "\nCURRENT RUN:"
)


print(
    "Anomaly records added:",
    current_anomaly_records
)


print(
    "Individual metric records added:",
    current_metric_records
)


print(
    "Yearly anomaly records:",
    yearly_anomaly_records
)


print(
    "\nRobust Z anomaly records:",
    total_robust
)


print(
    "PSI anomaly records:",
    total_psi
)


print(
    "\nSeverity:"
)


print(
    "HIGH:",
    high
)


print(
    "MEDIUM:",
    medium
)


print(
    "LOW:",
    low
)


# ============================================================
# 33. DISPLAY TOP CURRENT ANOMALIES
# ============================================================

print("\n" + "=" * 80)
print("TOP CURRENT-RUN DRUG ANOMALIES")
print("=" * 80)


if current_results.empty:

    print(
        "No anomalies detected."
    )

else:

    print(
        current_results.to_string(
            index=False
        )
    )


# ============================================================
# 34. CLOSE
# ============================================================

conn.close()
input_conn.close()


print(
    "\nInput and output database connections closed."
)


print(
    "Existing historical data was preserved."
)