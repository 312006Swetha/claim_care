# ============================================================
# PART D PHARMACY VOLUME RISK
# ============================================================
#
# INPUT DATABASE:
#     claim_sentinel.db
#
# INPUT TABLES:
#     medicare_part_d_drug_lists
#     part_d_grand_totals
#     part_d_prescriber_drug
#
# OUTPUT DATABASE:
#     volume_pharmacy.db
#
# OUTPUT TABLES:
#     pharmacy_overall_volume_risk
#     pharmacy_npi_volume_risk
#     pharmacy_drug_volume_risk
#     pharmacy_npi_drug_detail
#
# ============================================================


import sqlite3
import pandas as pd
import numpy as np
import os


# ============================================================
# CONFIGURATION
# ============================================================

INPUT_DB = "claim_sentinel.db"
OUTPUT_DB = "volume_pharmacy.db"

# Number of previous years used for historical baseline
ROLLING_WINDOW = 3


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def safe_numeric(series):
    """
    Convert values to numeric.

    Invalid/suppressed/non-numeric values become 0.
    """
    return pd.to_numeric(series, errors="coerce").fillna(0)


def zscore_to_risk(z):
    """
    Convert positive Z-score into a 0-100 risk score.

    Z < 1       -> 0
    1 <= Z < 2  -> 40
    2 <= Z < 3  -> 70
    Z >= 3      -> 100

    NaN remains NaN because there is not enough
    historical information to calculate risk.
    """

    if pd.isna(z):
        return np.nan

    if z < 1:
        return 0.0

    elif z < 2:
        return 40.0

    elif z < 3:
        return 70.0

    else:
        return 100.0


def percentile_to_risk(percentile):
    """
    Convert peer percentile to a 0-100 volume risk score.

    < 75th percentile  -> Low
    75-90               -> Medium
    90-95               -> High
    >=95                -> Critical
    """

    if pd.isna(percentile):
        return np.nan

    if percentile < 75:
        return 0.0

    elif percentile < 90:
        return 40.0

    elif percentile < 95:
        return 70.0

    else:
        return 100.0


def risk_level(score):
    """
    Convert risk score into risk category.
    """

    if pd.isna(score):
        return "Insufficient History"

    if score < 25:
        return "Low"

    elif score < 50:
        return "Medium"

    elif score < 75:
        return "High"

    else:
        return "Critical"



# ============================================================
# ROOT CAUSE + RECOMMENDATION ENGINE
# ============================================================

def generate_overall_root_cause(row):
    """Explain the strongest existing overall volume-risk driver."""

    if pd.isna(row["final_volume_risk_score"]):
        return (
            "Insufficient historical data to determine "
            "the root cause of volume risk."
        )

    drivers = {
        "Claims Volume": row["total_claims_risk"],
        "Standardized 30-Day Fills":
            row["total_standardized_30_day_fills_risk"],
        "Beneficiary Volume":
            row["total_beneficiaries_risk"],
        "Prescriber Volume":
            row["total_prescribers_risk"]
    }

    drivers = {
        k: v for k, v in drivers.items()
        if not pd.isna(v)
    }

    if not drivers:
        return "No identifiable volume-risk driver."

    primary_driver = max(drivers, key=drivers.get)
    primary_risk = drivers[primary_driver]

    if primary_risk >= 70:
        return (
            f"{primary_driver} is the primary root cause of "
            f"the elevated volume risk "
            f"(component risk score: {primary_risk:.0f})."
        )

    elif primary_risk >= 40:
        return (
            f"{primary_driver} is the main contributing factor "
            f"to the volume risk "
            f"(component risk score: {primary_risk:.0f})."
        )

    return (
        "No individual volume component shows a materially "
        "elevated risk."
    )


def generate_overall_recommendation(row):
    """Recommend an action from the existing final risk score."""

    if pd.isna(row["final_volume_risk_score"]):
        return (
            "Obtain sufficient historical data before performing "
            "volume-risk assessment."
        )

    score = row["final_volume_risk_score"]

    if score >= 75:
        return (
            "Perform priority utilization review. Validate the "
            "elevated claims, fills, beneficiary and prescriber "
            "volumes against the 3-year historical baseline and "
            "investigate the main contributing component."
        )

    elif score >= 50:
        return (
            "Review the elevated volume component against the "
            "3-year historical baseline and monitor whether "
            "the increase persists."
        )

    return (
        "Continue routine monitoring against the "
        "historical baseline."
    )


def generate_npi_root_cause(row):
    """Explain the strongest existing NPI peer-volume driver."""

    if pd.isna(row["volume_risk_score"]):
        return "NPI volume risk could not be determined."

    drivers = {
        "Claims Volume": row["claims_percentile"],
        "30-Day Fill Volume": row["fills_percentile"],
        "Day Supply Volume": row["day_supply_percentile"],
        "Beneficiary Volume": row["beneficiary_percentile"]
    }

    drivers = {
        k: v for k, v in drivers.items()
        if not pd.isna(v)
    }

    if not drivers:
        return "No identifiable NPI volume-risk driver."

    primary_driver = max(drivers, key=drivers.get)
    percentile = drivers[primary_driver]

    if percentile >= 95:
        return (
            f"{primary_driver} is the primary root cause. "
            f"The NPI is at the {percentile:.2f}th peer "
            f"percentile for this measure."
        )

    elif percentile >= 90:
        return (
            f"{primary_driver} is the main contributing factor, "
            f"with the NPI at the {percentile:.2f}th peer percentile."
        )

    elif percentile >= 75:
        return (
            f"{primary_driver} is elevated relative to the "
            f"NPI peer group ({percentile:.2f}th percentile)."
        )

    return (
        "No individual NPI volume component is materially elevated."
    )


def generate_npi_recommendation(row):
    """Recommend an action from the existing NPI volume score."""

    if pd.isna(row["volume_risk_score"]):
        return (
            "Insufficient peer data. Continue monitoring until "
            "a reliable peer comparison is available."
        )

    score = row["volume_risk_score"]

    if score >= 75:
        return (
            "Perform priority provider-level utilization review. "
            "Validate the NPI's claims, fills, day supply and "
            "beneficiary volume against peer providers and drill "
            "down into the highest-volume drugs."
        )

    elif score >= 50:
        return (
            "Review provider utilization against peer benchmarks "
            "and investigate the main elevated volume component."
        )

    return "Continue peer-level monitoring."


def generate_drug_root_cause(row):
    """Explain the strongest existing drug peer-volume driver."""

    if pd.isna(row["volume_risk_score"]):
        return "Drug volume risk could not be determined."

    drivers = {
        "Claims Volume": row["claims_percentile"],
        "30-Day Fill Volume": row["fills_percentile"],
        "Day Supply Volume": row["day_supply_percentile"],
        "Beneficiary Volume": row["beneficiary_percentile"]
    }

    drivers = {
        k: v for k, v in drivers.items()
        if not pd.isna(v)
    }

    if not drivers:
        return "No identifiable drug volume-risk driver."

    primary_driver = max(drivers, key=drivers.get)
    percentile = drivers[primary_driver]

    if percentile >= 95:
        return (
            f"{primary_driver} is the primary root cause of "
            f"the elevated drug volume risk, with the drug at "
            f"the {percentile:.2f}th peer percentile."
        )

    elif percentile >= 90:
        return (
            f"{primary_driver} is the main contributing factor, "
            f"with the drug at the {percentile:.2f}th peer percentile."
        )

    elif percentile >= 75:
        return (
            f"{primary_driver} is elevated relative to the "
            f"drug peer group ({percentile:.2f}th percentile)."
        )

    return (
        "No individual drug volume component is materially elevated."
    )


def generate_drug_recommendation(row):
    """Recommend an action from the existing drug volume score."""

    if pd.isna(row["volume_risk_score"]):
        return (
            "Continue monitoring until sufficient peer comparison "
            "data is available."
        )

    score = row["volume_risk_score"]

    if score >= 75:
        return (
            "Perform targeted drug utilization review. Examine "
            "prescriber concentration, beneficiary distribution, "
            "claims and day supply to determine whether the "
            "elevated peer-relative volume is justified."
        )

    elif score >= 50:
        return (
            "Review the drug's utilization distribution across "
            "prescribers and beneficiaries and monitor for "
            "sustained elevated volume."
        )

    return (
        "Continue routine monitoring against the current "
        "drug peer baseline."
    )


def generate_detail_root_cause(row):
    """Provide supporting NPI-drug root cause."""

    claims = row["Tot_Clms"]

    if pd.isna(claims) or claims <= 0:
        return "No measurable claim-volume contribution."

    return (
        "This NPI-drug combination contributes to the provider's "
        "pharmacy utilization volume."
    )


def generate_detail_recommendation(row):
    """Provide supporting NPI-drug recommendation."""

    claims = row["Tot_Clms"]

    if pd.isna(claims) or claims <= 0:
        return "No immediate action required."

    return (
        "Review this NPI-drug combination when the associated "
        "NPI or drug volume risk is elevated."
    )


def calculate_rolling_zscore(
    df,
    column,
    window=3
):
    """
    Calculate a historical rolling Z-score.

    IMPORTANT:
    shift(1) means the current year is excluded
    from its own historical baseline.

    Example for 2024:

        2021
        2022
        2023
          ↓
        baseline
          ↓
        compare 2024
    """

    rolling_mean = (
        df[column]
        .shift(1)
        .rolling(
            window=window,
            min_periods=window
        )
        .mean()
    )

    rolling_std = (
        df[column]
        .shift(1)
        .rolling(
            window=window,
            min_periods=window
        )
        .std()
    )

    zscore = np.where(
        rolling_std.notna() & (rolling_std > 0),

        (
            df[column] - rolling_mean
        ) / rolling_std,

        np.nan
    )

    return (
        rolling_mean,
        rolling_std,
        pd.Series(
            zscore,
            index=df.index
        )
    )


# ============================================================
# OUTPUT DATABASE
# ============================================================
# IMPORTANT:
# The existing volume_pharmacy.db is NOT deleted.
# Existing tables with the same names are replaced below by the
# existing pandas to_sql(..., if_exists="replace") logic.
# ============================================================

if os.path.exists(OUTPUT_DB):

    print(
        f"Existing output database found: {OUTPUT_DB}"
    )

    print(
        "The database file will NOT be deleted."
    )

else:

    print(
        f"Creating output database: {OUTPUT_DB}"
    )


# ============================================================
# CONNECT TO SOURCE DATABASE
# ============================================================

if not os.path.exists(INPUT_DB):

    raise FileNotFoundError(
        f"Source database not found: {INPUT_DB}"
    )


source_conn = sqlite3.connect(INPUT_DB)


# ============================================================
# CHECK SOURCE TABLES
# ============================================================

source_tables = pd.read_sql_query(
    """
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
    """,
    source_conn
)["name"].tolist()


required_tables = [
    "medicare_part_d_drug_lists",
    "part_d_grand_totals",
    "part_d_prescriber_drug"
]


missing_tables = [
    table
    for table in required_tables
    if table not in source_tables
]


if missing_tables:

    source_conn.close()

    raise ValueError(
        "Missing required tables: "
        + ", ".join(missing_tables)
    )


print("\nAll required source tables found.")


# ============================================================
# ============================================================
# PART A
# OVERALL PART D HISTORICAL VOLUME RISK
# ============================================================
# ============================================================


print(
    "\n=============================================="
)

print(
    "PART A: OVERALL HISTORICAL VOLUME RISK"
)

print(
    "=============================================="
)


# ============================================================
# LOAD GRAND TOTALS
# ============================================================

grand = pd.read_sql_query(
    """
    SELECT *
    FROM part_d_grand_totals
    ORDER BY calendar_year
    """,
    source_conn
)


print(
    f"Grand-total records loaded: {len(grand)}"
)


# ============================================================
# VALIDATE YEAR COLUMN
# ============================================================

if "calendar_year" not in grand.columns:

    source_conn.close()

    raise ValueError(
        "calendar_year column is required "
        "in part_d_grand_totals."
    )


grand["calendar_year"] = pd.to_numeric(
    grand["calendar_year"],
    errors="coerce"
)


grand = (
    grand
    .dropna(subset=["calendar_year"])
    .sort_values("calendar_year")
    .reset_index(drop=True)
)


grand["calendar_year"] = (
    grand["calendar_year"]
    .astype(int)
)


# ============================================================
# NUMERIC COLUMNS
# ============================================================

grand_numeric_columns = [

    "total_claims",

    "total_standardized_30_day_fills",

    "total_drug_cost",

    "total_beneficiaries",

    "total_prescribers",

    "total_claims_for_antibiotic_drugs",

    "total_drug_cost_for_antibiotic_drugs",

    "total_beneficiaries_for_antibiotic_drugs",

    "total_claims_for_antipsychotic_drugs_age65plus",

    "total_drug_cost_for_antipsychotic_drugs_age65plus",

    "total_beneficiaries_for_antipsychotic_drugs_age65plus",

    "total_claims_for_opioid_drugs",

    "total_drug_cost_for_opioid_drugs",

    "total_beneficiaries_for_opioid_drugs",

    "total_claims_for_la_opioid_drugs",

    "total_drug_cost_for_la_opioid_drugs",

    "total_beneficiaries_for_la_opioid_drugs"
]


for col in grand_numeric_columns:

    if col in grand.columns:

        grand[col] = safe_numeric(
            grand[col]
        )


# ============================================================
# MAIN HISTORICAL VOLUME METRICS
# ============================================================

baseline_metrics = [

    "total_claims",

    "total_standardized_30_day_fills",

    "total_beneficiaries",

    "total_prescribers"
]


# ============================================================
# CALCULATE 3-YEAR ROLLING HISTORICAL BASELINE
# ============================================================

print(
    "\nCalculating 3-year rolling historical baseline..."
)


for col in baseline_metrics:

    (
        rolling_mean,
        rolling_std,
        zscore
    ) = calculate_rolling_zscore(
        grand,
        col,
        ROLLING_WINDOW
    )


    grand[
        f"{col}_rolling_mean"
    ] = rolling_mean


    grand[
        f"{col}_rolling_std"
    ] = rolling_std


    grand[
        f"{col}_zscore"
    ] = zscore


    # --------------------------------------------------------
    # Only positive deviations are volume-spike risk.
    #
    # Negative Z-score means volume is lower than baseline.
    # That is not treated as high volume risk.
    # --------------------------------------------------------

    grand[
        f"{col}_positive_zscore"
    ] = (
        grand[f"{col}_zscore"]
        .clip(lower=0)
    )


    grand[
        f"{col}_risk"
    ] = (
        grand[f"{col}_positive_zscore"]
        .apply(zscore_to_risk)
    )


# ============================================================
# HIGH-RISK DRUG CATEGORY HISTORICAL METRICS
# ============================================================

category_metrics = {

    "antibiotic":
        "total_claims_for_antibiotic_drugs",

    "antipsychotic":
        "total_claims_for_antipsychotic_drugs_age65plus",

    "opioid":
        "total_claims_for_opioid_drugs",

    "la_opioid":
        "total_claims_for_la_opioid_drugs"
}


for category, col in category_metrics.items():

    if col not in grand.columns:

        # If a category doesn't exist,
        # create empty columns.
        grand[col] = 0


    (
        rolling_mean,
        rolling_std,
        zscore
    ) = calculate_rolling_zscore(
        grand,
        col,
        ROLLING_WINDOW
    )


    grand[
        f"{category}_rolling_mean"
    ] = rolling_mean


    grand[
        f"{category}_rolling_std"
    ] = rolling_std


    grand[
        f"{category}_zscore"
    ] = zscore


    grand[
        f"{category}_positive_zscore"
    ] = (
        grand[f"{category}_zscore"]
        .clip(lower=0)
    )


    grand[
        f"{category}_risk"
    ] = (
        grand[f"{category}_positive_zscore"]
        .apply(zscore_to_risk)
    )


# ============================================================
# GENERAL VOLUME RISK SCORE
# ============================================================

grand["volume_risk_score"] = (

      0.35
    * grand["total_claims_risk"]

    + 0.35
    * grand[
        "total_standardized_30_day_fills_risk"
    ]

    + 0.20
    * grand[
        "total_beneficiaries_risk"
    ]

    + 0.10
    * grand[
        "total_prescribers_risk"
    ]
)


# ============================================================
# HIGH-RISK DRUG UTILIZATION SCORE
#
# This is kept SEPARATE from the pure volume score.
# ============================================================

grand["high_risk_drug_volume_score"] = (

      0.30
    * grand["antibiotic_risk"]

    + 0.20
    * grand["antipsychotic_risk"]

    + 0.30
    * grand["opioid_risk"]

    + 0.20
    * grand["la_opioid_risk"]
)


# ============================================================
# FINAL OVERALL SCORE
#
# Only calculate final score when historical baseline exists.
# ============================================================

grand["final_volume_risk_score"] = (

      0.85
    * grand["volume_risk_score"]

    + 0.15
    * grand["high_risk_drug_volume_score"]
)


# ------------------------------------------------------------
# If any required historical metric is unavailable,
# mark final score as unavailable.
# ------------------------------------------------------------

required_risk_columns = [

    "total_claims_risk",

    "total_standardized_30_day_fills_risk",

    "total_beneficiaries_risk",

    "total_prescribers_risk"
]


history_available = (
    grand[required_risk_columns]
    .notna()
    .all(axis=1)
)


grand.loc[
    ~history_available,
    "final_volume_risk_score"
] = np.nan


# ============================================================
# RISK LEVEL
# ============================================================

grand["volume_risk_level"] = (
    grand["final_volume_risk_score"]
    .apply(risk_level)
)


# ============================================================
# BASELINE INFORMATION
# ============================================================

grand["baseline_type"] = np.where(

    history_available,

    "3-year rolling historical baseline",

    "Insufficient historical data"
)


grand["baseline_years_used"] = np.where(

    history_available,

    ROLLING_WINDOW,

    0
)


# ============================================================
# YEAR-OVER-YEAR CHANGE
# ============================================================

for col in baseline_metrics:

    grand[
        f"{col}_yoy_change_pct"
    ] = (
        grand[col]
        .pct_change()
        * 100
    )


# ============================================================
# FINAL OVERALL OUTPUT
# ============================================================

overall_columns = [

    "calendar_year",

    # Current volume
    "total_claims",

    "total_standardized_30_day_fills",

    "total_beneficiaries",

    "total_prescribers",

    # Claims baseline
    "total_claims_rolling_mean",

    "total_claims_rolling_std",

    "total_claims_zscore",

    "total_claims_risk",

    # Fills baseline
    "total_standardized_30_day_fills_rolling_mean",

    "total_standardized_30_day_fills_rolling_std",

    "total_standardized_30_day_fills_zscore",

    "total_standardized_30_day_fills_risk",

    # Beneficiary baseline
    "total_beneficiaries_rolling_mean",

    "total_beneficiaries_rolling_std",

    "total_beneficiaries_zscore",

    "total_beneficiaries_risk",

    # Prescriber baseline
    "total_prescribers_rolling_mean",

    "total_prescribers_rolling_std",

    "total_prescribers_zscore",

    "total_prescribers_risk",

    # High-risk drug categories
    "antibiotic_zscore",

    "antibiotic_risk",

    "antipsychotic_zscore",

    "antipsychotic_risk",

    "opioid_zscore",

    "opioid_risk",

    "la_opioid_zscore",

    "la_opioid_risk",

    # Final scores
    "volume_risk_score",

    "high_risk_drug_volume_score",

    "final_volume_risk_score",

    "volume_risk_level",

    "baseline_type",

    "baseline_years_used"
]


overall_result = (
    grand[overall_columns]
    .copy()
)


# ============================================================
# ROOT CAUSE + RECOMMENDATION
# ============================================================

overall_result["root_cause"] = (
    overall_result.apply(
        generate_overall_root_cause,
        axis=1
    )
)

overall_result["recommendation"] = (
    overall_result.apply(
        generate_overall_recommendation,
        axis=1
    )
)


# ============================================================
# ============================================================
# PART B
# NPI CURRENT PEER VOLUME RISK
# ============================================================
# ============================================================

print(
    "\n=============================================="
)

print(
    "PART B: NPI CURRENT PEER VOLUME RISK"
)

print(
    "=============================================="
)


# ============================================================
# LOAD PRESCRIBER-DRUG DATA
# ============================================================

prescriber = pd.read_sql_query(
    """
    SELECT
        Prscrbr_NPI,
        Prscrbr_Last_Org_Name,
        Prscrbr_First_Name,
        Prscrbr_City,
        Prscrbr_State_Abrvtn,
        Prscrbr_Type,
        Brnd_Name,
        Gnrc_Name,
        Tot_Clms,
        Tot_30day_Fills,
        Tot_Day_Suply,
        Tot_Drug_Cst,
        Tot_Benes
    FROM part_d_prescriber_drug
    """,
    source_conn
)


print(
    f"Prescriber-drug rows loaded: "
    f"{len(prescriber)}"
)


# ============================================================
# CLEAN NUMERIC DATA
# ============================================================

prescriber_numeric = [

    "Tot_Clms",

    "Tot_30day_Fills",

    "Tot_Day_Suply",

    "Tot_Drug_Cst",

    "Tot_Benes"
]


for col in prescriber_numeric:

    prescriber[col] = safe_numeric(
        prescriber[col]
    )


# ============================================================
# CLEAN NPI
# ============================================================

prescriber["Prscrbr_NPI"] = (

    prescriber["Prscrbr_NPI"]

    .astype(str)

    .str.strip()

)


# ============================================================
# LOAD DRUG LIST
# ============================================================

drug_list = pd.read_sql_query(
    """
    SELECT
        drug_name,
        generic_name,
        opioid_flag,
        la_opioid_flag,
        antibiotic_flag,
        antipsychotic_flag,
        ndc_conflict_flag
    FROM medicare_part_d_drug_lists
    """,
    source_conn
)


print(
    f"Drug-list rows loaded: "
    f"{len(drug_list)}"
)


# ============================================================
# NORMALIZE DRUG NAMES
# ============================================================

def normalize_drug_name(value):

    if pd.isna(value):

        return ""

    return (
        str(value)
        .upper()
        .strip()
        .replace("  ", " ")
    )


prescriber["drug_join_name"] = (
    prescriber["Brnd_Name"]
    .apply(normalize_drug_name)
)


drug_list["drug_join_name"] = (
    drug_list["drug_name"]
    .apply(normalize_drug_name)
)


# ============================================================
# REMOVE EMPTY DRUG NAMES FROM JOIN
# ============================================================

drug_list = drug_list[
    drug_list["drug_join_name"] != ""
].copy()


# ============================================================
# REMOVE DUPLICATE DRUG NAMES
# ============================================================

drug_list = (
    drug_list
    .drop_duplicates(
        subset=["drug_join_name"]
    )
)


# ============================================================
# JOIN DRUG FLAGS
# ============================================================

prescriber = prescriber.merge(

    drug_list[
        [
            "drug_join_name",

            "opioid_flag",

            "la_opioid_flag",

            "antibiotic_flag",

            "antipsychotic_flag",

            "ndc_conflict_flag"
        ]
    ],

    on="drug_join_name",

    how="left"
)


# ============================================================
# CONVERT DRUG FLAGS TO 0/1
# ============================================================

flag_columns = [

    "opioid_flag",

    "la_opioid_flag",

    "antibiotic_flag",

    "antipsychotic_flag",

    "ndc_conflict_flag"
]


for col in flag_columns:

    prescriber[col] = (

        prescriber[col]

        .fillna("N")

        .astype(str)

        .str.upper()

        .str.strip()

        .eq("Y")

        .astype(int)

    )


# ============================================================
# CALCULATE FLAGGED CLAIM VOLUMES
# ============================================================

prescriber["opioid_claims"] = (

    prescriber["Tot_Clms"]

    * prescriber["opioid_flag"]

)


prescriber["la_opioid_claims"] = (

    prescriber["Tot_Clms"]

    * prescriber["la_opioid_flag"]

)


prescriber["antibiotic_claims"] = (

    prescriber["Tot_Clms"]

    * prescriber["antibiotic_flag"]

)


prescriber["antipsychotic_claims"] = (

    prescriber["Tot_Clms"]

    * prescriber["antipsychotic_flag"]

)


prescriber["ndc_conflict_claims"] = (

    prescriber["Tot_Clms"]

    * prescriber["ndc_conflict_flag"]

)


# ============================================================
# AGGREGATE TO NPI
# ============================================================

npi = (

    prescriber

    .groupby(

        [
            "Prscrbr_NPI",

            "Prscrbr_Last_Org_Name",

            "Prscrbr_First_Name",

            "Prscrbr_City",

            "Prscrbr_State_Abrvtn",

            "Prscrbr_Type"
        ],

        dropna=False

    )

    .agg(

        total_claims=(
            "Tot_Clms",
            "sum"
        ),

        total_fills=(
            "Tot_30day_Fills",
            "sum"
        ),

        total_day_supply=(
            "Tot_Day_Suply",
            "sum"
        ),

        total_drug_cost=(
            "Tot_Drug_Cst",
            "sum"
        ),

        total_beneficiaries=(
            "Tot_Benes",
            "sum"
        ),

        opioid_claims=(
            "opioid_claims",
            "sum"
        ),

        la_opioid_claims=(
            "la_opioid_claims",
            "sum"
        ),

        antibiotic_claims=(
            "antibiotic_claims",
            "sum"
        ),

        antipsychotic_claims=(
            "antipsychotic_claims",
            "sum"
        ),

        ndc_conflict_claims=(
            "ndc_conflict_claims",
            "sum"
        )
    )

    .reset_index()
)


# ============================================================
# CALCULATE CLAIM SHARES
# ============================================================

npi["opioid_claim_share_pct"] = np.where(

    npi["total_claims"] > 0,

    npi["opioid_claims"]
    / npi["total_claims"]
    * 100,

    0
)


npi["la_opioid_claim_share_pct"] = np.where(

    npi["total_claims"] > 0,

    npi["la_opioid_claims"]
    / npi["total_claims"]
    * 100,

    0
)


npi["antibiotic_claim_share_pct"] = np.where(

    npi["total_claims"] > 0,

    npi["antibiotic_claims"]
    / npi["total_claims"]
    * 100,

    0
)


npi["antipsychotic_claim_share_pct"] = np.where(

    npi["total_claims"] > 0,

    npi["antipsychotic_claims"]
    / npi["total_claims"]
    * 100,

    0
)


npi["ndc_conflict_claim_share_pct"] = np.where(

    npi["total_claims"] > 0,

    npi["ndc_conflict_claims"]
    / npi["total_claims"]
    * 100,

    0
)


# ============================================================
# CURRENT NPI PEER PERCENTILES
#
# IMPORTANT:
# There is NO year in part_d_prescriber_drug.
#
# Therefore this is a CURRENT PEER BASELINE,
# NOT a historical rolling baseline.
# ============================================================

npi["claims_percentile"] = (

    npi["total_claims"]

    .rank(
        pct=True,
        method="average"
    )

    * 100
)


npi["fills_percentile"] = (

    npi["total_fills"]

    .rank(
        pct=True,
        method="average"
    )

    * 100
)


npi["day_supply_percentile"] = (

    npi["total_day_supply"]

    .rank(
        pct=True,
        method="average"
    )

    * 100
)


npi["beneficiary_percentile"] = (

    npi["total_beneficiaries"]

    .rank(
        pct=True,
        method="average"
    )

    * 100
)


# ============================================================
# PEER PERCENTILE → RISK
# ============================================================

npi["claims_volume_risk"] = (

    npi["claims_percentile"]

    .apply(percentile_to_risk)
)


npi["fills_volume_risk"] = (

    npi["fills_percentile"]

    .apply(percentile_to_risk)
)


npi["day_supply_volume_risk"] = (

    npi["day_supply_percentile"]

    .apply(percentile_to_risk)
)


npi["beneficiary_volume_risk"] = (

    npi["beneficiary_percentile"]

    .apply(percentile_to_risk)
)


# ============================================================
# PURE NPI VOLUME RISK
#
# IMPORTANT:
# No drug-category risk is mixed into this score.
# ============================================================

npi["volume_risk_score"] = (

      0.40
    * npi["claims_volume_risk"]

    + 0.30
    * npi["fills_volume_risk"]

    + 0.20
    * npi["day_supply_volume_risk"]

    + 0.10
    * npi["beneficiary_volume_risk"]
)


# ============================================================
# HIGH-RISK DRUG UTILIZATION SCORE
#
# This is a SEPARATE score.
# ============================================================

npi["high_risk_drug_utilization_score"] = (

      0.25
    * npi[
        "opioid_claim_share_pct"
    ].rank(pct=True)
    * 100

    + 0.15
    * npi[
        "la_opioid_claim_share_pct"
    ].rank(pct=True)
    * 100

    + 0.20
    * npi[
        "antibiotic_claim_share_pct"
    ].rank(pct=True)
    * 100

    + 0.20
    * npi[
        "antipsychotic_claim_share_pct"
    ].rank(pct=True)
    * 100

    + 0.20
    * npi[
        "ndc_conflict_claim_share_pct"
    ].rank(pct=True)
    * 100
)


# ============================================================
# NPI VOLUME RISK LEVEL
# ============================================================

npi["volume_risk_level"] = (

    npi["volume_risk_score"]

    .apply(risk_level)
)


# ============================================================
# BASELINE TYPE
# ============================================================

npi["baseline_type"] = (
    "Current peer baseline"
)


npi["historical_baseline_available"] = 0


# ============================================================
# NPI ROOT CAUSE + RECOMMENDATION
# ============================================================

npi["root_cause"] = (
    npi.apply(
        generate_npi_root_cause,
        axis=1
    )
)

npi["recommendation"] = (
    npi.apply(
        generate_npi_recommendation,
        axis=1
    )
)


# ============================================================
# ============================================================
# PART C
# DRUG-LEVEL CURRENT PEER VOLUME RISK
# ============================================================
# ============================================================

print(
    "\n=============================================="
)

print(
    "PART C: DRUG CURRENT PEER VOLUME RISK"
)

print(
    "=============================================="
)


drug = (

    prescriber

    .groupby(

        [
            "Brnd_Name",
            "Gnrc_Name"
        ],

        dropna=False

    )

    .agg(

        total_claims=(
            "Tot_Clms",
            "sum"
        ),

        total_fills=(
            "Tot_30day_Fills",
            "sum"
        ),

        total_day_supply=(
            "Tot_Day_Suply",
            "sum"
        ),

        total_drug_cost=(
            "Tot_Drug_Cst",
            "sum"
        ),

        total_beneficiaries=(
            "Tot_Benes",
            "sum"
        ),

        opioid_flag=(
            "opioid_flag",
            "max"
        ),

        la_opioid_flag=(
            "la_opioid_flag",
            "max"
        ),

        antibiotic_flag=(
            "antibiotic_flag",
            "max"
        ),

        antipsychotic_flag=(
            "antipsychotic_flag",
            "max"
        ),

        ndc_conflict_flag=(
            "ndc_conflict_flag",
            "max"
        )
    )

    .reset_index()
)


# ============================================================
# DRUG PEER PERCENTILES
# ============================================================

drug["claims_percentile"] = (

    drug["total_claims"]

    .rank(
        pct=True,
        method="average"
    )

    * 100
)


drug["fills_percentile"] = (

    drug["total_fills"]

    .rank(
        pct=True,
        method="average"
    )

    * 100
)


drug["day_supply_percentile"] = (

    drug["total_day_supply"]

    .rank(
        pct=True,
        method="average"
    )

    * 100
)


drug["beneficiary_percentile"] = (

    drug["total_beneficiaries"]

    .rank(
        pct=True,
        method="average"
    )

    * 100
)


# ============================================================
# PURE DRUG VOLUME SCORE
# ============================================================

drug["volume_risk_score"] = (

      0.35
    * drug["claims_percentile"]

    + 0.30
    * drug["fills_percentile"]

    + 0.20
    * drug["day_supply_percentile"]

    + 0.15
    * drug["beneficiary_percentile"]
)


# ============================================================
# DRUG VOLUME RISK LEVEL
# ============================================================

drug["volume_risk_level"] = (

    drug["volume_risk_score"]

    .apply(risk_level)
)


# ============================================================
# DRUG CATEGORY FLAGS
#
# These are kept as attributes, NOT added to volume score.
# ============================================================

drug["high_risk_flag_count"] = (

      drug["opioid_flag"]

    + drug["la_opioid_flag"]

    + drug["antibiotic_flag"]

    + drug["antipsychotic_flag"]

    + drug["ndc_conflict_flag"]
)


drug["baseline_type"] = (
    "Current drug peer baseline"
)


drug["historical_baseline_available"] = 0


# ============================================================
# DRUG ROOT CAUSE + RECOMMENDATION
# ============================================================

drug["root_cause"] = (
    drug.apply(
        generate_drug_root_cause,
        axis=1
    )
)

drug["recommendation"] = (
    drug.apply(
        generate_drug_recommendation,
        axis=1
    )
)


# ============================================================
# PART D
# SUPPORTING NPI-DRUG DETAIL
# ============================================================

detail_columns = [

    "Prscrbr_NPI",

    "Prscrbr_Last_Org_Name",

    "Prscrbr_First_Name",

    "Prscrbr_City",

    "Prscrbr_State_Abrvtn",

    "Prscrbr_Type",

    "Brnd_Name",

    "Gnrc_Name",

    "Tot_Clms",

    "Tot_30day_Fills",

    "Tot_Day_Suply",

    "Tot_Drug_Cst",

    "Tot_Benes",

    "opioid_flag",

    "la_opioid_flag",

    "antibiotic_flag",

    "antipsychotic_flag",

    "ndc_conflict_flag",

    "opioid_claims",

    "la_opioid_claims",

    "antibiotic_claims",

    "antipsychotic_claims",

    "ndc_conflict_claims"
]


detail = (
    prescriber[
        detail_columns
    ]
    .copy()
)


# ============================================================
# NPI-DRUG ROOT CAUSE + RECOMMENDATION
# ============================================================

detail["root_cause"] = (
    detail.apply(
        generate_detail_root_cause,
        axis=1
    )
)

detail["recommendation"] = (
    detail.apply(
        generate_detail_recommendation,
        axis=1
    )
)


# ============================================================
# CREATE OUTPUT DATABASE
# ============================================================

print(
    "\n=============================================="
)

print(
    "CREATING OUTPUT DATABASE"
)

print(
    "=============================================="
)


output_conn = sqlite3.connect(
    OUTPUT_DB
)


# ============================================================
# TABLE 1
# OVERALL HISTORICAL RISK
# ============================================================

overall_result.to_sql(

    "pharmacy_overall_volume_risk",

    output_conn,

    if_exists="replace",

    index=False
)


# ============================================================
# TABLE 2
# NPI CURRENT PEER RISK
# ============================================================

npi.to_sql(

    "pharmacy_npi_volume_risk",

    output_conn,

    if_exists="replace",

    index=False
)


# ============================================================
# TABLE 3
# DRUG CURRENT PEER RISK
# ============================================================

drug.to_sql(

    "pharmacy_drug_volume_risk",

    output_conn,

    if_exists="replace",

    index=False
)


# ============================================================
# TABLE 4
# NPI-DRUG DETAIL
# ============================================================

detail.to_sql(

    "pharmacy_npi_drug_detail",

    output_conn,

    if_exists="replace",

    index=False
)


# ============================================================
# CREATE INDEXES
# ============================================================

cursor = output_conn.cursor()


cursor.execute(
    """
    CREATE INDEX IF NOT EXISTS
    idx_overall_calendar_year

    ON pharmacy_overall_volume_risk(
        calendar_year
    )
    """
)


cursor.execute(
    """
    CREATE INDEX IF NOT EXISTS
    idx_npi

    ON pharmacy_npi_volume_risk(
        Prscrbr_NPI
    )
    """
)


cursor.execute(
    """
    CREATE INDEX IF NOT EXISTS
    idx_npi_volume_risk

    ON pharmacy_npi_volume_risk(
        volume_risk_score
    )
    """
)


cursor.execute(
    """
    CREATE INDEX IF NOT EXISTS
    idx_drug

    ON pharmacy_drug_volume_risk(
        Brnd_Name
    )
    """
)


cursor.execute(
    """
    CREATE INDEX IF NOT EXISTS
    idx_drug_volume_risk

    ON pharmacy_drug_volume_risk(
        volume_risk_score
    )
    """
)


cursor.execute(
    """
    CREATE INDEX IF NOT EXISTS
    idx_detail_npi

    ON pharmacy_npi_drug_detail(
        Prscrbr_NPI
    )
    """
)


# ============================================================
# COMMIT
# ============================================================

output_conn.commit()


# ============================================================
# CLOSE CONNECTIONS
# ============================================================

output_conn.close()

source_conn.close()


# ============================================================
# VALIDATION
# ============================================================

print(
    "\n=============================================="
)

print(
    "VOLUME RISK CALCULATION COMPLETED"
)

print(
    "=============================================="
)


print(
    "\nOutput database:"
)

print(
    os.path.abspath(
        OUTPUT_DB
    )
)


print(
    "\nTables created:"
)

print(
    "1. pharmacy_overall_volume_risk"
)

print(
    "2. pharmacy_npi_volume_risk"
)

print(
    "3. pharmacy_drug_volume_risk"
)

print(
    "4. pharmacy_npi_drug_detail"
)


# ============================================================
# VALIDATION 1
# OVERALL HISTORICAL RISK
# ============================================================

print(
    "\n=============================================="
)

print(
    "OVERALL HISTORICAL VOLUME RISK"
)

print(
    "=============================================="
)


print(
    overall_result[
        [
            "calendar_year",

            "total_claims",

            "total_standardized_30_day_fills",

            "total_claims_zscore",

            "total_standardized_30_day_fills_zscore",

            "final_volume_risk_score",

            "volume_risk_level",

            "baseline_type",

            "root_cause",

            "recommendation"
        ]
    ]

    .round(2)

    .to_string(
        index=False
    )
)


# ============================================================
# VALIDATION 2
# RISK DISTRIBUTION
# ============================================================

print(
    "\n=============================================="
)

print(
    "OVERALL RISK DISTRIBUTION"
)

print(
    "=============================================="
)


print(
    overall_result[
        "volume_risk_level"
    ]
    .value_counts(
        dropna=False
    )
    .to_string()
)


# ============================================================
# VALIDATION 3
# NPI RISK DISTRIBUTION
# ============================================================

print(
    "\n=============================================="
)

print(
    "NPI RISK DISTRIBUTION"
)

print(
    "=============================================="
)


print(
    npi[
        "volume_risk_level"
    ]
    .value_counts(
        dropna=False
    )
    .to_string()
)


# ============================================================
# TOP NPI VOLUME RISKS
# ============================================================

print(
    "\n=============================================="
)

print(
    "TOP 20 NPI VOLUME RISKS"
)

print(
    "=============================================="
)


top_npi = (

    npi[
        [
            "Prscrbr_NPI",

            "Prscrbr_Last_Org_Name",

            "total_claims",

            "total_fills",

            "total_day_supply",

            "total_beneficiaries",

            "claims_percentile",

            "fills_percentile",

            "volume_risk_score",

            "volume_risk_level",

            "root_cause",

            "recommendation"
        ]
    ]

    .sort_values(
        "volume_risk_score",
        ascending=False
    )

    .head(20)
)


print(
    top_npi
    .round(2)
    .to_string(
        index=False
    )
)


# ============================================================
# VALIDATION 4
# DRUG RISK DISTRIBUTION
# ============================================================

print(
    "\n=============================================="
)

print(
    "DRUG RISK DISTRIBUTION"
)

print(
    "=============================================="
)


print(
    drug[
        "volume_risk_level"
    ]
    .value_counts(
        dropna=False
    )
    .to_string()
)


# ============================================================
# TOP DRUG VOLUME RISKS
# ============================================================

print(
    "\n=============================================="
)

print(
    "TOP 20 DRUG VOLUME RISKS"
)

print(
    "=============================================="
)


top_drugs = (

    drug[
        [
            "Brnd_Name",

            "Gnrc_Name",

            "total_claims",

            "total_fills",

            "total_day_supply",

            "total_beneficiaries",

            "high_risk_flag_count",

            "volume_risk_score",

            "volume_risk_level",

            "root_cause",

            "recommendation"
        ]
    ]

    .sort_values(
        "volume_risk_score",
        ascending=False
    )

    .head(20)
)


print(
    top_drugs
    .round(2)
    .to_string(
        index=False
    )
)


# ============================================================
# FINAL VALIDATION CHECKS
# ============================================================

print(
    "\n=============================================="
)

print(
    "VALIDATION CHECKS"
)

print(
    "=============================================="
)


# ------------------------------------------------------------
# Check 1: first three years should not have historical risk
# ------------------------------------------------------------

early_years = overall_result[
    overall_result["calendar_year"]
    < (
        overall_result["calendar_year"].min()
        + ROLLING_WINDOW
    )
]


print(
    "\nEarly years:"
)


print(
    early_years[
        [
            "calendar_year",

            "final_volume_risk_score",

            "volume_risk_level"
        ]
    ]
    .to_string(
        index=False
    )
)


# ------------------------------------------------------------
# Check 2: no NPI risk score should be negative
# ------------------------------------------------------------

negative_npi_scores = (
    npi["volume_risk_score"] < 0
).sum()


print(
    f"\nNegative NPI scores: "
    f"{negative_npi_scores}"
)


# ------------------------------------------------------------
# Check 3: NPI scores must be between 0 and 100
# ------------------------------------------------------------

invalid_npi_scores = (

    (
        npi["volume_risk_score"] < 0
    )

    |

    (
        npi["volume_risk_score"] > 100
    )

).sum()


print(
    f"Invalid NPI scores outside 0-100: "
    f"{invalid_npi_scores}"
)


# ------------------------------------------------------------
# Check 4: drug scores must be between 0 and 100
# ------------------------------------------------------------

invalid_drug_scores = (

    (
        drug["volume_risk_score"] < 0
    )

    |

    (
        drug["volume_risk_score"] > 100
    )

).sum()


print(
    f"Invalid drug scores outside 0-100: "
    f"{invalid_drug_scores}"
)


# ------------------------------------------------------------
# Check 5: output file exists
# ------------------------------------------------------------

print(
    f"\nOutput database exists: "
    f"{os.path.exists(OUTPUT_DB)}"
)


print(
    "\n=============================================="
)

print(
    "DONE"
)

print(
    "=============================================="
)