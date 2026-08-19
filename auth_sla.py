import sqlite3
import json
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# CLAIMCARE — AUTHORIZATION DAGSTER + SLA + BEHAVIOR ANALYSIS
# ============================================================
#
# SOURCE
#   claim_sentinel.db
#       └── authorization_dataset
#
# OUTPUT
#   auth_sla.db
#       └── dq_run_output
#
# The output table uses the same column names as the supplied
# claims_dagster dq_run_output table.
#
# SLA:
#   approval_date - request_date
#
#   <= 72 hours          -> MET
#   > 72 and <= 75.6     -> MINOR_BREACH
#   > 75.6               -> BREACHED
#
# BEHAVIOR:
#   Monthly authorization_count =
#       count(authorization_id)
#
#   Baseline =
#       previous 3 calendar months average
#
#   Deviation =
#       abs(current - baseline) / baseline * 100
#
#   > 50% -> ANOMALOUS
#
# No Robust Z-score, PSI, Isolation Forest, or ML algorithm.
# No provider/NPI grouping is used for SLA/behavior volume.
# ============================================================


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_DB = BASE_DIR / "claim_sentinel.db"
INPUT_TABLE = "authorization_dataset"

OUTPUT_DB = BASE_DIR / "auth_sla.db"
OUTPUT_TABLE = "dq_run_output"


# ============================================================
# SLA CONFIGURATION
# ============================================================

# Replace with the SLA agreed for your authorization workflow.
SLA_LIMIT_HOURS = 72.0

# Small overrun tolerance.
SLA_MINOR_BREACH_PCT = 5.0


# ============================================================
# BEHAVIOR CONFIGURATION
# ============================================================

BEHAVIOR_BASELINE_PERIODS = 3
BEHAVIOR_DEVIATION_THRESHOLD_PCT = 50.0


# ============================================================
# CLAIMS DAGSTER COLUMN NAMES
# Taken from the supplied claim_dagster dq_run_output schema.
# ============================================================

DAGSTER_COLUMNS = [
    "run_id",
    "step_name",
    "status",
    "started_at",
    "completed_at",
    "duration_seconds",
    "records_processed",
    "dataset_name",
    "batch_id",
    "error_message",
    "dimension",
    "field_name",
    "rule_name",
    "affected_rows",
    "affected_pct",
    "severity",
    "message",
    "total_records",
    "passed_records",
    "failed_records",
    "total_rules_checked",
    "total_violations",
    "critical_count",
    "high_count",
    "warning_count",
    "info_count",
    "quality_score",
    "overall_status",
    "root_cause",
    "recommendation",
    "npi",
    "npi_total_rows",
    "npi_affected_rows",
    "npi_affected_pct",
    "npi_completeness_score",
    "created_at",
    "npi_dimension_score",
]


# ============================================================
# LOAD AUTHORIZATION DATA FROM claim_sentinel.db
# ============================================================

def load_authorization_data():
    if not INPUT_DB.exists():
        raise FileNotFoundError(
            f"Input database not found:\n{INPUT_DB}"
        )

    conn = sqlite3.connect(INPUT_DB)

    try:
        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table'",
            conn,
        )["name"].tolist()

        if INPUT_TABLE not in tables:
            raise ValueError(
                f"Table '{INPUT_TABLE}' was not found in {INPUT_DB}"
            )

        df = pd.read_sql_query(
            f"""
            SELECT
                authorization_id,
                bene_id,
                provider_id,
                service_code,
                request_date,
                approval_date,
                status,
                expiry_date,
                urgency,
                batch_id
            FROM "{INPUT_TABLE}"
            """,
            conn,
        )
    finally:
        conn.close()

    required = [
        "authorization_id",
        "bene_id",
        "provider_id",
        "service_code",
        "request_date",
        "approval_date",
        "status",
        "expiry_date",
        "urgency",
        "batch_id",
    ]

    missing = [c for c in required if c not in df.columns]

    if missing:
        raise ValueError(
            "Missing required authorization columns: "
            + ", ".join(missing)
        )

    for col in ["request_date", "approval_date", "expiry_date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")

    return df


# ============================================================
# CREATE OUTPUT DATABASE + TABLE
# ============================================================

def create_output_database():
    conn = sqlite3.connect(OUTPUT_DB)

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {OUTPUT_TABLE} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            step_name TEXT,
            status TEXT,
            started_at DATETIME,
            completed_at DATETIME,
            duration_seconds REAL,
            records_processed INTEGER,
            dataset_name TEXT,
            batch_id TEXT,
            error_message TEXT,
            dimension TEXT,
            field_name TEXT,
            rule_name TEXT,
            affected_rows INTEGER,
            affected_pct REAL,
            severity TEXT,
            message TEXT,
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
            root_cause TEXT,
            recommendation TEXT,
            npi TEXT,
            npi_total_rows INTEGER,
            npi_affected_rows INTEGER,
            npi_affected_pct REAL,
            npi_completeness_score REAL,
            created_at DATETIME,
            npi_dimension_score REAL
        )
        """
    )

    conn.commit()
    return conn


# ============================================================
# SLA CALCULATION
# ============================================================

def calculate_sla(df):
    work = df.copy()

    work["turnaround_hours"] = (
        (
            work["approval_date"] - work["request_date"]
        ).dt.total_seconds()
        / 3600.0
    )

    work["sla_status"] = "N/A"

    evaluable = (
        work["request_date"].notna()
        & work["approval_date"].notna()
        & work["turnaround_hours"].notna()
        & (work["turnaround_hours"] >= 0)
    )

    minor_limit = SLA_LIMIT_HOURS * (
        1.0 + SLA_MINOR_BREACH_PCT / 100.0
    )

    work.loc[
        evaluable
        & (work["turnaround_hours"] <= SLA_LIMIT_HOURS),
        "sla_status",
    ] = "MET"

    work.loc[
        evaluable
        & (work["turnaround_hours"] > SLA_LIMIT_HOURS)
        & (work["turnaround_hours"] <= minor_limit),
        "sla_status",
    ] = "MINOR_BREACH"

    work.loc[
        evaluable
        & (work["turnaround_hours"] > minor_limit),
        "sla_status",
    ] = "BREACHED"

    evaluated = work[
        work["sla_status"].isin(
            ["MET", "MINOR_BREACH", "BREACHED"]
        )
    ]

    met_count = int(
        evaluated["sla_status"].eq("MET").sum()
    )
    minor_count = int(
        evaluated["sla_status"].eq("MINOR_BREACH").sum()
    )
    breached_count = int(
        evaluated["sla_status"].eq("BREACHED").sum()
    )

    compliance = (
        (met_count / len(evaluated) * 100.0)
        if len(evaluated) > 0
        else np.nan
    )

    work["sla_compliance_percentage"] = compliance
    work["sla_met_count"] = met_count
    work["sla_minor_breach_count"] = minor_count
    work["sla_breached_count"] = breached_count
    work["sla_evaluable_requests"] = len(evaluated)

    return work


# ============================================================
# MONTHLY AUTHORIZATION VOLUME
# ============================================================

def aggregate_monthly_volume(df):
    work = df.copy()

    work["request_month"] = (
        work["request_date"].dt.to_period("M")
    )

    monthly = (
        work.dropna(subset=["request_month"])
        .groupby("request_month")
        .agg(
            authorization_count=(
                "authorization_id",
                "count",
            ),
            unique_beneficiaries=(
                "bene_id",
                "nunique",
            ),
            unique_providers=(
                "provider_id",
                "nunique",
            ),
            unique_services=(
                "service_code",
                "nunique",
            ),
            urgent_count=(
                "urgency",
                lambda x: (
                    x.astype(str)
                    .str.strip()
                    .str.lower()
                    .eq("urgent")
                    .sum()
                ),
            ),
        )
        .reset_index()
    )

    monthly["request_month"] = (
        monthly["request_month"].astype(str)
    )

    return (
        monthly
        .sort_values("request_month")
        .reset_index(drop=True)
    )


# ============================================================
# SIMPLE BEHAVIOR ANALYSIS
# ============================================================

def calculate_behavior(monthly_df):
    df = monthly_df.copy()

    if df.empty:
        return df

    df["request_month"] = pd.PeriodIndex(
        df["request_month"],
        freq="M",
    )

    df = (
        df
        .sort_values("request_month")
        .drop_duplicates(
            subset=["request_month"],
            keep="last",
        )
        .set_index("request_month")
    )

    full_months = pd.period_range(
        start=df.index.min(),
        end=df.index.max(),
        freq="M",
    )

    df = df.reindex(full_months)

    for col in [
        "authorization_count",
        "unique_beneficiaries",
        "unique_providers",
        "unique_services",
        "urgent_count",
    ]:
        df[col] = (
            pd.to_numeric(df[col], errors="coerce")
            .fillna(0)
        )

    df["request_month"] = df.index.astype(str)
    df = df.reset_index(drop=True)

    df["behavior_baseline_volume"] = np.nan
    df["behavior_deviation_pct"] = np.nan

    statuses = []
    reasons = []

    for i in range(len(df)):
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

        current = float(
            df.loc[i, "authorization_count"]
        )

        baseline = float(
            history["authorization_count"].mean()
        )

        df.loc[
            i, "behavior_baseline_volume"
        ] = baseline

        if baseline == 0:
            if current == 0:
                deviation = 0.0
                status = "NORMAL"
                reason = (
                    "Current and previous 3 calendar months "
                    "have zero authorization volume."
                )
            else:
                deviation = np.inf
                status = "ANOMALOUS"
                reason = (
                    "Current authorization volume is positive "
                    "while the previous 3-calendar-month "
                    "baseline is zero."
                )
        else:
            deviation = (
                abs(current - baseline)
                / baseline
            ) * 100.0

            if deviation > BEHAVIOR_DEVIATION_THRESHOLD_PCT:
                status = "ANOMALOUS"
                direction = (
                    "increased"
                    if current > baseline
                    else "decreased"
                )
                reason = (
                    f"Authorization volume {direction} by "
                    f"{deviation:.2f}% from the previous "
                    f"{BEHAVIOR_BASELINE_PERIODS}-month average."
                )
            else:
                status = "NORMAL"
                reason = (
                    "Authorization volume is within the "
                    f"configured "
                    f"{BEHAVIOR_DEVIATION_THRESHOLD_PCT:.0f}% "
                    "behavior threshold."
                )

        df.loc[
            i, "behavior_deviation_pct"
        ] = deviation

        statuses.append(status)
        reasons.append(reason)

    df["behavior_status"] = statuses
    df["behavior_reason"] = reasons

    return df


# ============================================================
# ROOT CAUSE + RECOMMENDATION
# ============================================================

def sla_root_cause(row):
    status = str(row["sla_status"]).upper()

    if status == "BREACHED":
        excess = (
            float(row["turnaround_hours"])
            - SLA_LIMIT_HOURS
        )
        return (
            f"Authorization turnaround exceeded the "
            f"{SLA_LIMIT_HOURS:.0f}-hour SLA by "
            f"{excess:.2f} hours."
        )

    if status == "MINOR_BREACH":
        excess = (
            float(row["turnaround_hours"])
            - SLA_LIMIT_HOURS
        )
        return (
            f"Authorization turnaround was slightly above "
            f"the {SLA_LIMIT_HOURS:.0f}-hour SLA by "
            f"{excess:.2f} hours, indicating a minor "
            f"processing delay or transient overhead."
        )

    return None


def sla_recommendation(row):
    status = str(row["sla_status"]).upper()

    if status == "BREACHED":
        return (
            "Investigate authorization processing bottlenecks, "
            "queueing delays, approval bottlenecks, manual review "
            "delays, and upstream/downstream dependencies."
        )

    if status == "MINOR_BREACH":
        return (
            "Review transient queueing, execution overhead, "
            "or minor approval delays. Monitor subsequent "
            "requests and investigate if the overrun repeats."
        )

    return None


def behavior_root_cause(row):
    if str(row["behavior_status"]).upper() != "ANOMALOUS":
        return None

    current = float(row["authorization_count"])
    baseline = float(row["behavior_baseline_volume"])
    deviation = float(row["behavior_deviation_pct"])

    direction = (
        "increased"
        if current > baseline
        else "decreased"
    )

    return (
        f"Authorization volume {direction} materially "
        f"from the previous {BEHAVIOR_BASELINE_PERIODS}-month "
        f"baseline: current={current:.0f}, "
        f"baseline={baseline:.2f}, "
        f"deviation={abs(deviation):.2f}%."
    )


def behavior_recommendation(row):
    if str(row["behavior_status"]).upper() != "ANOMALOUS":
        return None

    if (
        row["authorization_count"]
        > row["behavior_baseline_volume"]
    ):
        return (
            "Investigate the authorization-volume increase "
            "against the previous 3-month baseline. Review "
            "provider concentration, service-code changes, "
            "urgent requests, and source or batch changes."
        )

    return (
        "Investigate the authorization-volume decrease "
        "against the previous 3-month baseline. Validate "
        "missing batches, source delays, ingestion problems, "
        "or a genuine utilization decline."
    )


# ============================================================
# INSERT INTO DAGSTER-STYLE TABLE
# ============================================================

def _sqlite_value(value):
    """
    Convert pandas/numpy/Python datetime-like values into SQLite-safe
    values. In particular, pandas.Timestamp cannot be bound directly
    by sqlite3 in Python 3.12.
    """
    if value is None:
        return None

    if pd.isna(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d %H:%M:%S")

    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")

    # Convert pandas/NumPy scalar types to native Python types.
    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        return float(value)

    if isinstance(value, np.bool_):
        return bool(value)

    return value



# ============================================================
# ROOT CAUSE + RECOMMENDATION
# ============================================================

def sla_root_cause(row):
    status = str(row["sla_status"]).upper()
    turnaround = row.get("turnaround_hours")

    if status == "BREACHED":
        if pd.notna(turnaround):
            excess = float(turnaround) - SLA_LIMIT_HOURS
            return (
                f"Authorization turnaround exceeded the "
                f"{SLA_LIMIT_HOURS:.0f}-hour SLA by "
                f"{excess:.2f} hours."
            )
        return "Authorization turnaround exceeded the configured SLA."

    if status == "MINOR_BREACH":
        if pd.notna(turnaround):
            excess = float(turnaround) - SLA_LIMIT_HOURS
            return (
                f"Authorization turnaround was slightly above the "
                f"{SLA_LIMIT_HOURS:.0f}-hour SLA by {excess:.2f} hours, "
                "indicating a minor processing delay or transient overhead."
            )
        return "Authorization turnaround was slightly above the configured SLA."

    return None


def sla_recommendation(row):
    status = str(row["sla_status"]).upper()

    if status == "BREACHED":
        return (
            "Investigate authorization processing bottlenecks, queueing "
            "delays, approval bottlenecks, manual review delays, and "
            "upstream/downstream dependencies."
        )

    if status == "MINOR_BREACH":
        return (
            "Review transient queueing, execution overhead, or minor "
            "approval delays. Monitor subsequent requests and investigate "
            "if the overrun repeats."
        )

    return None


def behavior_root_cause(row):
    if str(row["behavior_status"]).upper() != "ANOMALOUS":
        return None

    current = float(row["authorization_count"])
    baseline = float(row["behavior_baseline_volume"])
    deviation = float(row["behavior_deviation_pct"])

    direction = "increased" if current > baseline else "decreased"

    return (
        f"Authorization volume {direction} materially from the previous "
        f"{BEHAVIOR_BASELINE_PERIODS}-month baseline: current volume="
        f"{current:.0f}, baseline={baseline:.2f}, "
        f"deviation={abs(deviation):.2f}%."
    )


def behavior_recommendation(row):
    if str(row["behavior_status"]).upper() != "ANOMALOUS":
        return None

    current = float(row["authorization_count"])
    baseline = float(row["behavior_baseline_volume"])

    if current > baseline:
        return (
            "Investigate the authorization-volume increase against the "
            "previous 3-month baseline. Review provider concentration, "
            "service-code changes, urgent requests, and source or batch changes."
        )

    return (
        "Investigate the authorization-volume decrease against the "
        "previous 3-month baseline. Validate missing batches, source delays, "
        "ingestion problems, or a genuine utilization decline."
    )



# ============================================================
# PROVIDER / NPI METRICS
# ============================================================
#
# The authorization dataset has provider_id rather than a separate
# NPI column. We use provider_id as the provider/NPI identifier
# solely to populate the existing Dagster-style NPI columns.
#
# This does NOT change SLA or behavior calculations.
# ============================================================

def calculate_npi_metrics(df):
    work = df.copy()

    work["npi"] = (
        work["provider_id"]
        .astype("string")
        .str.strip()
    )

    work.loc[
        work["npi"].isin(
            ["", "nan", "None", "<NA>"]
        ),
        "npi"
    ] = pd.NA

    work["npi_affected_flag"] = (
        work["sla_status"]
        .isin(
            ["MINOR_BREACH", "BREACHED"]
        )
        .astype(int)
    )

    metrics = (
        work
        .groupby("npi", dropna=False)
        .agg(
            npi_total_rows=(
                "authorization_id",
                "count"
            ),
            npi_affected_rows=(
                "npi_affected_flag",
                "sum"
            ),
        )
        .reset_index()
    )

    metrics["npi_affected_pct"] = np.where(
        metrics["npi_total_rows"] > 0,
        (
            metrics["npi_affected_rows"]
            /
            metrics["npi_total_rows"]
        ) * 100.0,
        0.0,
    )

    metrics["npi_completeness_score"] = np.where(
        metrics["npi"].notna(),
        100.0,
        0.0,
    )

    metrics["npi_dimension_score"] = (
        metrics["npi_completeness_score"]
    )

    return metrics


def build_npi_lookup(metrics):
    lookup = {}

    for _, row in metrics.iterrows():

        key = (
            "__NULL_NPI__"
            if pd.isna(row["npi"])
            else str(row["npi"])
        )

        lookup[key] = {
            "npi": (
                None
                if key == "__NULL_NPI__"
                else key
            ),
            "npi_total_rows": int(
                row["npi_total_rows"]
            ),
            "npi_affected_rows": int(
                row["npi_affected_rows"]
            ),
            "npi_affected_pct": float(
                row["npi_affected_pct"]
            ),
            "npi_completeness_score": float(
                row["npi_completeness_score"]
            ),
            "npi_dimension_score": float(
                row["npi_dimension_score"]
            ),
        }

    return lookup


def batch_npi_values(
    npi_metrics
):
    values = (
        npi_metrics["npi"]
        .dropna()
        .astype(str)
        .drop_duplicates()
        .tolist()
    )

    return json.dumps(
        sorted(values)
    )


def insert_dagster_row(conn, values):
    """
    Insert one row into the Dagster-style SQLite output table.

    All values are normalized before sqlite3 binding so pandas
    Timestamp values do not produce:
        sqlite3.ProgrammingError:
        type 'Timestamp' is not supported
    """
    if len(values) != len(DAGSTER_COLUMNS):
        raise RuntimeError(
            f"Dagster output mismatch: "
            f"{len(DAGSTER_COLUMNS)} columns but "
            f"{len(values)} values."
        )

    safe_values = tuple(
        _sqlite_value(value)
        for value in values
    )

    placeholders = ", ".join(
        ["?"] * len(DAGSTER_COLUMNS)
    )

    conn.execute(
        f"""
        INSERT INTO {OUTPUT_TABLE} (
            {", ".join(DAGSTER_COLUMNS)}
        )
        VALUES (
            {placeholders}
        )
        """,
        safe_values,
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print("\n" + "=" * 80)
    print(
        "CLAIMCARE — AUTHORIZATION DAGSTER + "
        "SLA COMPLIANCE + BEHAVIOR"
    )
    print("=" * 80)

    run_id = str(uuid.uuid4())
    run_start = datetime.now()

    batch_id = (
        f"{datetime.now():%Y%m%d_%H%M%S}_"
        f"{run_id[:8]}"
    )

    # --------------------------------------------------------
    # 1. LOAD authorization_dataset FROM claim_sentinel.db
    # --------------------------------------------------------

    df = load_authorization_data()

    print(
        f"\nAuthorization rows loaded : "
        f"{len(df):,}"
    )

    # --------------------------------------------------------
    # 2. SLA
    # --------------------------------------------------------

    sla_df = calculate_sla(df)

    sla_df["root_cause"] = sla_df.apply(
        lambda row: sla_root_cause(row)
        if str(row["sla_status"]).upper()
        in {"MINOR_BREACH", "BREACHED"}
        else None,
        axis=1,
    )

    sla_df["recommendation"] = sla_df.apply(
        lambda row: sla_recommendation(row)
        if str(row["sla_status"]).upper()
        in {"MINOR_BREACH", "BREACHED"}
        else None,
        axis=1,
    )


    # --------------------------------------------------------
    # 3. BEHAVIOR
    # --------------------------------------------------------

    monthly_df = aggregate_monthly_volume(df)
    behavior_df = calculate_behavior(monthly_df)

    # --------------------------------------------------------
    # PROVIDER / NPI METRICS
    # --------------------------------------------------------

    npi_metrics = calculate_npi_metrics(
        sla_df
    )

    npi_lookup = build_npi_lookup(
        npi_metrics
    )

    batch_npi_json = batch_npi_values(
        npi_metrics
    )

    if not behavior_df.empty:
        behavior_df["root_cause"] = behavior_df.apply(
            behavior_root_cause,
            axis=1,
        )

        behavior_df["recommendation"] = behavior_df.apply(
            behavior_recommendation,
            axis=1,
        )


    run_completed = datetime.now()

    duration_seconds = (
        run_completed - run_start
    ).total_seconds()

    # --------------------------------------------------------
    # 4. SLA SUMMARY
    # --------------------------------------------------------

    evaluated = sla_df[
        sla_df["sla_status"].isin(
            ["MET", "MINOR_BREACH", "BREACHED"]
        )
    ]

    met_count = int(
        evaluated["sla_status"]
        .eq("MET")
        .sum()
    )

    minor_count = int(
        evaluated["sla_status"]
        .eq("MINOR_BREACH")
        .sum()
    )

    breached_count = int(
        evaluated["sla_status"]
        .eq("BREACHED")
        .sum()
    )

    compliance = (
        met_count / len(evaluated) * 100.0
        if len(evaluated) > 0
        else np.nan
    )

    if breached_count > 0:
        overall_status = "BREACHED"
        severity = "critical"
        breach_rows = sla_df[
            sla_df["sla_status"].eq("BREACHED")
        ]

        summary_root_cause = (
            breach_rows["root_cause"].dropna().iloc[0]
            if not breach_rows["root_cause"].dropna().empty
            else (
                f"{breached_count} authorization request(s) "
                f"exceeded the configured SLA of "
                f"{SLA_LIMIT_HOURS:.0f} hours."
            )
        )
        summary_recommendation = (
            breach_rows["recommendation"].dropna().iloc[0]
            if not breach_rows["recommendation"].dropna().empty
            else (
                "Investigate authorization processing bottlenecks, "
                "queueing, approval delays, and upstream/downstream "
                "dependencies."
            )
        )
    elif minor_count > 0:
        overall_status = "MINOR_BREACH"
        severity = "warning"
        minor_rows = sla_df[
            sla_df["sla_status"].eq("MINOR_BREACH")
        ]

        summary_root_cause = (
            minor_rows["root_cause"].dropna().iloc[0]
            if not minor_rows["root_cause"].dropna().empty
            else (
                f"{minor_count} authorization request(s) were "
                f"slightly above the configured SLA of "
                f"{SLA_LIMIT_HOURS:.0f} hours."
            )
        )
        summary_recommendation = (
            minor_rows["recommendation"].dropna().iloc[0]
            if not minor_rows["recommendation"].dropna().empty
            else (
                "Review transient queueing and minor approval delays "
                "and monitor subsequent requests."
            )
        )
    else:
        overall_status = "MET"
        severity = "info"
        summary_root_cause = None
        summary_recommendation = None

    # --------------------------------------------------------
    # 5. CREATE NEW DAGSTER-STYLE SQLITE OUTPUT DATABASE
    # --------------------------------------------------------

    conn = create_output_database()

    try:
        # ----------------------------------------------------
        # A. SLA SUMMARY
        # ----------------------------------------------------

        insert_dagster_row(
            conn,
            (
                run_id,
                "authorization_sla_behavior",
                "SUCCESS",
                run_start,
                run_completed,
                duration_seconds,
                len(df),
                INPUT_TABLE,
                batch_id,
                None,
                "sla_compliance",
                None,
                "authorization_turnaround_sla",
                minor_count + breached_count,
                None,
                severity,
                (
                    f"Authorization SLA compliance: "
                    f"{compliance:.2f}%"
                    if not np.isnan(compliance)
                    else "Authorization SLA compliance: N/A"
                ),
                len(df),
                met_count,
                minor_count + breached_count,
                1,
                minor_count + breached_count,
                breached_count,
                0,
                minor_count,
                0,
                None,
                overall_status,
                summary_root_cause,
                summary_recommendation,
                batch_npi_json,
                int(len(sla_df)),
                int(
                    sla_df["sla_status"]
                    .isin(
                        ["MINOR_BREACH", "BREACHED"]
                    )
                    .sum()
                ),
                (
                    float(
                        sla_df["sla_status"]
                        .isin(
                            ["MINOR_BREACH", "BREACHED"]
                        )
                        .mean()
                        * 100.0
                    )
                    if len(sla_df) > 0
                    else 0.0
                ),
                (
                    float(
                        sla_df["provider_id"]
                        .notna()
                        .mean()
                        * 100.0
                    )
                    if len(sla_df) > 0
                    else 0.0
                ),
                run_completed,
                (
                    float(
                        sla_df["provider_id"]
                        .notna()
                        .mean()
                        * 100.0
                    )
                    if len(sla_df) > 0
                    else 0.0
                ),
            )
        )

        # ----------------------------------------------------
        # B. SLA DETAIL — ONE ROW PER AUTHORIZATION
        # ----------------------------------------------------

        for _, row in sla_df.iterrows():
            status = str(
                row["sla_status"]
            ).upper()

            insert_dagster_row(
                conn,
                (
                    run_id,
                    "authorization_sla",
                    "SUCCESS",
                    (
                        row["request_date"]
                        if pd.notna(row["request_date"])
                        else run_start
                    ),
                    (
                        row["approval_date"]
                        if pd.notna(row["approval_date"])
                        else run_completed
                    ),
                    (
                        float(row["turnaround_hours"])
                        if pd.notna(row["turnaround_hours"])
                        else None
                    ),
                    1,
                    INPUT_TABLE,
                    row["batch_id"],
                    None,
                    "sla_compliance",
                    row["authorization_id"],
                    "authorization_turnaround",
                    (
                        1
                        if status in {
                            "MINOR_BREACH",
                            "BREACHED",
                        }
                        else 0
                    ),
                    (
                        (
                            float(row["turnaround_hours"])
                            - SLA_LIMIT_HOURS
                        )
                        if pd.notna(
                            row["turnaround_hours"]
                        )
                        and status in {
                            "MINOR_BREACH",
                            "BREACHED",
                        }
                        else 0.0
                    ),
                    (
                        "critical"
                        if status == "BREACHED"
                        else (
                            "warning"
                            if status == "MINOR_BREACH"
                            else "info"
                        )
                    ),
                    f"SLA status: {status}",
                    1,
                    1 if status == "MET" else 0,
                    (
                        1
                        if status in {
                            "MINOR_BREACH",
                            "BREACHED",
                        }
                        else 0
                    ),
                    1,
                    (
                        1
                        if status in {
                            "MINOR_BREACH",
                            "BREACHED",
                        }
                        else 0
                    ),
                    1 if status == "BREACHED" else 0,
                    0,
                    1 if status == "MINOR_BREACH" else 0,
                    0,
                    None,
                    status,
                    row["root_cause"],
                    row["recommendation"],
                    npi_lookup[
                        (
                            str(row["provider_id"]).strip()
                            if pd.notna(row["provider_id"])
                            else "__NULL_NPI__"
                        )
                    ]["npi"],
                    npi_lookup[
                        (
                            str(row["provider_id"]).strip()
                            if pd.notna(row["provider_id"])
                            else "__NULL_NPI__"
                        )
                    ]["npi_total_rows"],
                    npi_lookup[
                        (
                            str(row["provider_id"]).strip()
                            if pd.notna(row["provider_id"])
                            else "__NULL_NPI__"
                        )
                    ]["npi_affected_rows"],
                    npi_lookup[
                        (
                            str(row["provider_id"]).strip()
                            if pd.notna(row["provider_id"])
                            else "__NULL_NPI__"
                        )
                    ]["npi_affected_pct"],
                    npi_lookup[
                        (
                            str(row["provider_id"]).strip()
                            if pd.notna(row["provider_id"])
                            else "__NULL_NPI__"
                        )
                    ]["npi_completeness_score"],
                    run_completed,
                    npi_lookup[
                        (
                            str(row["provider_id"]).strip()
                            if pd.notna(row["provider_id"])
                            else "__NULL_NPI__"
                        )
                    ]["npi_dimension_score"],
                )
            )

        # ----------------------------------------------------
        # C. BEHAVIOR DETAIL
        # ----------------------------------------------------

        for _, row in behavior_df.iterrows():
            anomaly = str(
                row["behavior_status"]
            ).upper()

            insert_dagster_row(
                conn,
                (
                    run_id,
                    "authorization_behavior",
                    "SUCCESS",
                    run_start,
                    run_completed,
                    duration_seconds,
                    int(row["authorization_count"]),
                    INPUT_TABLE,
                    batch_id,
                    None,
                    "behavior",
                    row["request_month"],
                    "monthly_authorization_volume",
                    (
                        1
                        if anomaly == "ANOMALOUS"
                        else 0
                    ),
                    (
                        float(
                            row["behavior_deviation_pct"]
                        )
                        if pd.notna(
                            row["behavior_deviation_pct"]
                        )
                        and np.isfinite(
                            row["behavior_deviation_pct"]
                        )
                        else None
                    ),
                    (
                        "warning"
                        if anomaly == "ANOMALOUS"
                        else "info"
                    ),
                    row["behavior_reason"],
                    int(row["authorization_count"]),
                    None,
                    None,
                    BEHAVIOR_BASELINE_PERIODS,
                    1 if anomaly == "ANOMALOUS" else 0,
                    0,
                    0,
                    1 if anomaly == "ANOMALOUS" else 0,
                    0,
                    None,
                    anomaly,
                    row["root_cause"],
                    row["recommendation"],
                    batch_npi_json,
                    int(len(sla_df)),
                    int(
                        sla_df["sla_status"]
                        .isin(
                            ["MINOR_BREACH", "BREACHED"]
                        )
                        .sum()
                    ),
                    (
                        float(
                            sla_df["sla_status"]
                            .isin(
                                ["MINOR_BREACH", "BREACHED"]
                            )
                            .mean()
                            * 100.0
                        )
                        if len(sla_df) > 0
                        else 0.0
                    ),
                    (
                        float(
                            sla_df["provider_id"]
                            .notna()
                            .mean()
                            * 100.0
                        )
                        if len(sla_df) > 0
                        else 0.0
                    ),
                    run_completed,
                    (
                        float(
                            sla_df["provider_id"]
                            .notna()
                            .mean()
                            * 100.0
                        )
                        if len(sla_df) > 0
                        else 0.0
                    ),
                )
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    # --------------------------------------------------------
    # 6. TERMINAL SUMMARY
    # --------------------------------------------------------

    anomaly_count = int(
        behavior_df["behavior_status"]
        .eq("ANOMALOUS")
        .sum()
    )

    normal_count = int(
        behavior_df["behavior_status"]
        .eq("NORMAL")
        .sum()
    )

    print("\n" + "=" * 80)
    print("AUTHORIZATION SLA COMPLIANCE")
    print("=" * 80)
    print(
        f"SLA limit            : "
        f"{SLA_LIMIT_HOURS:.0f} hours"
    )
    print(
        f"Requests evaluated   : "
        f"{len(evaluated)}"
    )
    print(
        f"SLA MET              : "
        f"{met_count}"
    )
    print(
        f"MINOR_BREACH         : "
        f"{minor_count}"
    )
    print(
        f"BREACHED             : "
        f"{breached_count}"
    )
    print(
        "SLA Compliance       : "
        + (
            f"{compliance:.2f}%"
            if not np.isnan(compliance)
            else "N/A"
        )
    )

    print("\n" + "=" * 80)
    print("AUTHORIZATION BEHAVIOR")
    print("=" * 80)
    print(
        f"Periods analyzed     : "
        f"{len(behavior_df)}"
    )
    print(
        f"Normal periods       : "
        f"{normal_count}"
    )
    print(
        f"Anomalous periods    : "
        f"{anomaly_count}"
    )

    print("\n" + "=" * 80)
    print("COMPLETED")
    print("=" * 80)
    print(
        f"Input database       : "
        f"{INPUT_DB}"
    )
    print(
        f"Input table          : "
        f"{INPUT_TABLE}"
    )
    print(
        f"Output database      : "
        f"{OUTPUT_DB}"
    )
    print(
        f"Output table         : "
        f"{OUTPUT_TABLE}"
    )
    print(
        "\nProvider/NPI grouping is NOT used "
        "for SLA or behavior analysis."
    )


if __name__ == "__main__":
    main()