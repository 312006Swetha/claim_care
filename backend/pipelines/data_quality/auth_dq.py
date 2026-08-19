
import os
import pandas as pd
import numpy as np
import sqlite3
import uuid
import time
from datetime import datetime




# ============================================================
# CONFIGURATION
# ============================================================

# ------------------------------------------------------------
# SOURCE DATABASE
# ------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CLAIM_SENTINEL_DB = os.path.join(
    BASE_DIR,
    "claim_sentinel.db"
)

SOURCE_TABLE = "authorization_dataset"


# ------------------------------------------------------------
# OUTPUT DATABASE
# ------------------------------------------------------------

# This is the database where the DQ results will be stored.
#
# IMPORTANT:
# Existing tables are NOT deleted.
# Results are appended to dq_run_output.
# ------------------------------------------------------------

OUTPUT_DB = os.path.join(
    BASE_DIR,
    "auth_dagster.db"
)

OUTPUT_TABLE = "dq_run_output"


# ------------------------------------------------------------
# DQ CONFIGURATION
# ------------------------------------------------------------

PENDING_SLA_DAYS = 7


VALID_STATUSES = {
    "Approved",
    "Denied",
    "Pending",
    "Expired",
    "Cancelled"
}


VALID_URGENCY = {
    "Routine",
    "Urgent",
    "Emergency"
}


# ============================================================
# DQ SCORE CATEGORY
# ============================================================

def get_category(score):

    if score >= 95:
        return "Excellent"

    elif score >= 85:
        return "Good"

    elif score >= 70:
        return "Warning"

    elif score >= 50:
        return "Poor"

    else:
        return "Critical"


# ============================================================
# SEVERITY RANK
# ============================================================

SEVERITY_RANK = {

    "Good": 0,

    "Low": 1,

    "Medium": 2,

    "High": 3,

    "Critical": 4
}


def get_worst_severity(series):

    if len(series) == 0:
        return "Good"

    highest_rank = max(
        SEVERITY_RANK.get(
            str(x),
            0
        )
        for x in series
    )

    for severity, rank in SEVERITY_RANK.items():

        if rank == highest_rank:
            return severity

    return "Good"


# ============================================================
# CREATE / VERIFY OUTPUT TABLE
# ============================================================

def ensure_output_table(conn):

    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS dq_run_output (

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


# ============================================================
# LOAD AUTHORIZATION DATA FROM CLAIM_SENTINEL.DB
# ============================================================

def load_authorization_dataset():

    print("=" * 80)
    print("AUTHORIZATION DATA QUALITY MONITOR")
    print("=" * 80)

    print(
        "\nSource database:",
        CLAIM_SENTINEL_DB
    )

    print(
        "Source table:",
        SOURCE_TABLE
    )

    conn = sqlite3.connect(
        CLAIM_SENTINEL_DB
    )

    try:

        # ----------------------------------------------------
        # Check table exists
        # ----------------------------------------------------

        table_check = pd.read_sql_query(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name=?
            """,
            conn,
            params=(SOURCE_TABLE,)
        )

        if table_check.empty:

            raise ValueError(
                f"Table '{SOURCE_TABLE}' "
                f"does not exist in {CLAIM_SENTINEL_DB}"
            )


        # ----------------------------------------------------
        # Load authorization_dataset
        # ----------------------------------------------------

        df = pd.read_sql_query(
            f"""
            SELECT *
            FROM "{SOURCE_TABLE}"
            """,
            conn
        )

    finally:

        conn.close()


    # --------------------------------------------------------
    # Clean column names
    # --------------------------------------------------------

    df.columns = (
        df.columns
        .str.strip()
    )


    print(
        "\nTotal authorization records:",
        len(df)
    )


    print(
        "\nSource columns:"
    )

    print(
        df.columns.tolist()
    )


    # --------------------------------------------------------
    # Required columns
    # --------------------------------------------------------

    required_columns = [

        "authorization_id",

        "bene_id",

        "provider_id",

        "service_code",

        "request_date",

        "approval_date",

        "status",

        "expiry_date",

        "urgency",

        "batch_id"
    ]


    missing_columns = [

        col
        for col in required_columns
        if col not in df.columns
    ]


    if missing_columns:

        raise ValueError(
            "authorization_dataset is missing "
            "required columns: "
            + ", ".join(missing_columns)
        )


    return df


# ============================================================
# INITIALIZE DQ COLUMNS
# ============================================================

def initialize_dq_columns(df):

    df["quality_score"] = 100.0

    df["failed_rules"] = ""

    df["root_cause"] = ""

    df["recommendation"] = ""

    df["severity"] = "Good"

    return df


# ============================================================
# STANDARDIZE DATA
# ============================================================

def standardize_data(df):

    string_columns = [

        "authorization_id",

        "bene_id",

        "provider_id",

        "service_code",

        "status",

        "urgency",

        "batch_id"
    ]


    for col in string_columns:

        if col in df.columns:

            if col == "provider_id":

                # Normalize numeric NPI values such as
                # 1003065772.0 to 1003065772.
                df[col] = (
                    df[col]
                    .astype("string")
                    .str.strip()
                    .str.replace(
                        r"^(\d+)\.0$",
                        r"\1",
                        regex=True
                    )
                )

            else:

                df[col] = (
                    df[col]
                    .astype("string")
                    .str.strip()
                )


    date_columns = [

        "request_date",

        "approval_date",

        "expiry_date"
    ]


    for col in date_columns:

        df[col] = pd.to_datetime(
            df[col],
            errors="coerce"
        )


    return df


# ============================================================
# APPLY RULE
# ============================================================

def apply_rule(
    df,
    rule_results,
    mask,
    rule_name,
    dq_dimension,
    deduction,
    severity,
    root_cause,
    recommendation
):

    count = int(
        mask.sum()
    )


    # --------------------------------------------------------
    # Deduct quality score
    # --------------------------------------------------------

    df.loc[
        mask,
        "quality_score"
    ] -= deduction


    # --------------------------------------------------------
    # Failed rules
    # --------------------------------------------------------

    df.loc[
        mask,
        "failed_rules"
    ] = (
        df.loc[
            mask,
            "failed_rules"
        ]
        .apply(
            lambda x:

            f"{x}; {rule_name}"
            if x
            else rule_name
        )
    )


    # --------------------------------------------------------
    # Root cause
    # --------------------------------------------------------

    df.loc[
        mask,
        "root_cause"
    ] = (
        df.loc[
            mask,
            "root_cause"
        ]
        .apply(
            lambda x:

            f"{x}; {root_cause}"
            if x
            else root_cause
        )
    )


    # --------------------------------------------------------
    # Recommendation
    # --------------------------------------------------------

    df.loc[
        mask,
        "recommendation"
    ] = (
        df.loc[
            mask,
            "recommendation"
        ]
        .apply(
            lambda x:

            f"{x}; {recommendation}"
            if x
            else recommendation
        )
    )


    # --------------------------------------------------------
    # Severity
    # --------------------------------------------------------

    current_rank = (
        df.loc[
            mask,
            "severity"
        ]
        .map(
            SEVERITY_RANK
        )
    )


    new_rank = (
        SEVERITY_RANK[
            severity
        ]
    )


    df.loc[
        mask,
        "severity"
    ] = np.where(

        current_rank < new_rank,

        severity,

        df.loc[
            mask,
            "severity"
        ]
    )


    # --------------------------------------------------------
    # Rule summary
    # --------------------------------------------------------

    rule_results.append({

        "rule_name":
            rule_name,

        "dq_dimension":
            dq_dimension,

        "failed_records":
            count,

        "failure_rate_pct":
            round(
                (
                    count
                    /
                    len(df)
                    *
                    100
                ),
                2
            ),

        "severity":
            severity
    })


# ============================================================
# RUN ALL 16 DQ RULES
# ============================================================

def run_dq_rules(df):

    rule_results = []


    # ========================================================
    # RULE 1
    # ========================================================

    mask = (

        df["authorization_id"].isna()

        |

        (
            df["authorization_id"]
            == ""
        )
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Missing Authorization ID",
        "Completeness",
        30,
        "Critical",
        "Authorization ID is missing",
        "Populate a valid unique authorization ID"
    )


    # ========================================================
    # RULE 2
    # ========================================================

    mask = (

        df["bene_id"].isna()

        |

        (
            df["bene_id"]
            == ""
        )
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Missing Beneficiary ID",
        "Completeness",
        15,
        "Critical",
        "Beneficiary ID is missing",
        "Populate a valid beneficiary ID"
    )


    # ========================================================
    # RULE 3
    # ========================================================

    mask = (

        df["provider_id"].isna()

        |

        (
            df["provider_id"]
            == ""
        )
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Missing Provider NPI",
        "Completeness",
        15,
        "Critical",
        "Provider NPI is missing",
        "Populate a valid provider NPI"
    )


    # ========================================================
    # RULE 4
    # ========================================================

    provider_string = (

        df["provider_id"]
        .fillna("")
        .astype(str)
        .str.strip()
    )


    mask = (

        provider_string.ne("")

        &

        (
            ~provider_string.str.fullmatch(
                r"\d{10}"
            )
        )
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Invalid Provider NPI Format",
        "Validity",
        25,
        "Critical",
        "Provider NPI is not exactly 10 numeric digits",
        "Correct provider_id using a valid 10-digit NPI"
    )


    # ========================================================
    # RULE 5
    # ========================================================

    mask = (

        df["service_code"].isna()

        |

        (
            df["service_code"]
            == ""
        )
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Missing Service Code",
        "Completeness",
        15,
        "High",
        "Service code is missing",
        "Populate a valid service code"
    )


    # ========================================================
    # RULE 6
    # ========================================================

    mask = (
        df["request_date"].isna()
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Missing or Invalid Request Date",
        "Completeness",
        15,
        "High",
        "Request date is missing or invalid",
        "Provide a valid authorization request date"
    )


    # ========================================================
    # RULE 7
    # ========================================================

    mask = (

        df["status"].notna()

        &

        ~df["status"].isin(
            VALID_STATUSES
        )
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Invalid Authorization Status",
        "Validity",
        15,
        "High",
        "Status is outside the allowed authorization status values",
        "Use Approved, Denied, Pending, Expired, or Cancelled"
    )


    # ========================================================
    # RULE 8
    # ========================================================

    mask = (

        df["urgency"].notna()

        &

        ~df["urgency"].isin(
            VALID_URGENCY
        )
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Invalid Urgency",
        "Validity",
        10,
        "Medium",
        "Urgency value is invalid",
        "Use Routine, Urgent, or Emergency"
    )


    # ========================================================
    # RULE 9
    # ========================================================

    mask = (

        df["approval_date"].notna()

        &

        df["request_date"].notna()

        &

        (
            df["approval_date"]
            <
            df["request_date"]
        )
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Approval Before Request",
        "Consistency",
        20,
        "Critical",
        "Approval date occurs before request date",
        "Correct the authorization timestamps"
    )


    # ========================================================
    # RULE 10
    # ========================================================

    mask = (

        df["expiry_date"].notna()

        &

        df["approval_date"].notna()

        &

        (
            df["expiry_date"]
            <
            df["approval_date"]
        )
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Expiry Before Approval",
        "Consistency",
        20,
        "Critical",
        "Expiry date occurs before approval date",
        "Correct the approval and expiry dates"
    )


    # ========================================================
    # RULE 11
    # ========================================================

    mask = (

        df["status"].eq(
            "Approved"
        )

        &

        df["approval_date"].isna()
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Approved Without Approval Date",
        "Consistency",
        20,
        "Critical",
        "Authorization is Approved but approval date is missing",
        "Populate approval date or correct authorization status"
    )


    # ========================================================
    # RULE 12
    # ========================================================

    mask = (

        df["status"].eq(
            "Expired"
        )

        &

        df["expiry_date"].isna()
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Expired Without Expiry Date",
        "Consistency",
        20,
        "Critical",
        "Authorization is Expired but expiry date is missing",
        "Populate expiry date or correct authorization status"
    )


    # ========================================================
    # RULE 13
    # ========================================================

    mask = (

        df["status"].eq(
            "Pending"
        )

        &

        df["approval_date"].notna()
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Pending With Approval Date",
        "Consistency",
        15,
        "High",
        "Authorization is Pending even though an approval date exists",
        "Review authorization status and approval information"
    )


    # ========================================================
    # RULE 14
    # ========================================================

    mask = (

        df["authorization_id"].notna()

        &

        df["authorization_id"].duplicated(
            keep=False
        )
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Duplicate Authorization ID",
        "Uniqueness",
        25,
        "Critical",
        "Authorization ID appears more than once",
        "Investigate and remove unintended duplicate records"
    )


    # ========================================================
    # RULE 15
    # ========================================================

    business_columns = [

        "bene_id",

        "provider_id",

        "service_code",

        "request_date"
    ]


    mask = (

        df[business_columns]
        .notna()
        .all(axis=1)

        &

        df.duplicated(
            subset=business_columns,
            keep=False
        )
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Duplicate Authorization Business Record",
        "Uniqueness",
        20,
        "High",
        "Same beneficiary, provider, service and request date occur multiple times",
        "Review the records and remove unintended duplicates"
    )


    # ========================================================
    # RULE 16
    # ========================================================

    today = (
        pd.Timestamp.today()
        .normalize()
    )


    pending_age = (

        today
        -
        df["request_date"]
    ).dt.days


    mask = (

        df["status"].eq(
            "Pending"
        )

        &

        df["request_date"].notna()

        &

        (
            pending_age
            >
            PENDING_SLA_DAYS
        )
    )


    apply_rule(
        df,
        rule_results,
        mask,
        "Pending Beyond SLA",
        "Timeliness",
        15,
        "High",
        "Authorization has remained Pending beyond the configured SLA",
        "Review and process the pending authorization"
    )


    # ========================================================
    # FINAL SCORE
    # ========================================================

    df["quality_score"] = (

        df["quality_score"]
        .clip(0, 100)
        .round(2)
    )


    # ========================================================
    # QUALITY CATEGORY
    # ========================================================

    df["quality_category"] = (

        df["quality_score"]
        .apply(
            get_category
        )
    )


    # ========================================================
    # NO ISSUE RECORDS
    # ========================================================

    no_issue = (

        df["failed_rules"]
        == ""
    )


    df.loc[
        no_issue,
        "failed_rules"
    ] = "No DQ Issues"


    df.loc[
        no_issue,
        "root_cause"
    ] = (
        "No data quality issue detected"
    )


    df.loc[
        no_issue,
        "recommendation"
    ] = (
        "No action required"
    )


    return df, rule_results


# ============================================================
# GROUP BY PROVIDER
# ============================================================

def calculate_provider_dq(df):

    print("\n")
    print("=" * 80)
    print("PROVIDER-WISE DQ CALCULATION")
    print("=" * 80)


    # --------------------------------------------------------
    # Provider grouping
    # --------------------------------------------------------

    df["provider_group"] = (

        df["provider_id"]
        .fillna(
            "MISSING_PROVIDER_NPI"
        )
        .replace(
            "",
            "MISSING_PROVIDER_NPI"
        )
    )


    # --------------------------------------------------------
    # Provider score
    #
    # IMPORTANT:
    #
    # Provider score =
    # average of all authorization quality scores
    # belonging to that provider.
    # --------------------------------------------------------

    provider_df = (

        df.groupby(
            "provider_group",
            dropna=False
        )
        .agg(

            total_authorizations=(

                "provider_group",

                "size"
            ),

            failed_authorizations=(

                "failed_rules",

                lambda x:
                (
                    x != "No DQ Issues"
                ).sum()
            ),

            provider_quality_score=(

                "quality_score",

                "mean"
            )
        )
        .reset_index()
    )


    provider_df = (
        provider_df
        .rename(
            columns={
                "provider_group":
                "provider_id"
            }
        )
    )


    # --------------------------------------------------------
    # Failure rate
    # --------------------------------------------------------

    provider_df[
        "dq_failure_rate_pct"
    ] = np.where(

        provider_df[
            "total_authorizations"
        ] > 0,

        (
            provider_df[
                "failed_authorizations"
            ]

            /

            provider_df[
                "total_authorizations"
            ]

            *

            100
        ),

        0.0
    )

    provider_df[
        "dq_failure_rate_pct"
    ] = (
        pd.Series(
            provider_df[
                "dq_failure_rate_pct"
            ],
            index=provider_df.index
        )
        .replace(
            [np.inf, -np.inf],
            0
        )
        .round(2)
    )


    # --------------------------------------------------------
    # Provider quality score
    # --------------------------------------------------------

    provider_df[
        "provider_quality_score"
    ] = (

        provider_df[
            "provider_quality_score"
        ]
        .clip(
            0,
            100
        )
        .round(2)
    )


    # --------------------------------------------------------
    # Category
    # --------------------------------------------------------

    provider_df[
        "quality_category"
    ] = (

        provider_df[
            "provider_quality_score"
        ]
        .apply(
            get_category
        )
    )


    # ========================================================
    # PROVIDER SEVERITY
    # ========================================================

    provider_severity = (

        df.groupby(
            "provider_group"
        )["severity"]

        .apply(
            get_worst_severity
        )

        .reset_index()
    )


    provider_severity = (

        provider_severity
        .rename(
            columns={
                "provider_group":
                "provider_id",

                "severity":
                "provider_severity"
            }
        )
    )


    provider_df = provider_df.merge(

        provider_severity,

        on="provider_id",

        how="left"
    )


    # ========================================================
    # COMBINE VALUES
    # ========================================================

    def combine_values(series):

        values = []

        for value in series:

            if pd.isna(value):
                continue

            value = str(
                value
            ).strip()

            if not value:
                continue

            for item in value.split(";"):

                item = item.strip()

                if (
                    item
                    and item not in values
                ):
                    values.append(item)

        if values:
            return "; ".join(
                values
            )

        return ""


    # ========================================================
    # FAILED RULES
    # ========================================================

    provider_failed_rules = (

        df.groupby(
            "provider_group"
        )["failed_rules"]

        .apply(
            combine_values
        )

        .reset_index()
    )


    provider_failed_rules = (

        provider_failed_rules
        .rename(
            columns={
                "provider_group":
                "provider_id"
            }
        )
    )


    provider_df = provider_df.merge(

        provider_failed_rules,

        on="provider_id",

        how="left"
    )


    # ========================================================
    # ROOT CAUSE
    # ========================================================

    provider_root_cause = (

        df.groupby(
            "provider_group"
        )["root_cause"]

        .apply(
            combine_values
        )

        .reset_index()
    )


    provider_root_cause = (

        provider_root_cause
        .rename(
            columns={
                "provider_group":
                "provider_id"
            }
        )
    )


    provider_df = provider_df.merge(

        provider_root_cause,

        on="provider_id",

        how="left"
    )


    # ========================================================
    # RECOMMENDATION
    # ========================================================

    provider_recommendation = (

        df.groupby(
            "provider_group"
        )["recommendation"]

        .apply(
            combine_values
        )

        .reset_index()
    )


    provider_recommendation = (

        provider_recommendation
        .rename(
            columns={
                "provider_group":
                "provider_id"
            }
        )
    )


    provider_df = provider_df.merge(

        provider_recommendation,

        on="provider_id",

        how="left"
    )


    # --------------------------------------------------------
    # Rename severity
    # --------------------------------------------------------

    provider_df = (

        provider_df
        .rename(
            columns={
                "provider_severity":
                "severity"
            }
        )
    )


    return provider_df


# ============================================================
# CREATE DAGSTER DQ OUTPUT ROWS
# ============================================================

def create_dq_output_rows(
    df,
    provider_df,
    rule_results,
    run_id,
    batch_id,
    started_at,
    completed_at,
    duration_seconds
):

    rows = []


    # ========================================================
    # 1. PROVIDER-WISE DQ ROW
    #
    # One row = one provider.
    # ========================================================

    for _, provider in provider_df.iterrows():

        provider_id = str(
            provider["provider_id"]
        )


        total_auth = int(
            provider[
                "total_authorizations"
            ]
        )


        failed_auth = int(
            provider[
                "failed_authorizations"
            ]
        )


        quality_score = float(
            provider[
                "provider_quality_score"
            ]
        )


        provider_failure_pct = float(
            provider[
                "dq_failure_rate_pct"
            ]
        )


        provider_status = (

            "FAIL"

            if failed_auth > 0

            else

            "SUCCESS"
        )


        root_cause = (
            provider.get(
                "root_cause",
                ""
            )
        )


        recommendation = (
            provider.get(
                "recommendation",
                ""
            )
        )


        if not root_cause:

            root_cause = (
                "No data quality issue detected"
            )


        if not recommendation:

            recommendation = (
                "No action required"
            )


        # ----------------------------------------------------
        # Overall provider row
        # ----------------------------------------------------

        rows.append({

            "run_id":
                run_id,

            "step_name":
                "authorization_provider_dq",

            "status":
                "SUCCESS",

            "started_at":
                started_at,

            "completed_at":
                completed_at,

            "duration_seconds":
                duration_seconds,

            "records_processed":
                total_auth,

            "dataset_name":
                SOURCE_TABLE,

            "batch_id":
                batch_id,

            "error_message":
                None,

            "dimension":
                "ALL_DQ_DIMENSIONS",

            "field_name":
                "provider_id",

            "rule_name":
                "PROVIDER_DQ_SCORE",

            "affected_rows":
                failed_auth,

            "affected_pct":
                provider_failure_pct,

            "severity":
                provider[
                    "severity"
                ],

            "message":
                (
                    f"Provider {provider_id}: "
                    f"{failed_auth} failed "
                    f"authorization(s) out of "
                    f"{total_auth}; "
                    f"provider quality score "
                    f"= {quality_score}"
                ),

            "total_records":
                total_auth,

            "passed_records":
                total_auth - failed_auth,

            "failed_records":
                failed_auth,

            "total_rules_checked":
                len(rule_results),

            "total_violations":
                failed_auth,

            "critical_count":
                1
                if provider[
                    "severity"
                ] == "Critical"
                else 0,

            "high_count":
                1
                if provider[
                    "severity"
                ] == "High"
                else 0,

            "warning_count":
                1
                if provider[
                    "severity"
                ] == "Medium"
                else 0,

            "info_count":
                1
                if provider[
                    "severity"
                ] == "Good"
                else 0,

            "quality_score":
                quality_score,

            "overall_status":
                provider_status,

            "root_cause":
                root_cause,

            "recommendation":
                recommendation,

            "npi":
                provider_id,

            "npi_total_rows":
                total_auth,

            "npi_affected_rows":
                failed_auth,

            "npi_affected_pct":
                provider_failure_pct,

            "npi_completeness_score":
                None,

            "created_at":
                completed_at,

            "npi_dimension_score":
                quality_score
        })


    # ========================================================
    # 2. RULE SUMMARY ROWS
    #
    # These preserve the 16 DQ rule results.
    # ========================================================

    total_records = len(df)


    for rule in rule_results:

        affected = int(
            rule[
                "failed_records"
            ]
        )


        affected_pct = float(
            rule[
                "failure_rate_pct"
            ]
        )


        passed = (
            total_records
            -
            affected
        )


        rule_status = (

            "FAIL"

            if affected > 0

            else

            "SUCCESS"
        )


        rows.append({

            "run_id":
                run_id,

            "step_name":
                "authorization_dq_rule",

            "status":
                "SUCCESS",

            "started_at":
                started_at,

            "completed_at":
                completed_at,

            "duration_seconds":
                duration_seconds,

            "records_processed":
                total_records,

            "dataset_name":
                SOURCE_TABLE,

            "batch_id":
                batch_id,

            "error_message":
                None,

            "dimension":
                rule[
                    "dq_dimension"
                ],

            "field_name":
                None,

            "rule_name":
                rule[
                    "rule_name"
                ],

            "affected_rows":
                affected,

            "affected_pct":
                affected_pct,

            "severity":
                (
                    rule[
                        "severity"
                    ]
                ),

            "message":
                (
                    f"Rule {rule['rule_name']}: "
                    f"{affected} affected row(s) "
                    f"out of {total_records}"
                ),

            "total_records":
                total_records,

            "passed_records":
                passed,

            "failed_records":
                affected,

            "total_rules_checked":
                1,

            "total_violations":
                affected,

            "critical_count":
                1
                if affected > 0
                and rule[
                    "severity"
                ] == "Critical"
                else 0,

            "high_count":
                1
                if affected > 0
                and rule[
                    "severity"
                ] == "High"
                else 0,

            "warning_count":
                1
                if affected > 0
                and rule[
                    "severity"
                ] == "Medium"
                else 0,

            "info_count":
                1
                if affected == 0
                else 0,

            "quality_score":
                None,

            "overall_status":
                rule_status,

            "root_cause":
                None,

            "recommendation":
                None,

            "npi":
                None,

            "npi_total_rows":
                None,

            "npi_affected_rows":
                None,

            "npi_affected_pct":
                None,

            "npi_completeness_score":
                None,

            "created_at":
                completed_at,

            "npi_dimension_score":
                None
        })


    return pd.DataFrame(
        rows
    )


# ============================================================
# PERSIST RESULTS TO DAGSTER SQLITE DB
# ============================================================

def persist_results(output_df):

    print("\n")
    print("=" * 80)
    print("STORING DQ RESULTS")
    print("=" * 80)


    conn = sqlite3.connect(
        OUTPUT_DB
    )


    try:

        # ----------------------------------------------------
        # DO NOT DELETE EXISTING DATA
        # ----------------------------------------------------

        ensure_output_table(
            conn
        )


        # ----------------------------------------------------
        # Exact column order from claim_dagster dq_run_output
        # ----------------------------------------------------

        output_columns = [

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

            "npi_dimension_score"
        ]


        output_df = output_df[
            output_columns
        ]


        # ----------------------------------------------------
        # APPEND INTO EXISTING dq_run_output
        # ----------------------------------------------------
        # If auth_dagster.db already contains dq_run_output,
        # use its existing columns. SQLite will generate the
        # primary-key id automatically.
        # ----------------------------------------------------

        existing_columns_df = pd.read_sql_query(
            f'PRAGMA table_info("{OUTPUT_TABLE}")',
            conn
        )

        if existing_columns_df.empty:

            output_df.to_sql(
                OUTPUT_TABLE,
                conn,
                if_exists="append",
                index=False
            )

        else:

            existing_columns = (
                existing_columns_df["name"]
                .tolist()
            )

            insert_columns = [
                col
                for col in output_df.columns
                if col in existing_columns
            ]

            if not insert_columns:

                raise ValueError(
                    f"No matching columns found between "
                    f"generated output and {OUTPUT_TABLE} "
                    f"in {OUTPUT_DB}."
                )

            output_df[
                insert_columns
            ].to_sql(
                OUTPUT_TABLE,
                conn,
                if_exists="append",
                index=False
            )

        conn.commit()

        print(
            "\nRows stored:",
            len(output_df)
        )


        print(
            "Output database:",
            OUTPUT_DB
        )


        print(
            "Output table:",
            OUTPUT_TABLE
        )


    finally:

        conn.close()


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n" + "=" * 80)
    print("AUTHORIZATION DATA QUALITY MONITOR")
    print("=" * 80)

    pipeline_start = time.time()

    run_id = str(
        uuid.uuid4()
    )

    started_at = (
        datetime.now()
        .strftime("%Y-%m-%d %H:%M:%S")
    )

    batch_id = (
        datetime.now()
        .strftime("%Y%m%d")
        +
        "_"
        +
        run_id[:8]
    )

    try:

        # ========================================================
        # STEP 1 — LOAD
        # ========================================================

        df = load_authorization_dataset()


        # ========================================================
        # STEP 2 — STANDARDIZE
        # ========================================================

        df = standardize_data(
            df
        )


        # ========================================================
        # STEP 3 — INITIALIZE DQ COLUMNS
        # ========================================================

        df = initialize_dq_columns(
            df
        )


        # ========================================================
        # STEP 4 — RUN 16 DQ RULES
        # ========================================================

        df, rule_results = run_dq_rules(
            df
        )


        # ========================================================
        # STEP 5 — GROUP BY PROVIDER
        # ========================================================

        provider_df = calculate_provider_dq(
            df
        )


        # ========================================================
        # STEP 6 — PROVIDER SCORE
        # ========================================================

        valid_providers = provider_df[
            provider_df["provider_id"]
            !=
            "MISSING_PROVIDER_NPI"
        ]


        if len(valid_providers) > 0:

            overall_provider_score = round(

                valid_providers[
                    "provider_quality_score"
                ].mean(),

                2
            )

        else:

            overall_provider_score = 0.0


        print("\n")
        print("=" * 80)
        print("PROVIDER DQ RESULT")
        print("=" * 80)

        print(
            "Total providers:",
            len(valid_providers)
        )

        print(
            "Overall provider quality score:",
            overall_provider_score,
            "/ 100"
        )

        print("\nProvider-wise sample:")

        print(
            provider_df[
                [
                    "provider_id",
                    "total_authorizations",
                    "failed_authorizations",
                    "dq_failure_rate_pct",
                    "provider_quality_score",
                    "quality_category",
                    "severity"
                ]
            ]
            .head(20)
            .to_string(
                index=False
            )
        )


        # ========================================================
        # STEP 7 — CREATE OUTPUT ROWS
        # ========================================================

        pipeline_end = time.time()

        completed_at = (
            datetime.now()
            .strftime("%Y-%m-%d %H:%M:%S")
        )

        duration_seconds = round(
            pipeline_end
            -
            pipeline_start,
            4
        )

        output_df = create_dq_output_rows(
            df,
            provider_df,
            rule_results,
            run_id,
            batch_id,
            started_at,
            completed_at,
            duration_seconds
        )


        # ========================================================
        # STEP 8 — STORE
        # ========================================================

        persist_results(
            output_df
        )


        print("\n")
        print("=" * 80)
        print("AUTHORIZATION DQ PIPELINE COMPLETED")
        print("=" * 80)

        print(
            "Run ID:",
            run_id
        )

        print(
            "Batch ID:",
            batch_id
        )

        print(
            "Authorization records:",
            len(df)
        )

        print(
            "Providers:",
            len(valid_providers)
        )

        print(
            "Provider quality score:",
            overall_provider_score
        )

        print(
            "Rows stored:",
            len(output_df)
        )

        print(
            "Output database:",
            OUTPUT_DB
        )

        print(
            "Output table:",
            OUTPUT_TABLE
        )

        return {
            "run_id": run_id,
            "batch_id": batch_id,
            "authorization_records": len(df),
            "providers": len(valid_providers),
            "provider_quality_score": overall_provider_score,
            "stored_rows": len(output_df)
        }


    except Exception as e:

        print("\n")
        print("=" * 80)
        print("DQ PIPELINE FAILED")
        print("=" * 80)

        print(
            "Error:",
            str(e)
        )

        raise


# ============================================================
# RUN DIRECTLY FROM VS CODE
# ============================================================

if __name__ == "__main__":
    main()
