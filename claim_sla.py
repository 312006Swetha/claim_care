import sqlite3
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd


# ============================================================
# CLAIMCARE — FFS CLAIMS SLA COMPLIANCE + BEHAVIOR ANALYSIS
# ============================================================
#
# INPUT DATABASES
#
# 1. voulme(1).db
#    Existing provider-level volume analysis:
#       - provider_volume_risk
#
# 2. claim_dagster(1).db
#    Existing ClaimCare DQ/Dagster execution history:
#       - dq_run_output
#
# IMPORTANT
# ----------
# This layer DOES NOT calculate SLA RISK.
# SLA risk is reserved for the next layer.
#
# This layer only calculates:
#
#   A. SLA COMPLIANCE
#   B. BEHAVIOR ANOMALY
#
# BEHAVIOR ANALYSIS
# -----------------
# Uses simple explainable statistics only:
#
#   1. Previous 3-period moving-average baseline
#   2. Percentage deviation from that baseline
#   3. Simple threshold-based anomaly flag
#
# It DOES NOT use:
#   - Robust Z-score
#   - PSI
#   - Isolation Forest
#   - Any ML anomaly algorithm
#
# ============================================================


# ============================================================
# PROJECT PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

VOLUME_DB = BASE_DIR / "voulme.db"
DQ_DB = BASE_DIR / "claim_dagster.db"

OUTPUT_DB = BASE_DIR / "claims_sla_behavior.db"

OUTPUT_TABLE = "claims_sla_behavior"




# ============================================================
# SLA CONFIGURATION
# ============================================================

# Maximum allowed processing duration for a Claims batch/run.
# Change this only if your actual Claims SLA is different.
SLA_LIMIT_MINUTES = 60.0

# A breach only slightly above the SLA is treated separately so that
# the RCA/recommendation reflects a minor overrun rather than a major delay.
# Example with a 60-minute SLA:
#   60.00 min -> MET
#   60.01 to 63.00 min -> MINOR_BREACH
#   > 63.00 min -> BREACHED
SLA_MINOR_BREACH_PCT = 5.0


# ============================================================
# BEHAVIOR CONFIGURATION
# ============================================================

# Number of previous periods used for the simple moving average.
BEHAVIOR_BASELINE_PERIODS = 3

# Percentage deviation above which behavior is flagged.
# Example:
# baseline = 100
# current  = 160
# deviation = 60%
# -> ANOMALOUS
BEHAVIOR_DEVIATION_THRESHOLD_PCT = 50.0


# ============================================================
# LOAD VOLUME DATABASE
# ============================================================

def load_volume_data():

    if not VOLUME_DB.exists():
        raise FileNotFoundError(
            f"Volume database not found:\n{VOLUME_DB}"
        )

    conn = sqlite3.connect(VOLUME_DB)

    try:

        tables = pd.read_sql_query(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            """,
            conn
        )["name"].tolist()

        if "provider_volume_risk" not in tables:
            raise ValueError(
                "Table 'provider_volume_risk' was not found "
                f"in {VOLUME_DB}"
            )

        df = pd.read_sql_query(
            """
            SELECT
                NPI,
                current_period,
                current_month_volume,
                baseline_volume,
                deviation_pct,
                volume_risk,
                risk_level,
                history_months,
                total_claim_volume,
                source_count,
                sources,
                months_available
            FROM provider_volume_risk
            """,
            conn
        )

    finally:
        conn.close()

    return df


# ============================================================
# LOAD DQ / DAGSTER EXECUTION DATABASE
# ============================================================

def load_dq_runs():

    if not DQ_DB.exists():
        raise FileNotFoundError(
            f"DQ database not found:\n{DQ_DB}"
        )

    conn = sqlite3.connect(DQ_DB)

    try:

        tables = pd.read_sql_query(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            """,
            conn
        )["name"].tolist()

        if "dq_run_output" not in tables:
            raise ValueError(
                "Table 'dq_run_output' was not found "
                f"in {DQ_DB}"
            )

        df = pd.read_sql_query(
            """
            SELECT
                run_id,
                step_name,
                status,
                started_at,
                completed_at,
                duration_seconds,
                records_processed,
                dataset_name,
                batch_id,
                created_at
            FROM dq_run_output
            WHERE run_id IS NOT NULL
            ORDER BY started_at, id
            """,
            conn
        )

    finally:
        conn.close()

    # Convert date/time fields
    for col in [
        "started_at",
        "completed_at",
        "created_at"
    ]:
        if col in df.columns:
            df[col] = pd.to_datetime(
                df[col],
                errors="coerce"
            )

    df["duration_seconds"] = pd.to_numeric(
        df["duration_seconds"],
        errors="coerce"
    )

    df["records_processed"] = pd.to_numeric(
        df["records_processed"],
        errors="coerce"
    )

    return df


# ============================================================
# NORMALIZE PERIOD
# ============================================================

def normalize_period(series):

    s = (
        series
        .astype(str)
        .str.strip()
    )

    extracted = s.str.extract(
        r"((?:19|20)\d{2})[-_/]?(\d{2})",
        expand=True
    )

    result = pd.Series(
        pd.NA,
        index=s.index,
        dtype="object"
    )

    mask = (
        extracted[0].notna()
        &
        extracted[1].notna()
    )

    result.loc[mask] = (
        extracted.loc[mask, 0].astype(str)
        + "-"
        + extracted.loc[mask, 1].astype(str)
    )

    return result


# ============================================================
# SLA COMPLIANCE
# ============================================================

def calculate_sla_compliance(dq_df):

    if dq_df.empty:
        return pd.DataFrame()

    df = dq_df.copy()

    # --------------------------------------------------------
    # Keep the actual claims-processing step where available.
    #
    # From the supplied Dagster database, this is:
    #     run_claims_checks
    #
    # If it is not present, fall back to the latest successful
    # processing step having a duration.
    # --------------------------------------------------------

    claims_steps = df[
        df["step_name"]
        .astype(str)
        .str.lower()
        .eq("run_claims_checks")
    ].copy()

    if claims_steps.empty:

        claims_steps = df[
            df["duration_seconds"].notna()
            &
            df["step_name"].astype(str)
            .str.lower()
            .str.contains(
                "claim",
                na=False
            )
        ].copy()

    if claims_steps.empty:

        claims_steps = df[
            df["duration_seconds"].notna()
        ].copy()

    if claims_steps.empty:
        return pd.DataFrame()

    # --------------------------------------------------------
    # One SLA record per run
    # --------------------------------------------------------

    claims_steps = (
        claims_steps
        .sort_values(
            [
                "started_at",
                "completed_at"
            ]
        )
        .drop_duplicates(
            subset=["run_id"],
            keep="last"
        )
        .reset_index(drop=True)
    )

    claims_steps["processing_time_minutes"] = (
        claims_steps["duration_seconds"]
        / 60.0
    )

    claims_steps["sla_limit_minutes"] = (
        SLA_LIMIT_MINUTES
    )

    # --------------------------------------------------------
    # SLA status
    #
    # No processing duration -> N/A
    # <= SLA              -> MET
    # > SLA and <= +3 min -> MINOR_OVERRUN
    # > SLA + 3 min       -> BREACHED
    # --------------------------------------------------------

    claims_steps["sla_status"] = "N/A"

    available = (
        claims_steps["processing_time_minutes"]
        .notna()
    )

    minor_overrun_limit = (
        SLA_LIMIT_MINUTES + 3.0
    )

    claims_steps.loc[
        available
        &
        (
            claims_steps["processing_time_minutes"]
            <=
            SLA_LIMIT_MINUTES
        ),
        "sla_status"
    ] = "MET"

    claims_steps.loc[
        available
        &
        (
            claims_steps["processing_time_minutes"]
            >
            SLA_LIMIT_MINUTES
        )
        &
        (
            claims_steps["processing_time_minutes"]
            <=
            minor_overrun_limit
        ),
        "sla_status"
    ] = "MINOR_OVERRUN"

    claims_steps.loc[
        available
        &
        (
            claims_steps["processing_time_minutes"]
            >
            minor_overrun_limit
        ),
        "sla_status"
    ] = "BREACHED"

    # --------------------------------------------------------
    # Compliance %
    #
    # Only evaluable runs are included.
    # --------------------------------------------------------

    evaluable = claims_steps[
        claims_steps["sla_status"]
        .isin(
            ["MET", "MINOR_OVERRUN", "BREACHED"]
        )
    ]

    if len(evaluable) > 0:

        compliance_pct = (
            evaluable["sla_status"]
            .eq("MET")
            .mean()
            * 100.0
        )

        met_count = int(
            evaluable["sla_status"]
            .eq("MET")
            .sum()
        )

        breached_count = int(
            evaluable["sla_status"]
            .isin(
                ["MINOR_OVERRUN", "BREACHED"]
            )
            .sum()
        )

    else:

        compliance_pct = np.nan
        met_count = 0
        breached_count = 0

    claims_steps["sla_compliance_percentage"] = (
        compliance_pct
    )

    claims_steps["sla_met_count"] = (
        met_count
    )

    claims_steps["sla_breached_count"] = (
        breached_count
    )

    claims_steps["sla_evaluable_runs"] = (
        len(evaluable)
    )

    return claims_steps


# ============================================================
# PERIOD-LEVEL CLAIM VOLUME
# ============================================================

def aggregate_claim_volume(volume_df):

    df = volume_df.copy()

    df["current_period"] = normalize_period(
        df["current_period"]
    )

    df["current_month_volume"] = pd.to_numeric(
        df["current_month_volume"],
        errors="coerce"
    )

    df["volume_risk"] = pd.to_numeric(
        df["volume_risk"],
        errors="coerce"
    )

    df["total_claim_volume"] = pd.to_numeric(
        df["total_claim_volume"],
        errors="coerce"
    )

    df["provider_count"] = (
        df["NPI"]
        .astype(str)
        .nunique()
    )

    # --------------------------------------------------------
    # Use CURRENT MONTH provider volumes to calculate the
    # overall FFS claim volume for each period.
    #
    # Do NOT sum total_claim_volume:
    # total_claim_volume is provider history, not current-month
    # volume and would double-count provider history.
    # --------------------------------------------------------

    period_volume = (
        df
        .groupby(
            "current_period",
            dropna=True
        )
        .agg(
            total_claim_volume=(
                "current_month_volume",
                "sum"
            ),
            provider_count=(
                "NPI",
                "nunique"
            ),
            average_volume_risk=(
                "volume_risk",
                "mean"
            ),
            maximum_volume_risk=(
                "volume_risk",
                "max"
            ),
            provider_rows=(
                "NPI",
                "count"
            ),
        )
        .reset_index()
    )

    return (
        period_volume
        .sort_values("current_period")
        .reset_index(drop=True)
    )


# ============================================================
# SIMPLE BEHAVIOR ANALYSIS
# ============================================================
#
# Method:
#
#   For each month:
#
#       baseline = average of previous 3 months
#
#       deviation =
#           |current - baseline|
#           / baseline * 100
#
#   If deviation > 50%:
#       ANOMALOUS
#
#   Otherwise:
#       NORMAL
#
# This is intentionally simple and explainable.
# ============================================================

def calculate_behavior_anomaly(period_df):

    # --------------------------------------------------------
    # IMPORTANT:
    # Build a COMPLETE calendar-month series first.
    #
    # Missing months are explicitly represented as zero claim
    # volume. This means the "previous 3 months" are always the
    # actual previous 3 calendar months, not merely the previous
    # 3 rows that happen to exist in the source data.
    # --------------------------------------------------------

    df = (
        period_df
        .copy()
    )

    df["current_period"] = pd.PeriodIndex(
        df["current_period"],
        freq="M"
    )

    df = (
        df
        .sort_values("current_period")
        .drop_duplicates(
            subset=["current_period"],
            keep="last"
        )
        .set_index("current_period")
    )

    if df.empty:
        return period_df.copy()

    full_periods = pd.period_range(
        start=df.index.min(),
        end=df.index.max(),
        freq="M"
    )

    # Keep the original observations and create rows for genuinely
    # absent calendar months.
    df = df.reindex(full_periods)

    # Missing calendar months mean no claim records were present for
    # that period in the source used by this layer.
    df["total_claim_volume"] = (
        pd.to_numeric(
            df["total_claim_volume"],
            errors="coerce"
        )
        .fillna(0)
    )

    # These fields are only informational for the behavior output.
    df["provider_count"] = (
        pd.to_numeric(
            df["provider_count"],
            errors="coerce"
        )
        .fillna(0)
        .astype(int)
    )

    df["average_volume_risk"] = pd.to_numeric(
        df["average_volume_risk"],
        errors="coerce"
    )

    df["maximum_volume_risk"] = pd.to_numeric(
        df["maximum_volume_risk"],
        errors="coerce"
    )

    # Re-label the index as YYYY-MM strings.
    df["current_period"] = (
        df.index.astype(str)
    )

    df = df.reset_index(drop=True)

    df["behavior_baseline_volume"] = np.nan
    df["behavior_deviation_pct"] = np.nan

    statuses = []
    reasons = []

    for i in range(len(df)):

        # Need the previous 3 REAL calendar months.
        if i < BEHAVIOR_BASELINE_PERIODS:

            statuses.append("N/A")

            reasons.append(
                "Insufficient previous calendar months "
                "for behavior baseline."
            )

            continue

        history = df.iloc[
            i - BEHAVIOR_BASELINE_PERIODS:i
        ]

        historical_volume = pd.to_numeric(
            history["total_claim_volume"],
            errors="coerce"
        )

        current_volume = pd.to_numeric(
            df.loc[i, "total_claim_volume"],
            errors="coerce"
        )

        # With the calendar-month completion above, all three
        # previous calendar months are now represented.
        if (
            len(historical_volume)
            !=
            BEHAVIOR_BASELINE_PERIODS
            or
            pd.isna(current_volume)
        ):

            statuses.append("N/A")

            reasons.append(
                "Insufficient valid claim-volume history."
            )

            continue

        baseline = (
            historical_volume
            .mean()
        )

        df.loc[
            i,
            "behavior_baseline_volume"
        ] = baseline

        # ----------------------------------------------------
        # Zero baseline handling
        # ----------------------------------------------------

        if baseline == 0:

            if current_volume == 0:

                deviation = 0.0
                status = "NORMAL"

                reason = (
                    "Current and previous 3 calendar months "
                    "have zero claim volume."
                )

            else:

                deviation = np.inf
                status = "ANOMALOUS"

                reason = (
                    "Current claim volume is positive while "
                    "the previous 3 calendar-month baseline "
                    "is zero."
                )

        else:

            deviation = (
                abs(
                    current_volume
                    -
                    baseline
                )
                /
                baseline
            ) * 100.0

            if (
                deviation
                >
                BEHAVIOR_DEVIATION_THRESHOLD_PCT
            ):

                status = "ANOMALOUS"

                direction = (
                    "increased"
                    if current_volume > baseline
                    else "decreased"
                )

                reason = (
                    f"Claim volume {direction} by "
                    f"{deviation:.2f}% from the previous "
                    f"{BEHAVIOR_BASELINE_PERIODS} calendar-month "
                    "average."
                )

            else:

                status = "NORMAL"

                reason = (
                    "Claim volume is within the configured "
                    f"{BEHAVIOR_DEVIATION_THRESHOLD_PCT:.0f}% "
                    "behavior threshold."
                )

        df.loc[
            i,
            "behavior_deviation_pct"
        ] = deviation

        statuses.append(status)
        reasons.append(reason)

    df["behavior_status"] = statuses
    df["behavior_reason"] = reasons

    return df


# ============================================================
# ROOT CAUSE + RECOMMENDATION ENGINE
# ============================================================
# This logic ONLY explains an already detected SLA/behavior failure.
# Existing SLA and behavior calculations are unchanged.
# ============================================================

def generate_sla_root_cause(row):
    status = str(row.get("sla_status", "")).upper()

    processing_time = row.get(
        "processing_time_minutes"
    )
    sla_limit = row.get(
        "sla_limit_minutes",
        SLA_LIMIT_MINUTES
    )

    if status == "BREACHED":
        if (
            pd.notna(processing_time)
            and pd.notna(sla_limit)
        ):
            excess = (
                float(processing_time)
                - float(sla_limit)
            )

            return (
                f"Claims processing exceeded the SLA by "
                f"{excess:.2f} minutes, indicating a material "
                f"processing delay against the configured "
                f"{float(sla_limit):.2f}-minute limit."
            )

        return (
            "Claims processing exceeded the configured SLA."
        )

    if status == "MINOR_OVERRUN":
        if (
            pd.notna(processing_time)
            and pd.notna(sla_limit)
        ):
            excess = (
                float(processing_time)
                - float(sla_limit)
            )

            return (
                f"Claims processing was slightly above the SLA by "
                f"{excess:.2f} minutes, indicating a minor processing "
                f"delay or transient execution overhead."
            )

        return (
            "Claims processing was slightly above the configured SLA."
        )

    if status == "MET":
        return "No SLA breach detected."

    return (
        "SLA root cause cannot be determined because processing "
        "time is unavailable."
    )


def generate_sla_recommendation(row):
    status = str(row.get("sla_status", "")).upper()

    if status == "BREACHED":
        return (
            "Investigate the affected claims-processing run for "
            "queueing delays, processing retries, data-volume spikes, "
            "failed or repeated steps, and downstream processing delays. "
            "Prioritize remediation before the next batch reaches the SLA."
        )

    if status == "MINOR_OVERRUN":
        return (
            "Review the run for transient queueing, execution overhead, "
            "or minor upstream/downstream delays. Monitor the next runs "
            "closely and address the source if the overrun repeats."
        )

    if status == "MET":
        return "No immediate SLA remediation is required."

    return (
        "No SLA recommendation can be made until valid processing-time "
        "information is available."
    )


def generate_behavior_root_cause(row):
    status = str(row.get("behavior_status", "")).upper()

    if status == "ANOMALOUS":
        current_volume = row.get("total_claim_volume")
        baseline = row.get("behavior_baseline_volume")
        deviation = row.get("behavior_deviation_pct")

        if (
            pd.notna(current_volume)
            and pd.notna(baseline)
            and pd.notna(deviation)
        ):
            direction = (
                "increased" if current_volume > baseline
                else "decreased"
            )

            return (
                f"Claim volume {direction} materially from the "
                f"previous {BEHAVIOR_BASELINE_PERIODS}-calendar-month "
                f"baseline: current volume {current_volume:.2f} versus "
                f"baseline {baseline:.2f}, a {abs(deviation):.2f}% deviation."
            )

        return str(row.get("behavior_reason", "Claim-volume behavior anomaly detected."))

    if status == "NORMAL":
        return "No behavior anomaly detected."

    return (
        "Behavior root cause cannot be determined because the "
        "behavior condition is not evaluable."
    )


def generate_behavior_recommendation(row):
    status = str(row.get("behavior_status", "")).upper()

    if status == "ANOMALOUS":
        current_volume = row.get("total_claim_volume")
        baseline = row.get("behavior_baseline_volume")

        if pd.notna(current_volume) and pd.notna(baseline):
            if current_volume > baseline:
                return (
                    "Investigate the claim-volume increase against the "
                    "previous 3-calendar-month baseline. Review provider "
                    "concentration, source or batch changes, and recent "
                    "processing activity to determine whether the increase "
                    "is expected or anomalous."
                )

            return (
                "Investigate the claim-volume decrease against the "
                "previous 3-calendar-month baseline. Validate missing "
                "batches, source delays, processing failures, or a genuine "
                "utilization decline."
            )

        return (
            "Review the anomalous claim-volume period and validate the "
            "underlying source and processing activity."
        )

    if status == "NORMAL":
        return "No immediate behavior remediation required."

    return (
        "No behavior remediation can be recommended until sufficient "
        "historical data is available."
    )


# ============================================================
# CREATE / UPGRADE OUTPUT TABLE
# ============================================================

def create_output_table(conn):

    create_sql = f"""
    CREATE TABLE IF NOT EXISTS {OUTPUT_TABLE} (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        analysis_type TEXT,

        current_period TEXT,

        run_id TEXT,
        batch_id TEXT,
        step_name TEXT,

        processing_start_at DATETIME,
        processing_end_at DATETIME,
        processing_time_minutes REAL,

        sla_limit_minutes REAL,
        sla_status TEXT,
        sla_compliance_percentage REAL,
        sla_met_count INTEGER,
        sla_breached_count INTEGER,
        sla_evaluable_runs INTEGER,

        provider_count INTEGER,
        total_claim_volume REAL,
        average_volume_risk REAL,
        maximum_volume_risk REAL,

        behavior_baseline_volume REAL,
        behavior_deviation_pct REAL,
        behavior_status TEXT,
        behavior_reason TEXT,

        root_cause TEXT,
        recommendation TEXT,

        records_processed REAL,
        duration_seconds REAL,

        created_at DATETIME
    )
    """

    conn.execute(create_sql)
    conn.commit()

    existing_columns = {
        row[1]
        for row in conn.execute(
            f"PRAGMA table_info({OUTPUT_TABLE})"
        ).fetchall()
    }

    new_columns = {
        "analysis_type": "TEXT",
        "current_period": "TEXT",
        "run_id": "TEXT",
        "batch_id": "TEXT",
        "step_name": "TEXT",
        "processing_start_at": "DATETIME",
        "processing_end_at": "DATETIME",
        "processing_time_minutes": "REAL",
        "sla_limit_minutes": "REAL",
        "sla_status": "TEXT",
        "sla_compliance_percentage": "REAL",
        "sla_met_count": "INTEGER",
        "sla_breached_count": "INTEGER",
        "sla_evaluable_runs": "INTEGER",
        "provider_count": "INTEGER",
        "total_claim_volume": "REAL",
        "average_volume_risk": "REAL",
        "maximum_volume_risk": "REAL",
        "behavior_baseline_volume": "REAL",
        "behavior_deviation_pct": "REAL",
        "behavior_status": "TEXT",
        "behavior_reason": "TEXT",
        "root_cause": "TEXT",
        "recommendation": "TEXT",
        "records_processed": "REAL",
        "duration_seconds": "REAL",
        "created_at": "DATETIME",
    }

    for column, column_type in new_columns.items():

        if column not in existing_columns:

            conn.execute(
                f"""
                ALTER TABLE {OUTPUT_TABLE}
                ADD COLUMN {column} {column_type}
                """
            )

    conn.commit()


# ============================================================
# SAVE SLA + BEHAVIOR RESULTS
# ============================================================

def save_results(
    conn,
    sla_df,
    behavior_df
):

    create_output_table(conn)

    # --------------------------------------------------------
    # Replace only output generated by this layer.
    # --------------------------------------------------------

    conn.execute(
        f"""
        DELETE FROM {OUTPUT_TABLE}
        """
    )

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    rows = []

    # --------------------------------------------------------
    # SLA COMPLIANCE ROWS
    # --------------------------------------------------------

    for _, row in sla_df.iterrows():

        def dt_string(value):

            if pd.isna(value):
                return None

            return pd.Timestamp(value).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

        rows.append(
            (
                "SLA_COMPLIANCE",

                None,

                row["run_id"],
                row["batch_id"],
                row["step_name"],

                dt_string(
                    row["started_at"]
                ),

                dt_string(
                    row["completed_at"]
                ),

                (
                    float(
                        row["processing_time_minutes"]
                    )
                    if pd.notna(
                        row["processing_time_minutes"]
                    )
                    else None
                ),

                SLA_LIMIT_MINUTES,

                row["sla_status"],

                (
                    float(
                        row["sla_compliance_percentage"]
                    )
                    if pd.notna(
                        row["sla_compliance_percentage"]
                    )
                    else None
                ),

                int(
                    row["sla_met_count"]
                ),

                int(
                    row["sla_breached_count"]
                ),

                int(
                    row["sla_evaluable_runs"]
                ),

                None,
                None,
                None,
                None,

                None,
                None,
                None,
                None,

                (
                    generate_sla_root_cause({
                        "sla_status": row["sla_status"],
                        "processing_time_minutes": row["processing_time_minutes"],
                        "sla_limit_minutes": SLA_LIMIT_MINUTES
                    })
                    if str(row["sla_status"]).upper()
                    in {"MINOR_OVERRUN", "BREACHED"}
                    else None
                ),

                (
                    generate_sla_recommendation({
                        "sla_status": row["sla_status"],
                        "processing_time_minutes": row["processing_time_minutes"],
                        "sla_limit_minutes": SLA_LIMIT_MINUTES
                    })
                    if str(row["sla_status"]).upper()
                    in {"MINOR_OVERRUN", "BREACHED"}
                    else None
                ),

                (
                    float(
                        row["records_processed"]
                    )
                    if pd.notna(
                        row["records_processed"]
                    )
                    else None
                ),

                (
                    float(
                        row["duration_seconds"]
                    )
                    if pd.notna(
                        row["duration_seconds"]
                    )
                    else None
                ),

                now,
            )
        )

    # --------------------------------------------------------
    # BEHAVIOR ROWS
    # --------------------------------------------------------

    for _, row in behavior_df.iterrows():

        rows.append(
            (
                "BEHAVIOR_ANOMALY",

                row["current_period"],

                None,
                None,
                None,

                None,
                None,
                None,

                None,
                None,
                None,
                None,
                None,
                None,

                (
                    int(row["provider_count"])
                    if pd.notna(
                        row["provider_count"]
                    )
                    else None
                ),

                (
                    float(
                        row["total_claim_volume"]
                    )
                    if pd.notna(
                        row["total_claim_volume"]
                    )
                    else None
                ),

                (
                    float(
                        row["average_volume_risk"]
                    )
                    if pd.notna(
                        row["average_volume_risk"]
                    )
                    else None
                ),

                (
                    float(
                        row["maximum_volume_risk"]
                    )
                    if pd.notna(
                        row["maximum_volume_risk"]
                    )
                    else None
                ),

                (
                    float(
                        row["behavior_baseline_volume"]
                    )
                    if pd.notna(
                        row["behavior_baseline_volume"]
                    )
                    else None
                ),

                (
                    float(
                        row["behavior_deviation_pct"]
                    )
                    if pd.notna(
                        row["behavior_deviation_pct"]
                    )
                    else None
                ),

                row["behavior_status"],
                row["behavior_reason"],

                generate_behavior_root_cause(row),
                generate_behavior_recommendation(row),

                None,
                None,

                now,
            )
        )

    insert_sql = f"""
    INSERT INTO {OUTPUT_TABLE} (

        analysis_type,

        current_period,

        run_id,
        batch_id,
        step_name,

        processing_start_at,
        processing_end_at,
        processing_time_minutes,

        sla_limit_minutes,
        sla_status,
        sla_compliance_percentage,
        sla_met_count,
        sla_breached_count,
        sla_evaluable_runs,

        provider_count,
        total_claim_volume,
        average_volume_risk,
        maximum_volume_risk,

        behavior_baseline_volume,
        behavior_deviation_pct,
        behavior_status,
        behavior_reason,

        root_cause,
        recommendation,

        records_processed,
        duration_seconds,

        created_at
    )
    VALUES (
        ?, ?,
        ?, ?, ?,
        ?, ?, ?,
        ?, ?, ?, ?, ?, ?,
        ?, ?, ?, ?,
        ?, ?, ?, ?,
        ?, ?,
        ?, ?,
        ?
    )
    """

    conn.executemany(
        insert_sql,
        rows
    )

    conn.commit()


# ============================================================
# PRINT SLA RESULTS
# ============================================================

def print_sla_results(sla_df):

    print("\n" + "=" * 80)
    print("SLA COMPLIANCE")
    print("=" * 80)

    if sla_df.empty:

        print(
            "No claims-processing run was found "
            "with timing information."
        )
        return

    evaluable = sla_df[
        sla_df["sla_status"].isin(
            ["MET", "BREACHED"]
        )
    ]

    print(
        f"SLA limit               : "
        f"{SLA_LIMIT_MINUTES:.0f} minutes"
    )

    print(
        f"Runs evaluated          : "
        f"{len(evaluable)}"
    )

    print(
        f"SLA MET                 : "
        f"{int(evaluable['sla_status'].eq('MET').sum())}"
    )

    print(
        f"SLA BREACHED            : "
        f"{int(evaluable['sla_status'].eq('BREACHED').sum())}"
    )

    if not evaluable.empty:

        compliance = (
            evaluable["sla_status"]
            .eq("MET")
            .mean()
            * 100.0
        )

        print(
            f"SLA Compliance         : "
            f"{compliance:.2f}%"
        )

    else:

        print(
            "SLA Compliance         : N/A"
        )

    print("\nRun details:")

    for _, row in sla_df.iterrows():

        print(
            f"\nRun ID          : "
            f"{row['run_id']}"
        )

        print(
            f"Step            : "
            f"{row['step_name']}"
        )

        print(
            f"Batch           : "
            f"{row['batch_id']}"
        )

        print(
            f"Processing time : "
            f"{row['processing_time_minutes']:.3f} min"
            if pd.notna(
                row["processing_time_minutes"]
            )
            else
            "Processing time : N/A"
        )

        print(
            f"SLA status      : "
            f"{row['sla_status']}"
        )

        print(
            f"Root cause      : "
            f"{generate_sla_root_cause(row)}"
        )

        print(
            f"Recommendation  : "
            f"{generate_sla_recommendation(row)}"
        )


# ============================================================
# PRINT BEHAVIOR RESULTS
# ============================================================

def print_behavior_results(behavior_df):

    print("\n" + "=" * 80)
    print("FFS CLAIMS BEHAVIOR ANALYSIS")
    print("=" * 80)

    for _, row in behavior_df.iterrows():

        print(
            f"\nPeriod: "
            f"{row['current_period']}"
        )

        print(
            f"Providers              : "
            f"{int(row['provider_count'])}"
        )

        print(
            f"Total current volume   : "
            f"{row['total_claim_volume']}"
        )

        print(
            f"Average volume risk    : "
            f"{row['average_volume_risk']}"
        )

        print(
            f"3-period baseline      : "
            f"{row['behavior_baseline_volume']}"
        )

        print(
            f"Deviation from baseline: "
            f"{row['behavior_deviation_pct']}"
        )

        print(
            f"Behavior status        : "
            f"{row['behavior_status']}"
        )

        print(
            f"Behavior reason        : "
            f"{row['behavior_reason']}"
        )

        print(
            f"Root cause             : "
            f"{generate_behavior_root_cause(row)}"
        )

        print(
            f"Recommendation         : "
            f"{generate_behavior_recommendation(row)}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n" + "=" * 80)
    print("CLAIMCARE — FFS SLA COMPLIANCE + BEHAVIOR ANALYSIS")
    print("=" * 80)

    # --------------------------------------------------------
    # LOAD SOURCE DATABASES
    # --------------------------------------------------------

    volume_df = load_volume_data()

    dq_df = load_dq_runs()

    print(
        f"\nVolume-risk rows loaded : "
        f"{len(volume_df):,}"
    )

    print(
        f"DQ/Dagster rows loaded  : "
        f"{len(dq_df):,}"
    )

    # --------------------------------------------------------
    # SLA COMPLIANCE
    #
    # Uses actual ClaimCare processing runs from dq_run_output.
    # --------------------------------------------------------

    sla_df = calculate_sla_compliance(
        dq_df
    )

    # --------------------------------------------------------
    # BEHAVIOR
    #
    # Uses the actual current-month FFS claim volume from the
    # provider volume database.
    # --------------------------------------------------------

    period_volume_df = aggregate_claim_volume(
        volume_df
    )

    behavior_df = calculate_behavior_anomaly(
        period_volume_df
    )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    conn = sqlite3.connect(
        OUTPUT_DB
    )

    try:

        save_results(
            conn,
            sla_df,
            behavior_df
        )

    finally:

        conn.close()

    # --------------------------------------------------------
    # DISPLAY
    # --------------------------------------------------------

    print_sla_results(
        sla_df
    )

    print_behavior_results(
        behavior_df
    )

    print("\n" + "=" * 80)
    print("COMPLETED")
    print("=" * 80)

    print(
        f"Output database : "
        f"{OUTPUT_DB}"
    )

    print(
        f"Output table    : "
        f"{OUTPUT_TABLE}"
    )

    print(
        "\nSLA risk is NOT calculated in this layer."
    )

    print(
        "This layer outputs only SLA compliance and behavior anomaly."
    )

    print(
        f"Separate output database: {OUTPUT_DB}"
    )


if __name__ == "__main__":
    main()