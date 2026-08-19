import os
import sqlite3
import pandas as pd


# ============================================================
# 1. PROJECT PATH
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(BASE_DIR, "voulme.db")


# ============================================================
# 2. DATASET CONFIGURATION
# ============================================================

DATASETS = [

    {
        "source": "outpatient",
        "folder": "outpatient_batches",
        "file": "batch_001.csv",
        "claim_id": "CLM_ID",
        "date": "CLM_FROM_DT",
        "npi": "ORG_NPI_NUM"
    },

    {
        "source": "carrier",
        "folder": "split_carrier",
        "file": "batch_001.csv",
        "claim_id": "CLM_ID",
        "date": "CLM_FROM_DT",
        "npi": "PRF_PHYSN_NPI"
    },

    {
        "source": "dme",
        "folder": "dme_splits",
        "file": "dme_part1.csv",
        "claim_id": "CLM_ID",
        "date": "CLM_FROM_DT",
        "npi": "PRVDR_NPI"
    },

    {
        "source": "hha",
        "folder": "hha_splits",
        "file": "hha_part1.csv",
        "claim_id": "CLM_ID",
        "date": "CLM_FROM_DT",
        "npi": "ORG_NPI_NUM"
    },

    {
        "source": "hospice",
        "folder": "hospice_splits",
        "file": "hospice_part1.csv",
        "claim_id": "CLM_ID",
        "date": "CLM_FROM_DT",
        "npi": "ORG_NPI_NUM"
    },

    {
        "source": "inpatient",
        "folder": "split_inpatient",
        "file": "inpatient_part_1.csv",
        "claim_id": "CLM_ID",
        "date": "CLM_FROM_DT",
        "npi": "ORG_NPI_NUM"
    },

    {
        "source": "snf",
        "folder": "snf_split",
        "file": "snf_part_1.csv",
        "claim_id": "CLM_ID",
        "date": "CLM_FROM_DT",
        "npi": "ORG_NPI_NUM"
    }
]


# ============================================================
# 3. ROLLING BASELINE CONFIGURATION
# ============================================================

ROLLING_MONTHS = 6

MIN_HISTORY_MONTHS = 6


# ============================================================
# 4. VOLUME RISK
# ============================================================

def calculate_volume_risk(deviation_pct):

    if deviation_pct is None or pd.isna(deviation_pct):
        return None

    deviation_pct = abs(float(deviation_pct))

    if deviation_pct <= 5:
        return 0.0

    elif deviation_pct <= 10:
        return 0.2

    elif deviation_pct <= 20:
        return 0.5

    elif deviation_pct <= 30:
        return 0.8

    else:
        return 1.0


# ============================================================
# 5. RISK LEVEL
# ============================================================

def get_risk_level(volume_risk):

    if volume_risk is None or pd.isna(volume_risk):
        return "INSUFFICIENT_HISTORY"

    if volume_risk == 0.0:
        return "LOW"

    elif volume_risk == 0.2:
        return "MODERATE"

    elif volume_risk == 0.5:
        return "MEDIUM"

    elif volume_risk == 0.8:
        return "HIGH"

    elif volume_risk == 1.0:
        return "CRITICAL"

    return "UNKNOWN"


# ============================================================
# 6. ROOT CAUSE + RECOMMENDATION
# ============================================================

def generate_root_cause_recommendation(
    risk_level=None,
    deviation_pct=None,
    baseline_volume=None,
    current_volume=None,
    history_months=None,
    status=None,
    property_name=None
):
    """
    Generate root cause and recommendation.

    This volume-risk pipeline does not currently contain a
    specific DQ property such as 'correction'.

    Therefore:
        - FAILED / ERROR status is supported if such fields
          are available in future input.
        - Otherwise explanation is based on volume-risk fields.
    """

    # --------------------------------------------------------
    # GENERIC PROPERTY FAILURE
    # --------------------------------------------------------

    property_status = ""

    if status is not None and not pd.isna(status):
        property_status = str(status).strip().upper()

    property_text = ""

    if property_name is not None and not pd.isna(property_name):
        property_text = str(property_name).strip()

    if property_status in [
        "FAILED",
        "FAIL",
        "ERROR"
    ]:

        if property_text:

            root_cause = (
                f"Property '{property_text}' failed validation "
                f"with status {property_status}."
            )

            recommendation = (
                f"Review the records associated with the "
                f"'{property_text}' property, correct the invalid "
                f"values, and rerun the validation."
            )

        else:

            root_cause = (
                f"A data validation property failed with "
                f"status {property_status}."
            )

            recommendation = (
                "Review the failed validation records, correct "
                "the underlying data issue, and rerun the validation."
            )

        return root_cause, recommendation

    # --------------------------------------------------------
    # SAFELY CONVERT VALUES
    # --------------------------------------------------------

    deviation = None
    baseline = None
    current = None
    history = None

    try:
        if deviation_pct is not None and not pd.isna(deviation_pct):
            deviation = float(deviation_pct)
    except Exception:
        pass

    try:
        if baseline_volume is not None and not pd.isna(baseline_volume):
            baseline = float(baseline_volume)
    except Exception:
        pass

    try:
        if current_volume is not None and not pd.isna(current_volume):
            current = float(current_volume)
    except Exception:
        pass

    try:
        if history_months is not None and not pd.isna(history_months):
            history = int(history_months)
    except Exception:
        pass

    level = ""

    if risk_level is not None and not pd.isna(risk_level):
        level = str(risk_level).strip().upper()

    # ========================================================
    # INSUFFICIENT HISTORY
    # ========================================================

    if level == "INSUFFICIENT_HISTORY":

        root_cause = (
            "Insufficient historical monthly data is available "
            "to calculate a reliable rolling baseline."
        )

        if history is not None:

            recommendation = (
                f"Continue collecting provider volume data until "
                f"at least {MIN_HISTORY_MONTHS} historical months "
                f"are available. Current history: {history} months."
            )

        else:

            recommendation = (
                f"Continue collecting data until at least "
                f"{MIN_HISTORY_MONTHS} historical months are available."
            )

        return root_cause, recommendation

    # ========================================================
    # CRITICAL
    # ========================================================

    if level == "CRITICAL":

        root_cause = (
            "Current provider claim volume shows a critical "
            "deviation from the previous 6-month historical baseline."
        )

        if deviation is not None:
            root_cause += (
                f" The deviation is {deviation:.2f}%."
            )

        if baseline is not None and current is not None:
            root_cause += (
                f" Current volume is {current:.0f} claims "
                f"against a baseline of {baseline:.2f}."
            )

        recommendation = (
            "Investigate the provider's current claim volume "
            "immediately. Check for abnormal claim activity, "
            "duplicate claims, missing or incorrectly loaded data, "
            "source-system changes, and sudden operational changes."
        )

        return root_cause, recommendation

    # ========================================================
    # HIGH
    # ========================================================

    if level == "HIGH":

        root_cause = (
            "Current provider claim volume has a high deviation "
            "from the previous 6-month historical baseline."
        )

        if deviation is not None:
            root_cause += (
                f" The deviation is {deviation:.2f}%."
            )

        if baseline is not None and current is not None:
            root_cause += (
                f" Current volume is {current:.0f} claims "
                f"against a baseline of {baseline:.2f}."
            )

        recommendation = (
            "Review the provider's recent claim volume and compare "
            "it with source-system records. Investigate unusual "
            "volume changes, duplicate records, missing records, "
            "and changes in provider activity."
        )

        return root_cause, recommendation

    # ========================================================
    # MEDIUM
    # ========================================================

    if level == "MEDIUM":

        root_cause = (
            "Current provider claim volume shows a moderate "
            "deviation from the historical baseline."
        )

        if deviation is not None:
            root_cause += (
                f" The deviation is {deviation:.2f}%."
            )

        if baseline is not None and current is not None:
            root_cause += (
                f" Current volume is {current:.0f} claims "
                f"against a baseline of {baseline:.2f}."
            )

        recommendation = (
            "Monitor the provider's claim volume and review the "
            "underlying source data if the deviation continues "
            "or increases."
        )

        return root_cause, recommendation

    # ========================================================
    # MODERATE
    # ========================================================

    if level == "MODERATE":

        root_cause = (
            "Current provider claim volume shows a small "
            "deviation from the historical baseline."
        )

        if deviation is not None:
            root_cause += (
                f" The deviation is {deviation:.2f}%."
            )

        recommendation = (
            "Continue monitoring the provider's monthly volume. "
            "No immediate corrective action is required unless "
            "the deviation continues to increase."
        )

        return root_cause, recommendation

    # ========================================================
    # LOW
    # ========================================================

    if level == "LOW":

        root_cause = (
            "Current provider claim volume is within the expected "
            "historical range."
        )

        recommendation = (
            "No corrective action is required. Continue routine "
            "monitoring of provider claim volume."
        )

        return root_cause, recommendation

    # ========================================================
    # UNKNOWN
    # ========================================================

    if level == "UNKNOWN":

        root_cause = (
            "The volume-risk level could not be determined from "
            "the available data."
        )

        recommendation = (
            "Review the provider volume and baseline fields and "
            "verify that the risk calculation completed correctly."
        )

        return root_cause, recommendation

    # ========================================================
    # DEFAULT
    # ========================================================

    return (
        "No volume-risk or validation failure was detected.",
        "No corrective action required. Continue routine monitoring."
    )


# ============================================================
# 7. ADD ROOT CAUSE + RECOMMENDATION TO DATAFRAME
# ============================================================

def add_explanation_columns(
    df,
    risk_column=None,
    deviation_column=None,
    baseline_column=None,
    current_column=None,
    history_column=None
):
    """
    Adds root_cause and recommendation directly to the DataFrame.

    This is important because the columns must exist in the
    DataFrame BEFORE to_sql() is called.
    """

    df = df.copy()

    root_causes = []
    recommendations = []

    for _, row in df.iterrows():

        risk_level = None
        deviation = None
        baseline = None
        current = None
        history = None

        if risk_column and risk_column in df.columns:
            risk_level = row[risk_column]

        if deviation_column and deviation_column in df.columns:
            deviation = row[deviation_column]

        if baseline_column and baseline_column in df.columns:
            baseline = row[baseline_column]

        if current_column and current_column in df.columns:
            current = row[current_column]

        if history_column and history_column in df.columns:
            history = row[history_column]

        root_cause, recommendation = (
            generate_root_cause_recommendation(
                risk_level=risk_level,
                deviation_pct=deviation,
                baseline_volume=baseline,
                current_volume=current,
                history_months=history
            )
        )

        root_causes.append(root_cause)
        recommendations.append(recommendation)

    df["root_cause"] = root_causes
    df["recommendation"] = recommendations

    return df


# ============================================================
# 8. CREATE DATABASE
# ============================================================

print("=" * 80)
print("PROVIDER LEVEL VOLUME RISK - ROLLING HISTORICAL BASELINE")
print("=" * 80)

print("\nDatabase:")
print(DB_PATH)

conn = sqlite3.connect(DB_PATH)


# ============================================================
# 9. READ DATASETS
# ============================================================

all_claims = []
dataset_summary = []


for config in DATASETS:

    source = config["source"]
    folder = config["folder"]
    filename = config["file"]

    claim_col = config["claim_id"]
    date_col = config["date"]
    npi_col = config["npi"]

    file_path = os.path.join(
        BASE_DIR,
        folder,
        filename
    )

    print("\n" + "-" * 80)
    print(f"PROCESSING: {source.upper()}")
    print(f"File: {file_path}")

    # --------------------------------------------------------
    # Check file
    # --------------------------------------------------------

    if not os.path.exists(file_path):

        print("WARNING: File not found.")
        continue

    try:

        # ----------------------------------------------------
        # Read required columns
        # ----------------------------------------------------

        df = pd.read_csv(
            file_path,
            usecols=[
                claim_col,
                date_col,
                npi_col
            ],
            dtype=str,
            low_memory=False
        )

        rows_loaded = len(df)

        print(
            f"Rows loaded: {rows_loaded:,}"
        )

        # ----------------------------------------------------
        # Rename
        # ----------------------------------------------------

        df = df.rename(
            columns={
                claim_col: "CLM_ID",
                date_col: "DT",
                npi_col: "NPI"
            }
        )

        df["source"] = source

        # ----------------------------------------------------
        # Clean NPI
        # ----------------------------------------------------

        df["NPI"] = (
            df["NPI"]
            .astype("string")
            .str.strip()
        )

        df["NPI"] = df["NPI"].str.replace(
            r"\.0$",
            "",
            regex=True
        )

        df = df[
            df["NPI"].notna()
            &
            (df["NPI"] != "")
            &
            (df["NPI"] != "0")
            &
            (df["NPI"] != "nan")
            &
            (df["NPI"] != "None")
        ]

        # ----------------------------------------------------
        # Clean Claim ID
        # ----------------------------------------------------

        df["CLM_ID"] = (
            df["CLM_ID"]
            .astype("string")
            .str.strip()
        )

        df = df[
            df["CLM_ID"].notna()
            &
            (df["CLM_ID"] != "")
            &
            (df["CLM_ID"] != "nan")
            &
            (df["CLM_ID"] != "None")
        ]

        # ----------------------------------------------------
        # Convert date
        # ----------------------------------------------------

        df["DT"] = pd.to_datetime(
            df["DT"],
            errors="coerce"
        )

        df = df.dropna(
            subset=["DT"]
        )

        # ----------------------------------------------------
        # Create monthly period
        # ----------------------------------------------------

        df["period"] = (
            df["DT"]
            .dt.to_period("M")
            .astype(str)
        )

        # ----------------------------------------------------
        # Remove duplicate claims
        # ----------------------------------------------------

        df = df.drop_duplicates(
            subset=[
                "source",
                "CLM_ID"
            ]
        )

        # ----------------------------------------------------
        # Keep required columns
        # ----------------------------------------------------

        df = df[
            [
                "source",
                "NPI",
                "CLM_ID",
                "DT",
                "period"
            ]
        ]

        all_claims.append(df)

        dataset_summary.append({

            "source": source,

            "file": filename,

            "rows_loaded": rows_loaded,

            "valid_claims": len(df),

            "unique_providers":
                df["NPI"].nunique(),

            "months":
                df["period"].nunique()
        })

        print(
            f"Valid claims: {len(df):,}"
        )

        print(
            f"Providers: {df['NPI'].nunique():,}"
        )

        print(
            f"Months: {df['period'].nunique():,}"
        )

    except Exception as e:

        print(
            f"ERROR processing {file_path}"
        )

        print(e)


# ============================================================
# 10. CHECK DATA
# ============================================================

if not all_claims:

    conn.close()

    raise SystemExit(
        "No valid datasets found."
    )


# ============================================================
# 11. COMBINE ALL DATASETS
# ============================================================

combined = pd.concat(
    all_claims,
    ignore_index=True
)

print("\n" + "=" * 80)
print("COMBINED DATA")
print("=" * 80)

print(
    f"Total claims: {len(combined):,}"
)

print(
    f"Unique providers: {combined['NPI'].nunique():,}"
)

print(
    f"Unique months: {combined['period'].nunique():,}"
)


# ============================================================
# 12. ROOT CAUSE + RECOMMENDATION
#     COMBINED CLAIM TABLE
# ============================================================

combined = add_explanation_columns(
    combined
)


# ============================================================
# 13. STORE CLAIM LEVEL DATA
# ============================================================

combined.to_sql(
    "combined_provider_claims",
    conn,
    if_exists="replace",
    index=False
)


# ============================================================
# 14. PROVIDER MONTHLY VOLUME
# ============================================================

provider_monthly = (

    combined

    .groupby(
        [
            "NPI",
            "period"
        ],
        as_index=False
    )

    .agg(
        monthly_volume=(
            "CLM_ID",
            "count"
        )
    )
)


provider_monthly = provider_monthly.sort_values(
    [
        "NPI",
        "period"
    ]
)


# ============================================================
# 15. ROOT CAUSE + RECOMMENDATION
#     MONTHLY TABLE
# ============================================================

provider_monthly = add_explanation_columns(
    provider_monthly
)


# ============================================================
# 16. STORE OBSERVED MONTHLY VOLUME
# ============================================================

provider_monthly.to_sql(
    "provider_monthly_volume",
    conn,
    if_exists="replace",
    index=False
)


# ============================================================
# 17. CREATE ROLLING HISTORICAL BASELINE
# ============================================================

rolling_rows = []


for npi, group in provider_monthly.groupby("NPI"):

    # --------------------------------------------------------
    # Sort by month
    # --------------------------------------------------------

    group = group.copy()

    group["period_date"] = pd.to_datetime(
        group["period"]
    )

    group = group.sort_values(
        "period_date"
    )

    group = group.set_index(
        "period_date"
    )

    # --------------------------------------------------------
    # Complete calendar-month index
    # --------------------------------------------------------

    full_index = pd.date_range(
        start=group.index.min(),
        end=group.index.max(),
        freq="MS"
    )

    group = group.reindex(
        full_index
    )

    # --------------------------------------------------------
    # Restore NPI
    # --------------------------------------------------------

    group["NPI"] = npi

    # --------------------------------------------------------
    # Missing monthly volume = 0
    # --------------------------------------------------------

    group["monthly_volume"] = (
        group["monthly_volume"]
        .fillna(0)
        .astype(int)
    )

    # --------------------------------------------------------
    # Current period
    # --------------------------------------------------------

    group["period"] = (
        group.index
        .strftime("%Y-%m")
    )

    # --------------------------------------------------------
    # Rolling historical baseline
    # --------------------------------------------------------

    group["baseline_volume"] = (

        group["monthly_volume"]

        .shift(1)

        .rolling(
            window=ROLLING_MONTHS,
            min_periods=ROLLING_MONTHS
        )

        .median()
    )

    # --------------------------------------------------------
    # Number of historical months
    # --------------------------------------------------------

    group["history_months"] = (

        group["monthly_volume"]
        .shift(1)
        .rolling(
            window=ROLLING_MONTHS,
            min_periods=1
        )
        .count()
    )

    # --------------------------------------------------------
    # Calculate deviation
    # --------------------------------------------------------

    group["deviation_pct"] = None

    valid_baseline = (
        group["baseline_volume"].notna()
        &
        (group["baseline_volume"] > 0)
    )

    group.loc[
        valid_baseline,
        "deviation_pct"
    ] = (

        (
            group.loc[
                valid_baseline,
                "monthly_volume"
            ]
            -
            group.loc[
                valid_baseline,
                "baseline_volume"
            ]
        ).abs()

        /

        group.loc[
            valid_baseline,
            "baseline_volume"
        ]

        * 100
    )

    # --------------------------------------------------------
    # Calculate volume risk
    # --------------------------------------------------------

    group["volume_risk"] = (
        group["deviation_pct"]
        .apply(calculate_volume_risk)
    )

    # --------------------------------------------------------
    # Risk level
    # --------------------------------------------------------

    group["risk_level"] = (
        group["volume_risk"]
        .apply(get_risk_level)
    )

    # --------------------------------------------------------
    # Baseline periods
    # --------------------------------------------------------

    baseline_period_list = []

    periods = group.index

    for i in range(len(group)):

        if i < ROLLING_MONTHS:

            baseline_period_list.append(
                None
            )

        else:

            previous_periods = periods[
                i - ROLLING_MONTHS:i
            ]

            baseline_period_list.append(

                ", ".join(
                    p.strftime("%Y-%m")
                    for p in previous_periods
                )
            )

    group["baseline_periods"] = (
        baseline_period_list
    )

    # --------------------------------------------------------
    # Baseline method
    # --------------------------------------------------------

    group["baseline_method"] = (

        group["baseline_volume"]
        .apply(
            lambda x:
                "ROLLING_6_MONTH_MEDIAN"
                if pd.notna(x)
                else "INSUFFICIENT_HISTORY"
        )
    )

    # --------------------------------------------------------
    # Store rows
    # --------------------------------------------------------

    for _, row in group.reset_index(
        drop=True
    ).iterrows():

        rolling_rows.append({

            "NPI":
                npi,

            "period":
                row["period"],

            "monthly_volume":
                int(row["monthly_volume"]),

            "baseline_volume":
                round(
                    float(row["baseline_volume"]),
                    2
                )
                if pd.notna(
                    row["baseline_volume"]
                )
                else None,

            "baseline_method":
                row["baseline_method"],

            "baseline_periods":
                row["baseline_periods"],

            "deviation_pct":
                round(
                    float(row["deviation_pct"]),
                    2
                )
                if pd.notna(
                    row["deviation_pct"]
                )
                else None,

            "volume_risk":
                row["volume_risk"],

            "risk_level":
                row["risk_level"],

            "history_months":
                int(row["history_months"])
        })


# ============================================================
# 18. CREATE ROLLING HISTORY DATAFRAME
# ============================================================

rolling_df = pd.DataFrame(
    rolling_rows
)


# ============================================================
# 19. ADD ROOT CAUSE + RECOMMENDATION
#     ROLLING HISTORY
# ============================================================

rolling_df = add_explanation_columns(
    rolling_df,
    risk_column="risk_level",
    deviation_column="deviation_pct",
    baseline_column="baseline_volume",
    current_column="monthly_volume",
    history_column="history_months"
)


# ============================================================
# 20. STORE ROLLING HISTORY
# ============================================================

rolling_df.to_sql(
    "provider_volume_rolling_history",
    conn,
    if_exists="replace",
    index=False
)


# ============================================================
# 21. CREATE LATEST PROVIDER LEVEL RESULT
# ============================================================

latest_df = (

    rolling_df

    .sort_values(
        [
            "NPI",
            "period"
        ]
    )

    .groupby(
        "NPI",
        as_index=False
    )

    .tail(1)

    .copy()
)


# ============================================================
# 22. ADD TOTAL CLAIM VOLUME
# ============================================================

total_volume = (

    rolling_df

    .groupby("NPI")["monthly_volume"]

    .sum()

    .reset_index()

    .rename(
        columns={
            "monthly_volume":
                "total_claim_volume"
        }
    )
)


latest_df = latest_df.merge(
    total_volume,
    on="NPI",
    how="left"
)


# ============================================================
# 23. ADD SOURCE INFORMATION
# ============================================================

source_info = (

    combined

    .groupby("NPI")["source"]

    .agg(
        lambda x:
        sorted(
            x.dropna()
            .unique()
            .tolist()
        )
    )

    .reset_index()
)


source_info["source_count"] = (
    source_info["source"]
    .apply(len)
)

source_info["sources"] = (
    source_info["source"]
    .apply(
        lambda x:
        ", ".join(x)
    )
)

source_info = source_info[
    [
        "NPI",
        "source_count",
        "sources"
    ]
]


latest_df = latest_df.merge(
    source_info,
    on="NPI",
    how="left"
)


# ============================================================
# 24. RENAME CURRENT MONTH FIELDS
# ============================================================

latest_df = latest_df.rename(
    columns={
        "period":
            "current_period",

        "monthly_volume":
            "current_month_volume"
    }
)


# ============================================================
# 25. MONTHS AVAILABLE
# ============================================================

months_available = (

    rolling_df

    .groupby("NPI")["period"]

    .nunique()

    .reset_index()

    .rename(
        columns={
            "period":
                "months_available"
        }
    )
)


latest_df = latest_df.merge(
    months_available,
    on="NPI",
    how="left"
)


# ============================================================
# 26. SORT BY RISK
# ============================================================

latest_df = latest_df.sort_values(

    [
        "volume_risk",
        "deviation_pct"
    ],

    ascending=[
        False,
        False
    ],

    na_position="last"
)


# ============================================================
# 27. ROOT CAUSE + RECOMMENDATION
#     FINAL PROVIDER TABLE
# ============================================================

latest_df = add_explanation_columns(
    latest_df,
    risk_column="risk_level",
    deviation_column="deviation_pct",
    baseline_column="baseline_volume",
    current_column="current_month_volume",
    history_column="history_months"
)


# ============================================================
# 28. STORE FINAL PROVIDER LEVEL TABLE
# ============================================================

latest_df.to_sql(
    "provider_volume_risk",
    conn,
    if_exists="replace",
    index=False
)


# ============================================================
# 29. DATASET SUMMARY
# ============================================================

summary_df = pd.DataFrame(
    dataset_summary
)


# Dataset summary does not have a provider-level risk field.
# Add the requested columns with a meaningful generic message.

summary_df["root_cause"] = (
    "Dataset-level volume summary. No individual "
    "provider volume-risk failure is represented in this table."
)

summary_df["recommendation"] = (
    "Use provider_volume_risk and provider_volume_rolling_history "
    "for provider-level investigation and corrective action."
)


summary_df.to_sql(
    "volume_dataset_summary",
    conn,
    if_exists="replace",
    index=False
)


# ============================================================
# 30. INDEXES
# ============================================================

conn.execute(
    """
    CREATE INDEX IF NOT EXISTS
    idx_claims_npi
    ON combined_provider_claims(NPI)
    """
)

conn.execute(
    """
    CREATE INDEX IF NOT EXISTS
    idx_monthly_npi
    ON provider_monthly_volume(NPI)
    """
)

conn.execute(
    """
    CREATE INDEX IF NOT EXISTS
    idx_rolling_npi
    ON provider_volume_rolling_history(NPI)
    """
)

conn.execute(
    """
    CREATE INDEX IF NOT EXISTS
    idx_rolling_period
    ON provider_volume_rolling_history(period)
    """
)

conn.execute(
    """
    CREATE INDEX IF NOT EXISTS
    idx_risk_npi
    ON provider_volume_risk(NPI)
    """
)

conn.commit()


# ============================================================
# 31. FINAL SUMMARY
# ============================================================

print("\n" + "=" * 80)
print("FINAL PROVIDER LEVEL RESULT")
print("=" * 80)

print(
    f"Total providers      : "
    f"{len(latest_df):,}"
)

print(
    f"Providers with risk  : "
    f"{latest_df['volume_risk'].notna().sum():,}"
)

print(
    f"Insufficient history : "
    f"{latest_df['volume_risk'].isna().sum():,}"
)


# ============================================================
# 32. RISK DISTRIBUTION
# ============================================================

print("\nRisk Distribution")
print("-" * 50)

print(
    latest_df[
        "risk_level"
    ]
    .value_counts(
        dropna=False
    )
    .to_string()
)


# ============================================================
# 33. SHOW TOP PROVIDERS
# ============================================================

print("\n" + "=" * 80)
print("TOP 20 PROVIDERS BY VOLUME RISK")
print("=" * 80)

display_columns = [

    "NPI",

    "total_claim_volume",

    "current_period",

    "current_month_volume",

    "baseline_volume",

    "baseline_method",

    "baseline_periods",

    "deviation_pct",

    "volume_risk",

    "risk_level",

    "months_available",

    "history_months",

    "source_count",

    "sources",

    "root_cause",

    "recommendation"
]


# Safety check
missing_display_columns = [
    col
    for col in display_columns
    if col not in latest_df.columns
]

if missing_display_columns:

    print(
        "\nERROR: Missing columns in latest_df:"
    )

    print(
        missing_display_columns
    )

else:

    print(
        latest_df[
            display_columns
        ]
        .head(20)
        .to_string(
            index=False
        )
    )


# ============================================================
# 34. SHOW ROLLING HISTORY EXAMPLE
# ============================================================

print("\n" + "=" * 80)
print("ROLLING BASELINE EXAMPLE")
print("=" * 80)

if len(latest_df) > 0:

    example_npi = latest_df.iloc[0]["NPI"]

    example_history = (

        rolling_df[
            rolling_df["NPI"] == example_npi
        ]

        .sort_values("period")

        .tail(12)
    )

    history_display_columns = [
        "NPI",
        "period",
        "monthly_volume",
        "baseline_volume",
        "deviation_pct",
        "volume_risk",
        "risk_level",
        "root_cause",
        "recommendation"
    ]

    print(
        example_history[
            history_display_columns
        ]
        .to_string(
            index=False
        )
    )


# ============================================================
# 35. VERIFY ALL FIVE TABLES
# ============================================================

print("\n" + "=" * 80)
print("VERIFYING ALL EXISTING TABLES")
print("=" * 80)

tables_to_verify = [
    "combined_provider_claims",
    "provider_monthly_volume",
    "provider_volume_rolling_history",
    "provider_volume_risk",
    "volume_dataset_summary"
]


for table in tables_to_verify:

    columns = [
        row[1]
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    ]

    row_count = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM {table}
        """
    ).fetchone()[0]

    root_column_exists = (
        "root_cause" in columns
    )

    recommendation_column_exists = (
        "recommendation" in columns
    )

    null_root_count = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM {table}
        WHERE root_cause IS NULL
        """
    ).fetchone()[0]

    null_recommendation_count = conn.execute(
        f"""
        SELECT COUNT(*)
        FROM {table}
        WHERE recommendation IS NULL
        """
    ).fetchone()[0]

    print("\n----------------------------------------")

    print(
        f"Table: {table}"
    )

    print(
        f"Rows: {row_count:,}"
    )

    print(
        f"root_cause column: "
        f"{'YES' if root_column_exists else 'NO'}"
    )

    print(
        f"recommendation column: "
        f"{'YES' if recommendation_column_exists else 'NO'}"
    )

    print(
        f"NULL root_cause: "
        f"{null_root_count:,}"
    )

    print(
        f"NULL recommendation: "
        f"{null_recommendation_count:,}"
    )


# ============================================================
# 36. CLOSE DATABASE
# ============================================================

conn.close()


# ============================================================
# 37. COMPLETED
# ============================================================

print("\n" + "=" * 80)
print("COMPLETED SUCCESSFULLY")
print("=" * 80)

print("\nDatabase:")
print(DB_PATH)

print("\nExisting tables updated:")

print("1. combined_provider_claims")
print("2. provider_monthly_volume")
print("3. provider_volume_rolling_history")
print("4. provider_volume_risk")
print("5. volume_dataset_summary")

print("\nAdded columns to every table:")

print("1. root_cause")
print("2. recommendation")

print("\nNo additional table was created.")

print("\nRoot cause and recommendation are generated")
print("BEFORE each DataFrame is stored in SQLite.")

print("\nRolling baseline:")
print(
    "Median of previous 6 consecutive calendar months"
)

print("\nMissing months:")
print(
    "Treated as 0 claims"
)

print("\nCurrent month:")
print(
    "Excluded from its own baseline"
)

print("\nDatasets:")
print(
    "Outpatient + Carrier + DME + HHA + "
    "Hospice + Inpatient + SNF"
)

print("\nFiles:")
print(
    "Only PART 1 / BATCH 001 files used."
)