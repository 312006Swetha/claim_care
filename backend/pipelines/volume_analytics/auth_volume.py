import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# CLAIMCARE — AUTHORIZATION PROVIDER VOLUME RISK
# ============================================================
#
# INPUT
#   claim_sentinel.db
#       └── authorization_dataset
#
# OUTPUT
#   auth_volume.db
#       ├── authorization_provider_monthly_volume
#       └── authorization_provider_volume_risk
#
# EXISTING voulme.db IS NOT USED OR MODIFIED.
#
# LOGIC
#   1. Group authorization records by provider_id + month.
#   2. Calculate monthly authorization volume.
#   3. Require 3 previous calendar months of provider history.
#   4. Baseline = previous 3-month median volume.
#   5. Deviation % = |current - baseline| / baseline * 100.
#   6. Risk = deviation / 100, capped at 1.0.
#   7. Risk levels:
#        < 0.25  -> LOW
#        < 0.50  -> MODERATE
#        < 0.75  -> HIGH
#        >= 0.75 -> CRITICAL
#
# No Robust Z-score, PSI, Isolation Forest, or ML model.
# ============================================================


BASE_DIR = Path(__file__).resolve().parent

CLAIM_SENTINEL_DB = BASE_DIR / "claim_sentinel.db"
VOLUME_DB = BASE_DIR / "auth_volume.db"

AUTH_INPUT_TABLE = "authorization_dataset"

AUTH_MONTHLY_TABLE = (
    "authorization_provider_monthly_volume"
)

AUTH_RISK_TABLE = (
    "authorization_provider_volume_risk"
)

MIN_HISTORY_MONTHS = 3
BASELINE_MONTHS = 3
MAX_DEVIATION_FOR_RISK = 100.0

# Avoid overreacting to tiny provider volumes.
# Providers with a baseline below this threshold are not assigned
# Moderate/High/Critical volume risk from percentage deviation alone.
MIN_BASELINE_VOLUME_FOR_RISK = 5


# ============================================================
# RISK LEVEL
# ============================================================

def determine_risk_level(
    risk_score,
    baseline_volume=None,
):

    if pd.isna(risk_score):
        return "INSUFFICIENT_HISTORY"

    if (
        baseline_volume is not None
        and pd.notna(baseline_volume)
        and float(baseline_volume)
        < MIN_BASELINE_VOLUME_FOR_RISK
    ):
        return "LOW_VOLUME"

    if risk_score < 0.25:
        return "LOW"

    if risk_score < 0.50:
        return "MODERATE"

    if risk_score < 0.75:
        return "HIGH"

    return "CRITICAL"


# ============================================================
# ROOT CAUSE
# ============================================================

def generate_root_cause(
    provider_id,
    current_volume,
    baseline,
    deviation_pct,
    risk_level,
):

    if risk_level == "INSUFFICIENT_HISTORY":

        return (
            "Insufficient historical monthly authorization "
            "data is available for this provider to establish "
            "a reliable volume baseline."
        )

    if risk_level == "LOW_VOLUME":

        return (
            f"Provider {provider_id} has a low historical "
            f"authorization baseline of {baseline:.0f} records. "
            "Percentage deviations at this volume can be "
            "misleading and are therefore treated as low-volume "
            "signals rather than material risk."
        )

    if baseline == 0 and current_volume > 0:

        return (
            f"Provider {provider_id} has current authorization "
            "activity while the previous 3-month baseline was zero."
        )

    if risk_level in {
        "CRITICAL",
        "HIGH",
        "MODERATE",
    }:

        direction = (
            "increased"
            if current_volume > baseline
            else "decreased"
        )

        return (
            f"Provider {provider_id} authorization volume has "
            f"{direction} compared with the previous "
            f"{BASELINE_MONTHS}-month baseline. "
            f"Current volume={current_volume:.0f}, "
            f"baseline={baseline:.2f}, "
            f"deviation={abs(deviation_pct):.2f}%."
        )

    return (
        f"Provider {provider_id} authorization volume is "
        "within the expected historical range."
    )


# ============================================================
# RECOMMENDATION
# ============================================================

def generate_recommendation(
    provider_id,
    current_volume,
    baseline,
    risk_level,
):

    if risk_level == "INSUFFICIENT_HISTORY":

        return (
            f"Continue collecting authorization history for "
            f"provider {provider_id} until at least "
            f"{MIN_HISTORY_MONTHS} previous calendar months "
            "are available."
        )

    if risk_level == "LOW_VOLUME":

        return (
            f"Continue monitoring provider {provider_id}. "
            "Collect additional monthly history before treating "
            "percentage changes in this low-volume provider as "
            "a significant operational risk."
        )

    if baseline == 0 and current_volume > 0:

        return (
            f"Review the new authorization activity for provider "
            f"{provider_id} and validate whether the increase is "
            "expected, source-driven, or associated with a batch "
            "or service-code change."
        )

    if risk_level == "CRITICAL":

        if current_volume > baseline:

            return (
                f"Immediately review the increase in authorization "
                f"activity for provider {provider_id}. Check for "
                "unusual service-code activity, urgent requests, "
                "duplicate records, batch changes, or source-system "
                "changes."
            )

        return (
            f"Investigate the significant decrease in authorization "
            f"activity for provider {provider_id}. Validate missing "
            "records, incomplete batches, source delays, or "
            "ingestion failures."
        )

    if risk_level == "HIGH":

        return (
            f"Review provider {provider_id}'s recent authorization "
            "activity against historical behavior and check for "
            "source, batch, service-code, and urgency changes."
        )

    if risk_level == "MODERATE":

        return (
            f"Continue monitoring provider {provider_id}'s "
            "authorization volume and investigate if the deviation "
            "continues in subsequent months."
        )

    return (
        f"No corrective action is required for provider "
        f"{provider_id}. Continue routine monitoring."
    )


# ============================================================
# LOAD AUTHORIZATION DATA
# ============================================================

def load_authorization_data():

    if not CLAIM_SENTINEL_DB.exists():

        raise FileNotFoundError(
            f"Claim Sentinel database not found:\n"
            f"{CLAIM_SENTINEL_DB}"
        )

    conn = sqlite3.connect(
        CLAIM_SENTINEL_DB
    )

    try:

        tables = pd.read_sql_query(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            """,
            conn
        )["name"].tolist()

        if AUTH_INPUT_TABLE not in tables:

            raise ValueError(
                f"Table '{AUTH_INPUT_TABLE}' was not found in "
                f"{CLAIM_SENTINEL_DB}"
            )

        df = pd.read_sql_query(
            f"""
            SELECT
                authorization_id,
                provider_id,
                request_date
            FROM "{AUTH_INPUT_TABLE}"
            """,
            conn
        )

    finally:

        conn.close()

    required = [
        "authorization_id",
        "provider_id",
        "request_date",
    ]

    missing = [
        c for c in required
        if c not in df.columns
    ]

    if missing:

        raise ValueError(
            "Missing required columns: "
            +
            ", ".join(missing)
        )

    df["request_date"] = pd.to_datetime(
        df["request_date"],
        errors="coerce"
    )

    # Keep provider identifiers as strings so 10-digit IDs
    # do not become 1003065772.0.
    df["provider_id"] = (
        df["provider_id"]
        .astype("string")
        .str.replace(
            r"\.0$",
            "",
            regex=True
        )
        .str.strip()
    )

    df = df[
        df["provider_id"].notna()
        &
        (df["provider_id"] != "")
        &
        df["request_date"].notna()
    ].copy()

    return df


# ============================================================
# MONTHLY PROVIDER VOLUME
# ============================================================

def calculate_provider_monthly_volume(df):

    work = df.copy()

    work["period"] = (
        work["request_date"]
        .dt.to_period("M")
        .astype(str)
    )

    monthly = (
        work
        .groupby(
            [
                "provider_id",
                "period",
            ],
            as_index=False,
        )
        .agg(
            monthly_volume=(
                "authorization_id",
                "count",
            )
        )
    )

    monthly = monthly.rename(
        columns={
            "provider_id": "NPI"
        }
    )

    return (
        monthly
        .sort_values(
            ["NPI", "period"]
        )
        .reset_index(drop=True)
    )


# ============================================================
# PROVIDER VOLUME RISK
# ============================================================

def calculate_provider_volume_risk(monthly):

    results = []

    monthly = monthly.copy()

    monthly["period_dt"] = pd.PeriodIndex(
        monthly["period"],
        freq="M",
    )

    for provider_id, provider_df in (
        monthly.groupby("NPI")
    ):

        provider_df = (
            provider_df
            .sort_values("period_dt")
            .copy()
        )

        full_periods = pd.period_range(
            start=provider_df["period_dt"].min(),
            end=provider_df["period_dt"].max(),
            freq="M",
        )

        provider_df = (
            provider_df
            .set_index("period_dt")
            .reindex(full_periods)
        )

        provider_df["NPI"] = provider_id

        provider_df["monthly_volume"] = (
            pd.to_numeric(
                provider_df["monthly_volume"],
                errors="coerce",
            )
            .fillna(0)
            .astype(int)
        )

        provider_df["period"] = (
            provider_df.index.astype(str)
        )

        provider_df = provider_df.reset_index(
            drop=True
        )

        for i in range(
            len(provider_df)
        ):

            current_period = (
                provider_df.loc[
                    i,
                    "period"
                ]
            )

            current_volume = int(
                provider_df.loc[
                    i,
                    "monthly_volume"
                ]
            )

            if i < MIN_HISTORY_MONTHS:

                baseline = np.nan
                deviation_pct = np.nan
                risk_score = np.nan
                risk_level = (
                    "INSUFFICIENT_HISTORY"
                )

                baseline_periods = ""

                history_months = i

            else:

                history = (
                    provider_df
                    .iloc[
                        i - BASELINE_MONTHS:i
                    ]
                )

                baseline = float(
                    history[
                        "monthly_volume"
                    ].median()
                )

                baseline_periods = ",".join(
                    history["period"].astype(str)
                )

                history_months = (
                    BASELINE_MONTHS
                )

                if baseline == 0:

                    if current_volume == 0:

                        deviation_pct = 0.0
                        risk_score = 0.0
                        risk_level = "LOW"

                    else:

                        # No stable positive historical baseline.
                        deviation_pct = np.nan
                        risk_score = np.nan
                        risk_level = (
                            "INSUFFICIENT_HISTORY"
                        )

                else:

                    deviation_pct = (
                        abs(
                            current_volume
                            -
                            baseline
                        )
                        /
                        baseline
                    ) * 100.0

                    risk_score = min(
                        deviation_pct
                        /
                        MAX_DEVIATION_FOR_RISK,
                        1.0,
                    )

                    risk_level = (
                        determine_risk_level(
                            risk_score,
                            baseline_volume=baseline
                        )
                    )

            root_cause = generate_root_cause(
                provider_id,
                current_volume,
                baseline,
                deviation_pct,
                risk_level,
            )

            recommendation = generate_recommendation(
                provider_id,
                current_volume,
                baseline,
                risk_level,
            )

            results.append(
                {
                    "NPI": str(
                        provider_id
                    ),
                    "current_period": (
                        current_period
                    ),
                    "current_month_volume": (
                        current_volume
                    ),
                    "baseline_volume": (
                        float(baseline)
                        if pd.notna(baseline)
                        else None
                    ),
                    "baseline_method": (
                        "ROLLING_3_MONTH_MEDIAN"
                        if pd.notna(baseline)
                        else "INSUFFICIENT_HISTORY"
                    ),
                    "baseline_periods": (
                        baseline_periods
                    ),
                    "deviation_pct": (
                        float(deviation_pct)
                        if pd.notna(deviation_pct)
                        else None
                    ),
                    "volume_risk": (
                        float(risk_score)
                        if pd.notna(risk_score)
                        else None
                    ),
                    "risk_level": (
                        risk_level
                    ),
                    "history_months": (
                        history_months
                    ),
                    "root_cause": (
                        root_cause
                    ),
                    "recommendation": (
                        recommendation
                    ),
                }
            )

    return pd.DataFrame(
        results
    )


# ============================================================
# CREATE AUTHORIZATION TABLES IN NEW auth_volume.db
# ============================================================

def create_output_tables(conn):

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS
        {AUTH_MONTHLY_TABLE} (

            NPI TEXT,
            period TEXT,
            monthly_volume INTEGER,

            root_cause TEXT,
            recommendation TEXT,

            PRIMARY KEY (
                NPI,
                period
            )
        )
        """
    )

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS
        {AUTH_RISK_TABLE} (

            NPI TEXT,
            current_period TEXT,
            current_month_volume INTEGER,
            baseline_volume REAL,
            baseline_method TEXT,
            baseline_periods TEXT,
            deviation_pct REAL,
            volume_risk REAL,
            risk_level TEXT,
            history_months INTEGER,

            root_cause TEXT,
            recommendation TEXT,

            total_authorization_volume INTEGER,
            source_count INTEGER,
            sources TEXT,
            months_available INTEGER,

            PRIMARY KEY (
                NPI,
                current_period
            )
        )
        """
    )

    conn.commit()


# ============================================================
# STORE MONTHLY VOLUME
# ============================================================

def store_monthly_volume(
    conn,
    monthly,
    risk_df,
):

    conn.execute(
        f"DELETE FROM {AUTH_MONTHLY_TABLE}"
    )

    risk_lookup = {
        (
            str(row["NPI"]),
            str(row["current_period"]),
        ): (
            row["root_cause"],
            row["recommendation"],
        )
        for _, row in risk_df.iterrows()
    }

    rows = []

    for _, row in monthly.iterrows():

        key = (
            str(row["NPI"]),
            str(row["period"]),
        )

        root_cause, recommendation = (
            risk_lookup.get(
                key,
                (
                    "No volume-risk issue was identified.",
                    "Continue routine provider-level monitoring.",
                ),
            )
        )

        rows.append(
            (
                str(row["NPI"]),
                str(row["period"]),
                int(row["monthly_volume"]),
                root_cause,
                recommendation,
            )
        )

    conn.executemany(
        f"""
        INSERT OR REPLACE INTO
        {AUTH_MONTHLY_TABLE} (
            NPI,
            period,
            monthly_volume,
            root_cause,
            recommendation
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )

    conn.commit()


# ============================================================
# STORE PROVIDER RISK
# ============================================================

def store_volume_risk(
    conn,
    risk_df,
    total_authorizations,
):

    conn.execute(
        f"DELETE FROM {AUTH_RISK_TABLE}"
    )

    rows = []

    unique_periods = (
        risk_df["current_period"]
        .nunique()
        if not risk_df.empty
        else 0
    )

    for _, row in risk_df.iterrows():

        rows.append(
            (
                str(row["NPI"]),
                str(row["current_period"]),
                int(
                    row["current_month_volume"]
                ),
                row["baseline_volume"],
                row["baseline_method"],
                row["baseline_periods"],
                row["deviation_pct"],
                row["volume_risk"],
                row["risk_level"],
                int(
                    row["history_months"]
                ),
                row["root_cause"],
                row["recommendation"],
                int(total_authorizations),
                1,
                "authorization",
                int(row["history_months"]),
            )
        )

    if rows:
        conn.executemany(
            f"""
            INSERT OR REPLACE INTO
            {AUTH_RISK_TABLE} (

                NPI,
                current_period,
                current_month_volume,
                baseline_volume,
                baseline_method,
                baseline_periods,
                deviation_pct,
                volume_risk,
                risk_level,
                history_months,
                root_cause,
                recommendation,
                total_authorization_volume,
                source_count,
                sources,
                months_available
            )

            VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?
            )
            """,
            rows,
        )

    conn.commit()


# ============================================================
# PRINT
# ============================================================

def print_results(risk_df):

    print("\n" + "=" * 80)
    print(
        "AUTHORIZATION PROVIDER-LEVEL VOLUME RISK"
    )
    print("=" * 80)

    if risk_df.empty:
        print("No provider volume results generated.")
        return

    print(
        f"Providers analyzed : "
        f"{risk_df['NPI'].nunique():,}"
    )

    print(
        f"Provider-periods   : "
        f"{len(risk_df):,}"
    )

    print("\nRisk summary:")
    print(
        risk_df["risk_level"]
        .value_counts(dropna=False)
        .to_string()
    )

    print("\nSample provider results:")

    for _, row in (
        risk_df.head(10).iterrows()
    ):

        print(
            f"\nProvider/NPI       : "
            f"{row['NPI']}"
        )

        print(
            f"Period             : "
            f"{row['current_period']}"
        )

        print(
            f"Current volume     : "
            f"{row['current_month_volume']}"
        )

        print(
            f"Baseline           : "
            f"{row['baseline_volume']}"
        )

        print(
            f"Deviation          : "
            f"{row['deviation_pct']}"
        )

        print(
            f"Volume risk        : "
            f"{row['volume_risk']}"
        )

        print(
            f"Risk level         : "
            f"{row['risk_level']}"
        )

        print(
            f"History months     : "
            f"{row['history_months']}"
        )

        print(
            f"Root cause         : "
            f"{row['root_cause']}"
        )

        print(
            f"Recommendation     : "
            f"{row['recommendation']}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n" + "=" * 80)
    print(
        "CLAIMCARE — AUTHORIZATION "
        "PROVIDER VOLUME ANALYSIS"
    )
    print("=" * 80)

    # --------------------------------------------------------
    # LOAD
    # --------------------------------------------------------

    df = load_authorization_data()

    print(
        f"\nAuthorization rows loaded : "
        f"{len(df):,}"
    )

    print(
        f"Unique providers           : "
        f"{df['provider_id'].nunique():,}"
    )

    print(
        f"Request months             : "
        f"{df['request_date'].dt.to_period('M').nunique():,}"
    )

    # --------------------------------------------------------
    # MONTHLY PROVIDER VOLUME
    # --------------------------------------------------------

    monthly = (
        calculate_provider_monthly_volume(
            df
        )
    )

    # --------------------------------------------------------
    # PROVIDER VOLUME RISK
    # --------------------------------------------------------

    risk_df = (
        calculate_provider_volume_risk(
            monthly
        )
    )

    # --------------------------------------------------------
    # NEW auth_volume.db
    # --------------------------------------------------------

    conn = sqlite3.connect(
        VOLUME_DB
    )

    try:

        create_output_tables(
            conn
        )

        store_monthly_volume(
            conn,
            monthly,
            risk_df,
        )

        store_volume_risk(
            conn,
            risk_df,
            total_authorizations=len(df),
        )

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    print_results(
        risk_df
    )

    print("\n" + "=" * 80)
    print("COMPLETED")
    print("=" * 80)

    print(
        f"Input database   : "
        f"{CLAIM_SENTINEL_DB}"
    )

    print(
        f"Input table      : "
        f"{AUTH_INPUT_TABLE}"
    )

    print(
        f"Output database  : "
        f"{VOLUME_DB}"
    )

    print(
        f"Monthly table    : "
        f"{AUTH_MONTHLY_TABLE}"
    )

    print(
        f"Risk table       : "
        f"{AUTH_RISK_TABLE}"
    )

    print(
        "\nThe existing voulme.db is not modified."
    )


if __name__ == "__main__":
    main()