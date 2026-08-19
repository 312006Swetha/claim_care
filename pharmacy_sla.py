import sqlite3
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd


# ============================================================
# CLAIMCARE — PHARMACY SLA COMPLIANCE + BEHAVIOR ANALYSIS
# ============================================================
#
# INPUT DATABASES
#
# 1. volume_pharmacy.db
#    Existing Pharmacy volume-risk output:
#       - pharmacy_overall_volume_risk
#       - pharmacy_npi_volume_risk
#       - pharmacy_drug_volume_risk
#
# 2. pharmacy_database.db
#    Existing Pharmacy DQ execution history:
#       - dq_run_output
#
# OUTPUT
#
# 3. pharmacy_sla_behavior.db
#    Existing output table:
#       - pharmacy_sla_behavior
#
# IMPORTANT
# ----------
# This script does NOT create another output table.
# It upgrades the existing pharmacy_sla_behavior table
# by adding:
#
#       root_cause
#       recommendation
#
# ============================================================


# ============================================================
# PROJECT PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

# Existing Pharmacy volume-risk database — INPUT ONLY
VOLUME_DB = BASE_DIR / "volume_pharmacy.db"

# Existing Pharmacy DQ database — INPUT ONLY
DQ_DB = BASE_DIR / "pharmacy_database.db"

# Existing database for this layer's results
OUTPUT_DB = BASE_DIR / "pharmacy_sla_behavior.db"

OUTPUT_TABLE = "pharmacy_sla_behavior"


# ============================================================
# SLA CONFIGURATION
# ============================================================

# Maximum allowed processing duration.
SLA_LIMIT_MINUTES = 60.0

# Slightly-over-SLA processing is treated separately so the
# root cause/recommendation can distinguish a minor overrun
# from a material SLA breach.
SLA_MINOR_BREACH_PCT = 5.0


# ============================================================
# BEHAVIOR CONFIGURATION
# ============================================================

# Pharmacy overall data is annual, so use previous 3
# calendar years as the behavior baseline.
BEHAVIOR_BASELINE_PERIODS = 3

# If current annual claims deviate from the previous
# 3-year average by more than this percentage,
# mark the period as ANOMALOUS.
BEHAVIOR_DEVIATION_THRESHOLD_PCT = 50.0


# ============================================================
# LOAD PHARMACY VOLUME DATABASE
# ============================================================

def load_volume_data():

    if not VOLUME_DB.exists():
        raise FileNotFoundError(
            f"Pharmacy volume database not found:\n{VOLUME_DB}"
        )

    conn = sqlite3.connect(VOLUME_DB)

    try:

        tables = pd.read_sql_query(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """,
            conn
        )["name"].tolist()

        if "pharmacy_overall_volume_risk" not in tables:
            raise ValueError(
                "Table 'pharmacy_overall_volume_risk' was not found "
                f"in {VOLUME_DB}"
            )

        df = pd.read_sql_query(
            """
            SELECT
                calendar_year,
                total_claims,
                total_standardized_30_day_fills,
                total_beneficiaries,
                total_prescribers,
                final_volume_risk_score,
                volume_risk_level,
                baseline_type,
                baseline_years_used
            FROM pharmacy_overall_volume_risk
            ORDER BY calendar_year
            """,
            conn
        )

    finally:
        conn.close()

    return df


# ============================================================
# LOAD PHARMACY DQ / DAGSTER EXECUTION DATABASE
# ============================================================

def load_dq_runs():

    if not DQ_DB.exists():
        raise FileNotFoundError(
            f"Pharmacy DQ database not found:\n{DQ_DB}"
        )

    conn = sqlite3.connect(DQ_DB)

    try:

        tables = pd.read_sql_query(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
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
                quality_score,
                created_at
            FROM dq_run_output
            WHERE run_id IS NOT NULL
            ORDER BY started_at, id
            """,
            conn
        )

    finally:
        conn.close()

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
# SLA COMPLIANCE
# ============================================================

def calculate_sla_compliance(dq_df):

    if dq_df.empty:
        return pd.DataFrame()

    df = dq_df.copy()

    # --------------------------------------------------------
    # Pharmacy DQ step in the supplied database is:
    #     data_quality
    #
    # Prefer it. If unavailable, fall back to any step
    # having a valid duration.
    # --------------------------------------------------------

    pharmacy_steps = df[
        df["step_name"]
        .astype(str)
        .str.lower()
        .eq("data_quality")
    ].copy()

    if pharmacy_steps.empty:

        pharmacy_steps = df[
            df["duration_seconds"].notna()
        ].copy()

    if pharmacy_steps.empty:
        return pd.DataFrame()

    # --------------------------------------------------------
    # One SLA record per run
    # --------------------------------------------------------

    pharmacy_steps = (
        pharmacy_steps
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

    pharmacy_steps["processing_time_minutes"] = (
        pharmacy_steps["duration_seconds"]
        / 60.0
    )

    pharmacy_steps["sla_limit_minutes"] = (
        SLA_LIMIT_MINUTES
    )

    # --------------------------------------------------------
    # SLA STATUS
    #
    # No duration -> N/A
    # <= SLA -> MET
    # > SLA and <= SLA + 5% -> MINOR_BREACH
    # > SLA + 5% -> BREACHED
    # --------------------------------------------------------

    pharmacy_steps["sla_status"] = "N/A"

    available = (
        pharmacy_steps["processing_time_minutes"]
        .notna()
    )

    minor_breach_limit = (
        SLA_LIMIT_MINUTES
        *
        (1.0 + SLA_MINOR_BREACH_PCT / 100.0)
    )

    pharmacy_steps.loc[
        available
        &
        (
            pharmacy_steps["processing_time_minutes"]
            <=
            SLA_LIMIT_MINUTES
        ),
        "sla_status"
    ] = "MET"

    pharmacy_steps.loc[
        available
        &
        (
            pharmacy_steps["processing_time_minutes"]
            >
            SLA_LIMIT_MINUTES
        )
        &
        (
            pharmacy_steps["processing_time_minutes"]
            <=
            minor_breach_limit
        ),
        "sla_status"
    ] = "MINOR_BREACH"

    pharmacy_steps.loc[
        available
        &
        (
            pharmacy_steps["processing_time_minutes"]
            >
            minor_breach_limit
        ),
        "sla_status"
    ] = "BREACHED"

    # --------------------------------------------------------
    # OVERALL SLA COMPLIANCE
    # --------------------------------------------------------

    evaluable = pharmacy_steps[
        pharmacy_steps["sla_status"]
        .isin(
            ["MET", "MINOR_BREACH", "BREACHED"]
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
                ["MINOR_BREACH", "BREACHED"]
            )
            .sum()
        )

    else:

        compliance_pct = np.nan
        met_count = 0
        breached_count = 0

    pharmacy_steps["sla_compliance_percentage"] = (
        compliance_pct
    )

    pharmacy_steps["sla_met_count"] = (
        met_count
    )

    pharmacy_steps["sla_breached_count"] = (
        breached_count
    )

    pharmacy_steps["sla_evaluable_runs"] = (
        len(evaluable)
    )

    return pharmacy_steps


# ============================================================
# ROOT CAUSE + RECOMMENDATION
# ============================================================

def generate_root_cause_recommendation(
    sla_status=None,
    behavior_status=None,
    behavior_reason=None,
    step_name=None,
    dq_status=None
):
    """
    Generate explainable root cause and recommendation.

    Priority:
        1. DQ/property failure
        2. SLA material breach
        3. SLA minor breach
        4. Behavior anomaly
        5. No failure
    """

    step = (
        str(step_name).strip()
        if pd.notna(step_name)
        else ""
    )

    status = (
        str(dq_status).strip().upper()
        if pd.notna(dq_status)
        else ""
    )

    sla = (
        str(sla_status).strip().upper()
        if pd.notna(sla_status)
        else ""
    )

    behavior = (
        str(behavior_status).strip().upper()
        if pd.notna(behavior_status)
        else ""
    )

    # --------------------------------------------------------
    # 1. DQ / PROPERTY FAILURE
    # --------------------------------------------------------

    if status in [
        "FAILED",
        "FAIL",
        "ERROR"
    ]:

        root_cause = (
            f"Data quality property or processing step "
            f"'{step}' failed during execution."
        )

        recommendation = (
            f"Review the failed '{step}' validation, identify "
            f"the records or fields causing the failure, correct "
            f"the underlying data issue, and rerun the validation."
        )

        return root_cause, recommendation

    # --------------------------------------------------------
    # 2. MATERIAL SLA BREACH
    # --------------------------------------------------------

    if sla == "BREACHED":

        root_cause = (
            f"Pharmacy processing time materially exceeded the "
            f"configured SLA limit of {SLA_LIMIT_MINUTES:.0f} minutes."
        )

        recommendation = (
            "Investigate the affected pharmacy processing run for "
            "processing bottlenecks, queueing delays, retries, "
            "database/query performance, input-volume spikes, and "
            "slow pipeline steps. Optimize the affected step and "
            "prioritize remediation before the next batch."
        )

        return root_cause, recommendation

    # --------------------------------------------------------
    # 3. MINOR SLA BREACH
    # --------------------------------------------------------

    if sla == "MINOR_BREACH":

        root_cause = (
            f"Pharmacy processing time was slightly above the "
            f"{SLA_LIMIT_MINUTES:.0f}-minute SLA limit, within the "
            f"{SLA_MINOR_BREACH_PCT:.0f}% minor-breach tolerance. "
            "This indicates a small processing delay or transient "
            "execution overhead rather than a material breach."
        )

        recommendation = (
            "Review the run for transient queueing, minor execution "
            "overhead, or small upstream/downstream delays. Monitor "
            "the next pharmacy runs and investigate further if the "
            "minor SLA overrun repeats."
        )

        return root_cause, recommendation

    # --------------------------------------------------------
    # 4. BEHAVIOR ANOMALY
    # --------------------------------------------------------

    if behavior == "ANOMALOUS":

        reason_text = (
            str(behavior_reason)
            if pd.notna(behavior_reason)
            else "Annual claim volume deviated from the baseline."
        )

        root_cause = (
            "Annual pharmacy claim volume deviated significantly "
            "from the previous 3-calendar-year baseline. "
            f"Reason: {reason_text}"
        )

        recommendation = (
            "Investigate the change in claim volume by checking "
            "incoming data volume, missing records, duplicated "
            "records, source-system changes, and unusual pharmacy "
            "activity."
        )

        return root_cause, recommendation

    # --------------------------------------------------------
    # 5. NO FAILURE
    # --------------------------------------------------------

    return (
        "No SLA, data-quality, or behavior failure detected.",
        "No corrective action required."
    )


# ============================================================
# PERIOD-LEVEL PHARMACY VOLUME
# ============================================================

def aggregate_pharmacy_volume(volume_df):

    df = volume_df.copy()

    df["calendar_year"] = pd.to_numeric(
        df["calendar_year"],
        errors="coerce"
    )

    df["total_claims"] = pd.to_numeric(
        df["total_claims"],
        errors="coerce"
    )

    df["total_standardized_30_day_fills"] = pd.to_numeric(
        df["total_standardized_30_day_fills"],
        errors="coerce"
    )

    df["total_beneficiaries"] = pd.to_numeric(
        df["total_beneficiaries"],
        errors="coerce"
    )

    df["total_prescribers"] = pd.to_numeric(
        df["total_prescribers"],
        errors="coerce"
    )

    df["final_volume_risk_score"] = pd.to_numeric(
        df["final_volume_risk_score"],
        errors="coerce"
    )

    # One row per calendar year already exists in the
    # pharmacy_overall_volume_risk table.

    period_df = (
        df[
            [
                "calendar_year",
                "total_claims",
                "total_standardized_30_day_fills",
                "total_beneficiaries",
                "total_prescribers",
                "final_volume_risk_score",
                "volume_risk_level"
            ]
        ]
        .dropna(
            subset=["calendar_year"]
        )
        .drop_duplicates(
            subset=["calendar_year"],
            keep="last"
        )
        .sort_values("calendar_year")
        .reset_index(drop=True)
    )

    return period_df


# ============================================================
# SIMPLE BEHAVIOR ANALYSIS
# ============================================================

def calculate_behavior_anomaly(period_df):

    df = period_df.copy()

    df["calendar_year"] = (
        df["calendar_year"]
        .astype(int)
    )

    df = (
        df
        .sort_values("calendar_year")
        .drop_duplicates(
            subset=["calendar_year"],
            keep="last"
        )
        .set_index("calendar_year")
    )

    if df.empty:
        return period_df.copy()

    first_year = int(df.index.min())
    last_year = int(df.index.max())

    full_years = pd.Index(
        range(
            first_year,
            last_year + 1
        ),
        name="calendar_year"
    )

    # Add genuinely absent calendar years.
    df = df.reindex(full_years)

    # Missing years are treated as zero claims/volume.
    df["total_claims"] = (
        pd.to_numeric(
            df["total_claims"],
            errors="coerce"
        )
        .fillna(0)
    )

    df["total_standardized_30_day_fills"] = (
        pd.to_numeric(
            df["total_standardized_30_day_fills"],
            errors="coerce"
        )
        .fillna(0)
    )

    df["total_beneficiaries"] = (
        pd.to_numeric(
            df["total_beneficiaries"],
            errors="coerce"
        )
        .fillna(0)
    )

    df["total_prescribers"] = (
        pd.to_numeric(
            df["total_prescribers"],
            errors="coerce"
        )
        .fillna(0)
    )

    df["final_volume_risk_score"] = pd.to_numeric(
        df["final_volume_risk_score"],
        errors="coerce"
    )

    df["volume_risk_level"] = (
        df["volume_risk_level"]
        .fillna("N/A")
    )

    df = df.reset_index()

    # --------------------------------------------------------
    # Main behavior metric:
    # total annual claims
    # --------------------------------------------------------

    df["behavior_baseline_claims"] = np.nan
    df["behavior_deviation_pct"] = np.nan

    statuses = []
    reasons = []

    for i in range(len(df)):

        if i < BEHAVIOR_BASELINE_PERIODS:

            statuses.append("N/A")

            reasons.append(
                "Insufficient previous calendar years "
                "for behavior baseline."
            )

            continue

        history = df.iloc[
            i - BEHAVIOR_BASELINE_PERIODS:i
        ]

        historical_claims = pd.to_numeric(
            history["total_claims"],
            errors="coerce"
        )

        current_claims = pd.to_numeric(
            df.loc[i, "total_claims"],
            errors="coerce"
        )

        if (
            len(historical_claims)
            !=
            BEHAVIOR_BASELINE_PERIODS
            or
            pd.isna(current_claims)
        ):

            statuses.append("N/A")

            reasons.append(
                "Insufficient valid historical claim volume."
            )

            continue

        baseline = (
            historical_claims
            .mean()
        )

        df.loc[
            i,
            "behavior_baseline_claims"
        ] = baseline

        # ----------------------------------------------------
        # Zero-baseline handling
        # ----------------------------------------------------

        if baseline == 0:

            if current_claims == 0:

                deviation = 0.0
                status = "NORMAL"

                reason = (
                    "Current and previous 3 calendar years "
                    "have zero claim volume."
                )

            else:

                deviation = np.inf
                status = "ANOMALOUS"

                reason = (
                    "Current claim volume is positive while "
                    "the previous 3-calendar-year baseline "
                    "is zero."
                )

        else:

            deviation = (
                abs(
                    current_claims
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
                    if current_claims > baseline
                    else "decreased"
                )

                reason = (
                    f"Annual claim volume {direction} by "
                    f"{deviation:.2f}% from the previous "
                    f"{BEHAVIOR_BASELINE_PERIODS}-year "
                    "average."
                )

            else:

                status = "NORMAL"

                reason = (
                    "Annual claim volume is within the "
                    f"configured "
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
# CREATE / UPGRADE EXISTING OUTPUT TABLE
# ============================================================

def create_output_table(conn):

    # --------------------------------------------------------
    # IMPORTANT:
    # This only creates the table if it does not exist.
    #
    # If pharmacy_sla_behavior already exists, it is NOT
    # replaced or recreated.
    # --------------------------------------------------------

    create_sql = f"""
    CREATE TABLE IF NOT EXISTS {OUTPUT_TABLE} (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        analysis_type TEXT,

        calendar_year INTEGER,

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

        total_claims REAL,
        total_standardized_30_day_fills REAL,
        total_beneficiaries REAL,
        total_prescribers REAL,

        final_volume_risk_score REAL,
        volume_risk_level TEXT,

        behavior_baseline_claims REAL,
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

    # --------------------------------------------------------
    # CHECK EXISTING COLUMNS
    # --------------------------------------------------------

    existing_columns = {
        row[1]
        for row in conn.execute(
            f"PRAGMA table_info({OUTPUT_TABLE})"
        ).fetchall()
    }

    # --------------------------------------------------------
    # ADD MISSING COLUMNS TO THE EXISTING TABLE
    # --------------------------------------------------------

    new_columns = {

        "analysis_type": "TEXT",
        "calendar_year": "INTEGER",

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

        "total_claims": "REAL",
        "total_standardized_30_day_fills": "REAL",
        "total_beneficiaries": "REAL",
        "total_prescribers": "REAL",

        "final_volume_risk_score": "REAL",
        "volume_risk_level": "TEXT",

        "behavior_baseline_claims": "REAL",
        "behavior_deviation_pct": "REAL",
        "behavior_status": "TEXT",
        "behavior_reason": "TEXT",

        # NEW COLUMNS
        "root_cause": "TEXT",
        "recommendation": "TEXT",

        "records_processed": "REAL",
        "duration_seconds": "REAL",

        "created_at": "DATETIME",
    }

    for column, column_type in new_columns.items():

        if column not in existing_columns:

            print(
                f"Adding column '{column}' "
                f"to existing table '{OUTPUT_TABLE}'..."
            )

            conn.execute(
                f"""
                ALTER TABLE {OUTPUT_TABLE}
                ADD COLUMN {column} {column_type}
                """
            )

    conn.commit()


# ============================================================
# SAVE RESULTS
# ============================================================

def save_results(
    conn,
    sla_df,
    behavior_df
):

    # Upgrade existing table if necessary.
    create_output_table(conn)

    # --------------------------------------------------------
    # Replace only this layer's results.
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

    # ========================================================
    # SLA COMPLIANCE ROWS
    # ========================================================

    if not sla_df.empty:

        for _, row in sla_df.iterrows():

            def dt_string(value):

                if pd.isna(value):
                    return None

                return pd.Timestamp(
                    value
                ).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )

            # ------------------------------------------------
            # Generate root cause and recommendation
            # ------------------------------------------------

            sla_requires_rca = str(
                row["sla_status"]
            ).upper() in {
                "MINOR_BREACH",
                "BREACHED"
            }

            if sla_requires_rca:
                root_cause, recommendation = (
                    generate_root_cause_recommendation(
                        sla_status=row["sla_status"],
                        step_name=row["step_name"],
                        dq_status=row["status"]
                    )
                )
            else:
                root_cause = None
                recommendation = None

            rows.append(
                (

                    # analysis_type
                    "SLA_COMPLIANCE",

                    # calendar_year
                    None,

                    # run_id
                    row["run_id"],

                    # batch_id
                    row["batch_id"],

                    # step_name
                    row["step_name"],

                    # processing_start_at
                    dt_string(
                        row["started_at"]
                    ),

                    # processing_end_at
                    dt_string(
                        row["completed_at"]
                    ),

                    # processing_time_minutes
                    (
                        float(
                            row["processing_time_minutes"]
                        )
                        if pd.notna(
                            row["processing_time_minutes"]
                        )
                        else None
                    ),

                    # sla_limit_minutes
                    SLA_LIMIT_MINUTES,

                    # sla_status
                    row["sla_status"],

                    # sla_compliance_percentage
                    (
                        float(
                            row["sla_compliance_percentage"]
                        )
                        if pd.notna(
                            row["sla_compliance_percentage"]
                        )
                        else None
                    ),

                    # sla_met_count
                    int(
                        row["sla_met_count"]
                    ),

                    # sla_breached_count
                    int(
                        row["sla_breached_count"]
                    ),

                    # sla_evaluable_runs
                    int(
                        row["sla_evaluable_runs"]
                    ),

                    # volume data
                    None,
                    None,
                    None,
                    None,

                    # volume risk
                    None,
                    None,

                    # behavior
                    None,
                    None,
                    None,
                    None,

                    # NEW
                    root_cause,
                    recommendation,

                    # processing
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

                    # created_at
                    now,
                )
            )

    # ========================================================
    # BEHAVIOR ROWS
    # ========================================================

    if not behavior_df.empty:

        for _, row in behavior_df.iterrows():

            # ------------------------------------------------
            # Generate root cause and recommendation
            # ------------------------------------------------

            root_cause, recommendation = (
                generate_root_cause_recommendation(
                    behavior_status=row["behavior_status"],
                    behavior_reason=row["behavior_reason"]
                )
            )

            rows.append(
                (

                    # analysis_type
                    "BEHAVIOR_ANOMALY",

                    # calendar_year
                    int(
                        row["calendar_year"]
                    ),

                    # run_id
                    None,

                    # batch_id
                    None,

                    # step_name
                    None,

                    # processing start
                    None,

                    # processing end
                    None,

                    # processing time
                    None,

                    # SLA limit
                    None,

                    # SLA status
                    None,

                    # SLA compliance
                    None,

                    # SLA met
                    None,

                    # SLA breached
                    None,

                    # SLA evaluable
                    None,

                    # total claims
                    (
                        float(
                            row["total_claims"]
                        )
                        if pd.notna(
                            row["total_claims"]
                        )
                        else None
                    ),

                    # fills
                    (
                        float(
                            row[
                                "total_standardized_30_day_fills"
                            ]
                        )
                        if pd.notna(
                            row[
                                "total_standardized_30_day_fills"
                            ]
                        )
                        else None
                    ),

                    # beneficiaries
                    (
                        float(
                            row["total_beneficiaries"]
                        )
                        if pd.notna(
                            row["total_beneficiaries"]
                        )
                        else None
                    ),

                    # prescribers
                    (
                        float(
                            row["total_prescribers"]
                        )
                        if pd.notna(
                            row["total_prescribers"]
                        )
                        else None
                    ),

                    # volume risk score
                    (
                        float(
                            row["final_volume_risk_score"]
                        )
                        if pd.notna(
                            row["final_volume_risk_score"]
                        )
                        else None
                    ),

                    # volume risk level
                    row["volume_risk_level"],

                    # behavior baseline
                    (
                        float(
                            row["behavior_baseline_claims"]
                        )
                        if pd.notna(
                            row["behavior_baseline_claims"]
                        )
                        else None
                    ),

                    # behavior deviation
                    (
                        float(
                            row["behavior_deviation_pct"]
                        )
                        if pd.notna(
                            row["behavior_deviation_pct"]
                        )
                        else None
                    ),

                    # behavior status
                    row["behavior_status"],

                    # behavior reason
                    row["behavior_reason"],

                    # NEW ROOT CAUSE
                    root_cause,

                    # NEW RECOMMENDATION
                    recommendation,

                    # records processed
                    None,

                    # duration
                    None,

                    # created_at
                    now,
                )
            )

    # ========================================================
    # INSERT INTO EXISTING TABLE
    # ========================================================

    insert_sql = f"""
    INSERT INTO {OUTPUT_TABLE} (

        analysis_type,

        calendar_year,

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

        total_claims,
        total_standardized_30_day_fills,
        total_beneficiaries,
        total_prescribers,

        final_volume_risk_score,
        volume_risk_level,

        behavior_baseline_claims,
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

        ?, ?,

        ?, ?, ?, ?,

        ?, ?,

        ?, ?,

        ?
    )
    """

    if rows:

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
    print("PHARMACY SLA COMPLIANCE")
    print("=" * 80)

    if sla_df.empty:

        print(
            "No pharmacy-processing run was found "
            "with timing information."
        )

        return

    evaluable = sla_df[
        sla_df["sla_status"].isin(
            ["MET", "MINOR_BREACH", "BREACHED"]
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
        f"SLA MINOR BREACH        : "
        f"{int(evaluable['sla_status'].eq('MINOR_BREACH').sum())}"
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

        if pd.notna(
            row["processing_time_minutes"]
        ):

            print(
                f"Processing time : "
                f"{row['processing_time_minutes']:.3f} min"
            )

        else:

            print(
                "Processing time : N/A"
            )

        print(
            f"SLA status      : "
            f"{row['sla_status']}"
        )

        # ----------------------------------------------------
        # Root cause + recommendation
        # ----------------------------------------------------

        root_cause, recommendation = (
            generate_root_cause_recommendation(
                sla_status=row["sla_status"],
                step_name=row["step_name"],
                dq_status=row["status"]
            )
        )

        print(
            f"Root cause      : "
            f"{root_cause}"
        )

        print(
            f"Recommendation  : "
            f"{recommendation}"
        )


# ============================================================
# PRINT BEHAVIOR RESULTS
# ============================================================

def print_behavior_results(behavior_df):

    print("\n" + "=" * 80)
    print("PHARMACY BEHAVIOR ANALYSIS")
    print("=" * 80)

    if behavior_df.empty:

        print(
            "No pharmacy behavior data was found."
        )

        return

    for _, row in behavior_df.iterrows():

        print(
            f"\nYear: "
            f"{int(row['calendar_year'])}"
        )

        print(
            f"Total annual claims       : "
            f"{row['total_claims']}"
        )

        print(
            f"3-year baseline claims    : "
            f"{row['behavior_baseline_claims']}"
        )

        print(
            f"Deviation from baseline  : "
            f"{row['behavior_deviation_pct']}"
        )

        print(
            f"Existing volume risk     : "
            f"{row['final_volume_risk_score']}"
        )

        print(
            f"Existing risk level      : "
            f"{row['volume_risk_level']}"
        )

        print(
            f"Behavior status          : "
            f"{row['behavior_status']}"
        )

        print(
            f"Behavior reason          : "
            f"{row['behavior_reason']}"
        )

        # ----------------------------------------------------
        # Root cause + recommendation
        # ----------------------------------------------------

        root_cause, recommendation = (
            generate_root_cause_recommendation(
                behavior_status=row["behavior_status"],
                behavior_reason=row["behavior_reason"]
            )
        )

        print(
            f"Root cause               : "
            f"{root_cause}"
        )

        print(
            f"Recommendation           : "
            f"{recommendation}"
        )


# ============================================================
# VERIFY OUTPUT TABLE
# ============================================================

def verify_output_table():

    if not OUTPUT_DB.exists():

        print(
            "\nOutput database was not created."
        )

        return

    conn = sqlite3.connect(
        OUTPUT_DB
    )

    try:

        columns = pd.read_sql_query(
            f"""
            PRAGMA table_info({OUTPUT_TABLE})
            """,
            conn
        )

        print("\n" + "=" * 80)
        print("OUTPUT TABLE VERIFICATION")
        print("=" * 80)

        print(
            f"Database : {OUTPUT_DB}"
        )

        print(
            f"Table    : {OUTPUT_TABLE}"
        )

        print("\nColumns:")

        for column in columns["name"].tolist():

            print(
                f"  - {column}"
            )

        required_columns = [
            "root_cause",
            "recommendation"
        ]

        print("\nNew columns:")

        for column in required_columns:

            if column in columns["name"].tolist():

                print(
                    f"  ✓ {column}"
                )

            else:

                print(
                    f"  ✗ {column} NOT FOUND"
                )

    finally:

        conn.close()


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n" + "=" * 80)
    print(
        "CLAIMCARE — PHARMACY SLA COMPLIANCE + "
        "BEHAVIOR ANALYSIS"
    )
    print("=" * 80)

    # --------------------------------------------------------
    # LOAD EXISTING VOLUME + DQ OUTPUTS
    # --------------------------------------------------------

    volume_df = load_volume_data()

    dq_df = load_dq_runs()

    print(
        f"\nPharmacy volume rows loaded : "
        f"{len(volume_df):,}"
    )

    print(
        f"Pharmacy DQ rows loaded     : "
        f"{len(dq_df):,}"
    )

    # --------------------------------------------------------
    # SLA COMPLIANCE
    # --------------------------------------------------------

    sla_df = calculate_sla_compliance(
        dq_df
    )

    # --------------------------------------------------------
    # BEHAVIOR
    # --------------------------------------------------------

    period_volume_df = aggregate_pharmacy_volume(
        volume_df
    )

    behavior_df = calculate_behavior_anomaly(
        period_volume_df
    )

    # --------------------------------------------------------
    # SAVE TO EXISTING DATABASE
    # --------------------------------------------------------

    print(
        f"\nSaving results to existing database:"
    )

    print(
        f"  {OUTPUT_DB}"
    )

    print(
        f"Existing table:"
    )

    print(
        f"  {OUTPUT_TABLE}"
    )

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

    # --------------------------------------------------------
    # VERIFY DATABASE
    # --------------------------------------------------------

    verify_output_table()

    # --------------------------------------------------------
    # COMPLETED
    # --------------------------------------------------------

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
        "\nRoot cause and recommendation "
        "are stored in the existing table."
    )

    print(
        "No additional output table was created."
    )

    print(
        "\nSLA risk is NOT calculated in this layer."
    )

    print(
        "This layer outputs SLA compliance, "
        "behavior anomaly, root cause, and recommendation."
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()