# ============================================================
# CLAIMCARE — FINAL PROVIDER SLA RISK ENGINE
# ============================================================
#
# PURPOSE
# -------
# Creates ONE FINAL SLA RISK SCORE per PROVIDER / NPI.
#
# IMPORTANT:
# ----------
# SLA COMPLIANCE and BEHAVIOR ANALYSIS are NOT included
# because the current outputs are not provider/NPI-level.
#
# FINAL FORMULA:
#
#   25% DQ Risk
#   20% Volume Risk
#   20% Robust Z Risk
#   15% PSI Risk
#   20% Arrival Delay Risk
#
# TOTAL = 100%
#
# SCORE RANGE:
#   0.00 = Lowest risk
#   1.00 = Highest risk
#
# RISK LEVEL:
#   0.00 - 0.24 = LOW
#   0.25 - 0.49 = MEDIUM
#   0.50 - 0.74 = HIGH
#   0.75 - 1.00 = CRITICAL
#
# ARRIVAL DELAY:
# ----------------
# Currently a DEFAULT PLACEHOLDER = 0.20
#
# Later replace only this value/calculation with the
# actual provider-level arrival-delay risk.
#
# EXISTING ENGINES ARE NOT MODIFIED.
# This script only reads their outputs.
#
# ============================================================


import sqlite3
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd


# ============================================================
# 1. PROJECT PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent


# Existing provider volume database
VOLUME_DB = BASE_DIR / "voulme.db"


# Existing Data Quality database
DQ_DB = BASE_DIR / "claim_dagster.db"


# Existing Robust-Z + PSI database
ANOMALY_DB = BASE_DIR / "anomalies.db"


# New output database
OUTPUT_DB = BASE_DIR / "final_sla_risk.db"


# Final output table
OUTPUT_TABLE = "provider_sla_risk"


# ============================================================
# 2. FINAL RISK WEIGHTS
# ============================================================

WEIGHT_DQ = 0.25

WEIGHT_VOLUME = 0.20

WEIGHT_ROBUST_Z = 0.20

WEIGHT_PSI = 0.15

WEIGHT_ARRIVAL_DELAY = 0.20


TOTAL_WEIGHT = (
    WEIGHT_DQ
    + WEIGHT_VOLUME
    + WEIGHT_ROBUST_Z
    + WEIGHT_PSI
    + WEIGHT_ARRIVAL_DELAY
)


# ============================================================
# 3. ARRIVAL-DELAY DEFAULT
# ============================================================
#
# TEMPORARY VALUE
#
# This MUST be replaced later when the actual
# provider-level arrival-delay risk is available.
#
# Range:
#   0 = no arrival-delay risk
#   1 = maximum arrival-delay risk
#
# ============================================================

ARRIVAL_DELAY_DEFAULT = 0.20


# ============================================================
# 4. RISK LEVEL THRESHOLDS
# ============================================================

LOW_MAX = 0.24

MEDIUM_MAX = 0.49

HIGH_MAX = 0.74


# ============================================================
# 5. VALIDATE CONFIGURATION
# ============================================================

def validate_configuration():

    if not np.isclose(
        TOTAL_WEIGHT,
        1.0
    ):

        raise ValueError(
            "Risk weights must sum to 1.0. "
            f"Current total = {TOTAL_WEIGHT}"
        )


    if not (
        0.0
        <= ARRIVAL_DELAY_DEFAULT
        <= 1.0
    ):

        raise ValueError(
            "ARRIVAL_DELAY_DEFAULT must "
            "be between 0 and 1."
        )


# ============================================================
# 6. CHECK TABLE EXISTS
# ============================================================

def table_exists(
    conn,
    table_name
):

    result = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,)
    ).fetchone()


    return result is not None


# ============================================================
# 7. NORMALIZE NPI
# ============================================================

def normalize_npi(series):

    return (
        series
        .astype("string")
        .str.strip()
        .str.replace(
            r"\.0$",
            "",
            regex=True
        )
    )


# ============================================================
# 8. FORCE VALUE TO 0–1
# ============================================================

def clip_risk(series):

    return (
        pd.to_numeric(
            series,
            errors="coerce"
        )
        .clip(
            lower=0.0,
            upper=1.0
        )
    )


# ============================================================
# 9. LOAD PROVIDER VOLUME RISK
# ============================================================

def load_provider_volume():

    print(
        "\nLoading provider volume risk..."
    )


    if not VOLUME_DB.exists():

        raise FileNotFoundError(
            f"\nVolume DB not found:\n"
            f"{VOLUME_DB}"
        )


    conn = sqlite3.connect(
        VOLUME_DB
    )


    try:

        if not table_exists(
            conn,
            "provider_volume_risk"
        ):

            raise ValueError(
                "Table "
                "'provider_volume_risk' "
                "was not found."
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
                months_available,
                root_cause,
                recommendation
            FROM provider_volume_risk
            """,
            conn
        )


    finally:

        conn.close()


    if df.empty:

        raise ValueError(
            "provider_volume_risk "
            "contains no records."
        )


    df["NPI"] = normalize_npi(
        df["NPI"]
    )


    # --------------------------------------------------------
    # Convert volume risk
    # --------------------------------------------------------

    df["volume_risk"] = clip_risk(
        df["volume_risk"]
    )


    # --------------------------------------------------------
    # Convert period to date for sorting
    # --------------------------------------------------------

    df["_period_sort"] = pd.to_datetime(
        df["current_period"]
        .astype(str)
        + "-01",
        errors="coerce"
    )


    # --------------------------------------------------------
    # Keep latest period per provider
    # --------------------------------------------------------

    df = (
        df
        .sort_values(
            [
                "NPI",
                "_period_sort"
            ]
        )
        .drop_duplicates(
            subset=["NPI"],
            keep="last"
        )
        .drop(
            columns=[
                "_period_sort"
            ]
        )
        .reset_index(
            drop=True
        )
    )


    print(
        f"Provider volume rows: "
        f"{len(df):,}"
    )


    return df


# ============================================================
# 10. LOAD DATA QUALITY
# ============================================================

def load_data_quality():

    print(
        "\nLoading Data Quality results..."
    )


    if not DQ_DB.exists():

        raise FileNotFoundError(
            f"\nDQ DB not found:\n"
            f"{DQ_DB}"
        )


    conn = sqlite3.connect(
        DQ_DB
    )


    try:

        if not table_exists(
            conn,
            "dq_run_output"
        ):

            raise ValueError(
                "Table "
                "'dq_run_output' "
                "was not found."
            )


        df = pd.read_sql_query(
            """
            SELECT
                npi,
                npi_completeness_score,
                npi_dimension_score,
                created_at,
                run_id
            FROM dq_run_output
            WHERE npi IS NOT NULL
            """,
            conn
        )


    finally:

        conn.close()


    if df.empty:

        print(
            "WARNING: No DQ records found."
        )

        return pd.DataFrame(
            columns=[
                "NPI",
                "npi_completeness_score",
                "npi_dimension_score",
                "dq_quality_score",
                "dq_risk"
            ]
        )


    df["NPI"] = normalize_npi(
        df["npi"]
    )


    # --------------------------------------------------------
    # Numeric conversion
    # --------------------------------------------------------

    df[
        "npi_completeness_score"
    ] = pd.to_numeric(
        df[
            "npi_completeness_score"
        ],
        errors="coerce"
    )


    df[
        "npi_dimension_score"
    ] = pd.to_numeric(
        df[
            "npi_dimension_score"
        ],
        errors="coerce"
    )


    # --------------------------------------------------------
    # Provider-level aggregation
    #
    # If multiple DQ rows exist for the same provider,
    # calculate the mean score.
    # --------------------------------------------------------

    provider_dq = (
        df
        .groupby(
            "NPI",
            dropna=True
        )
        .agg(
            npi_completeness_score=(
                "npi_completeness_score",
                "mean"
            ),

            npi_dimension_score=(
                "npi_dimension_score",
                "mean"
            )
        )
        .reset_index()
    )


    # --------------------------------------------------------
    # Overall DQ Quality Score
    #
    # Average of:
    #   NPI completeness
    #   NPI dimension
    # --------------------------------------------------------

    provider_dq[
        "dq_quality_score"
    ] = (
        provider_dq[
            [
                "npi_completeness_score",
                "npi_dimension_score"
            ]
        ]
        .mean(
            axis=1
        )
    )


    # --------------------------------------------------------
    # Quality -> Risk
    #
    # 100 quality = 0 risk
    # 0 quality   = 1 risk
    # --------------------------------------------------------

    provider_dq[
        "dq_risk"
    ] = (
        1.0
        - (
            provider_dq[
                "dq_quality_score"
            ]
            / 100.0
        )
    )


    provider_dq[
        "dq_risk"
    ] = clip_risk(
        provider_dq[
            "dq_risk"
        ]
    )


    print(
        f"DQ providers: "
        f"{len(provider_dq):,}"
    )


    return provider_dq[
        [
            "NPI",
            "npi_completeness_score",
            "npi_dimension_score",
            "dq_quality_score",
            "dq_risk"
        ]
    ]


# ============================================================
# 11. LOAD ROBUST Z + PSI
# ============================================================

def load_robust_z_and_psi(
    provider_df
):

    print(
        "\nLoading Robust-Z and PSI results..."
    )


    result = provider_df[
        [
            "NPI",
            "current_period"
        ]
    ].copy()


    # --------------------------------------------------------
    # Default values
    # --------------------------------------------------------

    result[
        "robust_z_max"
    ] = np.nan


    result[
        "robust_z_risk"
    ] = 0.0


    result[
        "robust_z_status"
    ] = "NO_DATA"


    result[
        "psi_score"
    ] = np.nan


    result[
        "psi_risk"
    ] = 0.0


    result[
        "psi_status"
    ] = "NO_DATA"


    # --------------------------------------------------------
    # Check database
    # --------------------------------------------------------

    if not ANOMALY_DB.exists():

        print(
            "WARNING: anomalies.db not found."
        )

        print(
            "Robust-Z risk = 0"
        )

        print(
            "PSI risk = 0"
        )

        return result


    conn = sqlite3.connect(
        ANOMALY_DB
    )


    try:

        if not table_exists(
            conn,
            "claims_anomalies"
        ):

            print(
                "WARNING: claims_anomalies "
                "table not found."
            )

            return result


        anomaly_df = pd.read_sql_query(
            """
            SELECT
                claim_type,
                provider_id,
                batch_month,
                robust_z_score,
                psi_score,
                anomaly_count,
                severity,
                anomaly_reason
            FROM claims_anomalies
            """,
            conn
        )


    finally:

        conn.close()


    if anomaly_df.empty:

        print(
            "No anomaly records found."
        )

        return result


    # ========================================================
    # NORMALIZE
    # ========================================================

    anomaly_df[
        "NPI"
    ] = normalize_npi(
        anomaly_df[
            "provider_id"
        ]
    )


    anomaly_df[
        "batch_month"
    ] = (
        anomaly_df[
            "batch_month"
        ]
        .astype("string")
        .str.strip()
    )


    anomaly_df[
        "robust_z_score"
    ] = pd.to_numeric(
        anomaly_df[
            "robust_z_score"
        ],
        errors="coerce"
    )


    anomaly_df[
        "psi_score"
    ] = pd.to_numeric(
        anomaly_df[
            "psi_score"
        ],
        errors="coerce"
    )


    # ========================================================
    # ROBUST Z
    # ========================================================
    #
    # Existing Robust-Z threshold = 3.5
    #
    # Risk normalization:
    #
    #   0     -> 0
    #   3.5   -> 0.50
    #   7.0+  -> 1.00
    #
    # ========================================================

    valid_z = anomaly_df[
        anomaly_df["NPI"].notna()
        & anomaly_df["robust_z_score"].notna()
    ].copy()


    if not valid_z.empty:

        valid_z[
            "abs_z"
        ] = valid_z[
            "robust_z_score"
        ].abs()


        provider_robust = (
            valid_z
            .groupby(
                [
                    "NPI",
                    "batch_month"
                ]
            )
            .agg(
                robust_z_max=(
                    "abs_z",
                    "max"
                )
            )
            .reset_index()
        )


        provider_robust[
            "robust_z_risk"
        ] = (
            provider_robust[
                "robust_z_max"
            ]
            / 7.0
        ).clip(
            0.0,
            1.0
        )


        provider_robust[
            "robust_z_status"
        ] = np.where(
            provider_robust[
                "robust_z_max"
            ] >= 3.5,
            "ANOMALOUS",
            "NORMAL"
        )


    else:

        provider_robust = pd.DataFrame(
            columns=[
                "NPI",
                "batch_month",
                "robust_z_max",
                "robust_z_risk",
                "robust_z_status"
            ]
        )


    # ========================================================
    # PSI
    # ========================================================
    #
    # Your current PSI is population-level.
    #
    # Therefore PSI is associated with the provider's
    # current month/claim population, NOT falsely calculated
    # as an independent provider PSI.
    #
    # ========================================================

    valid_psi = anomaly_df[
        anomaly_df[
            "psi_score"
        ].notna()
    ].copy()


    if not valid_psi.empty:

        psi_monthly = (
            valid_psi
            .groupby(
                "batch_month"
            )
            .agg(
                psi_score=(
                    "psi_score",
                    "max"
                )
            )
            .reset_index()
        )


        # ----------------------------------------------------
        # PSI normalization
        #
        # 0.00 -> 0
        # 0.25 -> 0.50
        # 0.50+ -> 1
        # ----------------------------------------------------

        psi_monthly[
            "psi_risk"
        ] = (
            psi_monthly[
                "psi_score"
            ]
            / 0.50
        ).clip(
            0.0,
            1.0
        )


        psi_monthly[
            "psi_status"
        ] = np.select(
            [
                psi_monthly[
                    "psi_score"
                ] < 0.10,

                psi_monthly[
                    "psi_score"
                ] < 0.25
            ],
            [
                "NORMAL",

                "MODERATE_DRIFT"
            ],
            default="SIGNIFICANT_DRIFT"
        )


    else:

        psi_monthly = pd.DataFrame(
            columns=[
                "batch_month",
                "psi_score",
                "psi_risk",
                "psi_status"
            ]
        )


    # ========================================================
    # MERGE ROBUST Z
    # ========================================================

    result = result.merge(
        provider_robust[
            [
                "NPI",
                "batch_month",
                "robust_z_max",
                "robust_z_risk",
                "robust_z_status"
            ]
        ],
        left_on=[
            "NPI",
            "current_period"
        ],
        right_on=[
            "NPI",
            "batch_month"
        ],
        how="left",
        suffixes=(
            "",
            "_new"
        )
    )


    result = result.drop(
        columns=[
            "batch_month"
        ],
        errors="ignore"
    )


    # ========================================================
    # MERGE PSI
    # ========================================================

    result = result.merge(
        psi_monthly,
        left_on="current_period",
        right_on="batch_month",
        how="left",
        suffixes=(
            "",
            "_new"
        )
    )


    result = result.drop(
        columns=[
            "batch_month"
        ],
        errors="ignore"
    )


    # ========================================================
    # CLEAN
    # ========================================================

    result[
        "robust_z_risk"
    ] = (
        pd.to_numeric(
            result[
                "robust_z_risk"
            ],
            errors="coerce"
        )
        .fillna(0.0)
        .clip(
            0.0,
            1.0
        )
    )


    result[
        "psi_risk"
    ] = (
        pd.to_numeric(
            result[
                "psi_risk"
            ],
            errors="coerce"
        )
        .fillna(0.0)
        .clip(
            0.0,
            1.0
        )
    )


    print(
        f"Provider Robust-Z matches: "
        f"{(
            result['robust_z_status']
            != 'NO_DATA'
        ).sum():,}"
    )


    print(
        f"Provider PSI matches: "
        f"{(
            result['psi_status']
            != 'NO_DATA'
        ).sum():,}"
    )


    return result


# ============================================================
# 12. ASSIGN FINAL RISK LEVEL
# ============================================================

def assign_risk_level(
    score
):

    if pd.isna(score):

        return "UNKNOWN"


    if score <= LOW_MAX:

        return "LOW"


    if score <= MEDIUM_MAX:

        return "MEDIUM"


    if score <= HIGH_MAX:

        return "HIGH"


    return "CRITICAL"


# ============================================================
# 13. GENERATE ROOT CAUSE
# ============================================================

def generate_root_cause(
    row
):

    components = {

        "Data Quality":
            row[
                "weighted_dq_risk"
            ],

        "Volume":
            row[
                "weighted_volume_risk"
            ],

        "Robust Z":
            row[
                "weighted_robust_z_risk"
            ],

        "PSI":
            row[
                "weighted_psi_risk"
            ],

        "Arrival Delay":
            row[
                "weighted_arrival_delay_risk"
            ]
    }


    components = {
        key: value
        for key, value in components.items()
        if pd.notna(value)
    }


    if not components:

        return (
            "No valid risk components available."
        )


    ranked = sorted(
        components.items(),
        key=lambda x: x[1],
        reverse=True
    )


    if len(ranked) == 1:

        return (
            f"Primary risk driver: "
            f"{ranked[0][0]}."
        )


    return (
        f"Primary risk driver: "
        f"{ranked[0][0]}; "
        f"secondary risk driver: "
        f"{ranked[1][0]}."
    )


# ============================================================
# 14. GENERATE RECOMMENDATION
# ============================================================

def generate_recommendation(
    row
):

    score = row[
        "final_sla_risk_score"
    ]


    if pd.isna(score):

        return (
            "Insufficient data for a reliable "
            "SLA risk recommendation."
        )


    drivers = []


    if row[
        "dq_risk"
    ] >= 0.50:

        drivers.append(
            "data quality"
        )


    if row[
        "volume_risk"
    ] >= 0.50:

        drivers.append(
            "claim volume"
        )


    if row[
        "robust_z_risk"
    ] >= 0.50:

        drivers.append(
            "provider anomalies"
        )


    if row[
        "psi_risk"
    ] >= 0.50:

        drivers.append(
            "population drift"
        )


    if row[
        "arrival_delay_risk"
    ] >= 0.50:

        drivers.append(
            "arrival delay"
        )


    # --------------------------------------------------------
    # No major driver
    # --------------------------------------------------------

    if not drivers:

        return (
            "No major risk driver detected. "
            "Continue routine monitoring."
        )


    driver_text = ", ".join(
        drivers
    )


    # --------------------------------------------------------
    # Critical
    # --------------------------------------------------------

    if score >= 0.75:

        return (
            "Immediate investigation required for "
            f"{driver_text}. "
            "Prioritize corrective action."
        )


    # --------------------------------------------------------
    # High
    # --------------------------------------------------------

    if score >= 0.50:

        return (
            f"Investigate {driver_text} "
            "and closely monitor the provider."
        )


    # --------------------------------------------------------
    # Medium
    # --------------------------------------------------------

    if score >= 0.25:

        return (
            f"Monitor {driver_text} "
            "during the next processing cycle."
        )


    return (
        "Continue routine monitoring."
    )


# ============================================================
# 15. BUILD FINAL PROVIDER SLA RISK
# ============================================================

def build_final_sla_risk():

    print(
        "\n"
        + "=" * 80
    )

    print(
        "CLAIMCARE — FINAL PROVIDER SLA RISK"
    )

    print(
        "=" * 80
    )


    # ========================================================
    # LOAD PROVIDER BASE
    # ========================================================

    provider_df = load_provider_volume()


    # ========================================================
    # LOAD DQ
    # ========================================================

    dq_df = load_data_quality()


    # ========================================================
    # LOAD ROBUST Z + PSI
    # ========================================================

    anomaly_df = load_robust_z_and_psi(
        provider_df
    )


    # ========================================================
    # MERGE DQ
    # ========================================================

    final_df = provider_df.merge(
        dq_df,
        on="NPI",
        how="left"
    )


    # ========================================================
    # MERGE ROBUST Z + PSI
    # ========================================================

    final_df = final_df.merge(
        anomaly_df,
        on=[
            "NPI",
            "current_period"
        ],
        how="left",
        suffixes=(
            "",
            "_anomaly"
        )
    )


    # ========================================================
    # 16. CLEAN RISK COMPONENTS
    # ========================================================

    # --------------------------------------------------------
    # DQ
    # --------------------------------------------------------

    final_df[
        "dq_risk"
    ] = clip_risk(
        final_df[
            "dq_risk"
        ]
    )


    final_df[
        "dq_risk"
    ] = (
        final_df[
            "dq_risk"
        ]
        .fillna(0.0)
    )


    # --------------------------------------------------------
    # Volume
    # --------------------------------------------------------

    final_df[
        "volume_risk"
    ] = clip_risk(
        final_df[
            "volume_risk"
        ]
    )


    final_df[
        "volume_risk"
    ] = (
        final_df[
            "volume_risk"
        ]
        .fillna(0.0)
    )


    # --------------------------------------------------------
    # Robust Z
    # --------------------------------------------------------

    final_df[
        "robust_z_risk"
    ] = clip_risk(
        final_df[
            "robust_z_risk"
        ]
    )


    final_df[
        "robust_z_risk"
    ] = (
        final_df[
            "robust_z_risk"
        ]
        .fillna(0.0)
    )


    # --------------------------------------------------------
    # PSI
    # --------------------------------------------------------

    final_df[
        "psi_risk"
    ] = clip_risk(
        final_df[
            "psi_risk"
        ]
    )


    final_df[
        "psi_risk"
    ] = (
        final_df[
            "psi_risk"
        ]
        .fillna(0.0)
    )


    # ========================================================
    # 17. ARRIVAL DELAY RISK
    # ========================================================
    #
    # TEMPORARY DEFAULT
    #
    # This is the ONLY component that should be replaced
    # when your actual arrival-delay calculation is ready.
    #
    # ========================================================

    final_df[
        "arrival_delay_risk"
    ] = ARRIVAL_DELAY_DEFAULT


    # ========================================================
    # 18. CALCULATE WEIGHTED COMPONENTS
    # ========================================================

    final_df[
        "weighted_dq_risk"
    ] = (
        final_df[
            "dq_risk"
        ]
        * WEIGHT_DQ
    )


    final_df[
        "weighted_volume_risk"
    ] = (
        final_df[
            "volume_risk"
        ]
        * WEIGHT_VOLUME
    )


    final_df[
        "weighted_robust_z_risk"
    ] = (
        final_df[
            "robust_z_risk"
        ]
        * WEIGHT_ROBUST_Z
    )


    final_df[
        "weighted_psi_risk"
    ] = (
        final_df[
            "psi_risk"
        ]
        * WEIGHT_PSI
    )


    final_df[
        "weighted_arrival_delay_risk"
    ] = (
        final_df[
            "arrival_delay_risk"
        ]
        * WEIGHT_ARRIVAL_DELAY
    )


    # ========================================================
    # 19. FINAL SLA RISK SCORE
    # ========================================================

    final_df[
        "final_sla_risk_score"
    ] = (

        final_df[
            "weighted_dq_risk"
        ]

        +

        final_df[
            "weighted_volume_risk"
        ]

        +

        final_df[
            "weighted_robust_z_risk"
        ]

        +

        final_df[
            "weighted_psi_risk"
        ]

        +

        final_df[
            "weighted_arrival_delay_risk"
        ]

    )


    # --------------------------------------------------------
    # Guarantee 0–1
    # --------------------------------------------------------

    final_df[
        "final_sla_risk_score"
    ] = (
        final_df[
            "final_sla_risk_score"
        ]
        .clip(
            0.0,
            1.0
        )
        .round(6)
    )


    # ========================================================
    # 20. FINAL RISK LEVEL
    # ========================================================

    final_df[
        "final_risk_level"
    ] = final_df[
        "final_sla_risk_score"
    ].apply(
        assign_risk_level
    )


    # ========================================================
    # 21. ROOT CAUSE
    # ========================================================

    final_df[
        "root_cause"
    ] = final_df.apply(
        generate_root_cause,
        axis=1
    )


    # ========================================================
    # 22. RECOMMENDATION
    # ========================================================

    final_df[
        "recommendation"
    ] = final_df.apply(
        generate_recommendation,
        axis=1
    )


    # ========================================================
    # 23. ADD RUN INFORMATION
    # ========================================================

    final_df[
        "run_timestamp"
    ] = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


    # ========================================================
    # 24. SELECT FINAL OUTPUT COLUMNS
    # ========================================================

    output_columns = [

        # ----------------------------------------------------
        # Provider
        # ----------------------------------------------------

        "NPI",

        "current_period",


        # ----------------------------------------------------
        # Volume
        # ----------------------------------------------------

        "current_month_volume",

        "baseline_volume",

        "deviation_pct",

        "volume_risk",


        # ----------------------------------------------------
        # Data Quality
        # ----------------------------------------------------

        "npi_completeness_score",

        "npi_dimension_score",

        "dq_quality_score",

        "dq_risk",


        # ----------------------------------------------------
        # Robust Z
        # ----------------------------------------------------

        "robust_z_max",

        "robust_z_risk",

        "robust_z_status",


        # ----------------------------------------------------
        # PSI
        # ----------------------------------------------------

        "psi_score",

        "psi_risk",

        "psi_status",


        # ----------------------------------------------------
        # Arrival Delay
        # ----------------------------------------------------

        "arrival_delay_risk",


        # ----------------------------------------------------
        # Weighted Components
        # ----------------------------------------------------

        "weighted_dq_risk",

        "weighted_volume_risk",

        "weighted_robust_z_risk",

        "weighted_psi_risk",

        "weighted_arrival_delay_risk",


        # ----------------------------------------------------
        # FINAL
        # ----------------------------------------------------

        "final_sla_risk_score",

        "final_risk_level",


        # ----------------------------------------------------
        # Explanation
        # ----------------------------------------------------

        "root_cause",

        "recommendation",

        "run_timestamp"
    ]


    # Keep only existing columns
    output_columns = [
        column
        for column in output_columns
        if column in final_df.columns
    ]


    final_df = final_df[
        output_columns
    ].copy()


    # ========================================================
    # 25. SAVE DATABASE
    # ========================================================

    print(
        "\nSaving final provider SLA risk..."
    )


    conn = sqlite3.connect(
        OUTPUT_DB
    )


    try:

        final_df.to_sql(
            OUTPUT_TABLE,
            conn,
            if_exists="replace",
            index=False
        )

    finally:

        conn.close()


    # ========================================================
    # 26. SUMMARY
    # ========================================================

    print(
        "\n"
        + "=" * 80
    )

    print(
        "FINAL SLA RISK SUMMARY"
    )

    print(
        "=" * 80
    )


    print(
        f"\nProviders processed : "
        f"{len(final_df):,}"
    )


    print(
        f"Average risk       : "
        f"{final_df['final_sla_risk_score'].mean():.4f}"
    )


    print(
        f"Minimum risk       : "
        f"{final_df['final_sla_risk_score'].min():.4f}"
    )


    print(
        f"Maximum risk       : "
        f"{final_df['final_sla_risk_score'].max():.4f}"
    )


    # ========================================================
    # 27. RISK DISTRIBUTION
    # ========================================================

    print(
        "\nRisk distribution:"
    )


    risk_distribution = (
        final_df[
            "final_risk_level"
        ]
        .value_counts()
    )


    for level in [
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL"
    ]:

        print(
            f"  {level:<10} : "
            f"{risk_distribution.get(level, 0):,}"
        )


    # ========================================================
    # 28. TOP 20 PROVIDERS
    # ========================================================

    print(
        "\n"
        + "=" * 80
    )

    print(
        "TOP 20 HIGHEST-RISK PROVIDERS"
    )

    print(
        "=" * 80
    )


    top_columns = [

        "NPI",

        "final_sla_risk_score",

        "final_risk_level",

        "dq_risk",

        "volume_risk",

        "robust_z_risk",

        "psi_risk",

        "arrival_delay_risk"
    ]


    top_df = (
        final_df[
            top_columns
        ]
        .sort_values(
            "final_sla_risk_score",
            ascending=False
        )
        .head(20)
    )


    print(
        top_df.to_string(
            index=False
        )
    )


    # ========================================================
    # 29. FORMULA
    # ========================================================

    print(
        "\n"
        + "=" * 80
    )

    print(
        "FINAL FORMULA"
    )

    print(
        "=" * 80
    )


    print(
        """
FINAL_SLA_RISK =
    0.25 × DQ_Risk
  + 0.20 × Volume_Risk
  + 0.20 × RobustZ_Risk
  + 0.15 × PSI_Risk
  + 0.20 × ArrivalDelay_Risk
"""
    )


    # ========================================================
    # 30. OUTPUT
    # ========================================================

    print(
        f"Output DB    : "
        f"{OUTPUT_DB}"
    )

    print(
        f"Output table : "
        f"{OUTPUT_TABLE}"
    )


    print(
        "\nArrival Delay Default:"
    )

    print(
        f"  {ARRIVAL_DELAY_DEFAULT}"
    )


    print(
        "\nIMPORTANT:"
    )

    print(
        "Replace ARRIVAL_DELAY_DEFAULT with the "
        "actual provider-level arrival-delay risk "
        "when it becomes available."
    )


    print(
        "\n"
        + "=" * 80
    )

    print(
        "COMPLETED"
    )

    print(
        "=" * 80
    )


    return final_df


# ============================================================
# 31. MAIN
# ============================================================

def main():

    validate_configuration()

    build_final_sla_risk()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()