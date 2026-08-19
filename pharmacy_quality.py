import argparse
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# CONFIG
# ============================================================

SOURCE_DB = "claim_sentinel.db"

SOURCE_TABLE = "part_d_prescriber_drug"

# Existing pharmacy database
OUTPUT_DB = "pharmacy_database.db"


# Tables to store provider-level DQ results
PROVIDER_SUMMARY_TABLE = "provider_dq_summary"
PROVIDER_DIMENSION_TABLE = "provider_dq_dimension"
PROVIDER_EVIDENCE_TABLE = "provider_dq_evidence"


# ============================================================
# REQUIRED FIELDS
# SAME AS EXISTING CODE
# ============================================================

REQUIRED_FIELDS = [
    "Prscrbr_NPI",
    "Prscrbr_Last_Org_Name",
    "Prscrbr_City",
    "Prscrbr_State_Abrvtn",
    "Prscrbr_State_FIPS",
    "Prscrbr_Type",
    "Prscrbr_Type_Src",
    "Brnd_Name",
    "Gnrc_Name",
    "Tot_Clms",
    "Tot_30day_Fills",
    "Tot_Day_Suply",
    "Tot_Drug_Cst",
]


# ============================================================
# VALIDITY VALUES
# SAME AS EXISTING CODE
# ============================================================

VALID_TYPE_SRC = {
    "Claim-Specialty",
    "NPPES-Specialty",
    "NPPES-Taxonomy",
}


VALID_SUPPRESSION_SYMBOLS = {
    "*",
    "#",
    "",
}


# ============================================================
# STATE → FIPS
# SAME AS EXISTING CODE
# ============================================================

STATE_FIPS = {
    "AL": 1,
    "AK": 2,
    "AZ": 4,
    "AR": 5,
    "CA": 6,
    "CO": 8,
    "CT": 9,
    "DE": 10,
    "DC": 11,
    "FL": 12,
    "GA": 13,
    "HI": 15,
    "ID": 16,
    "IL": 17,
    "IN": 18,
    "IA": 19,
    "KS": 20,
    "KY": 21,
    "LA": 22,
    "ME": 23,
    "MD": 24,
    "MA": 25,
    "MI": 26,
    "MN": 27,
    "MS": 28,
    "MO": 29,
    "MT": 30,
    "NE": 31,
    "NV": 32,
    "NH": 33,
    "NJ": 34,
    "NM": 35,
    "NY": 36,
    "NC": 37,
    "ND": 38,
    "OH": 39,
    "OK": 40,
    "OR": 41,
    "PA": 42,
    "RI": 44,
    "SC": 45,
    "SD": 46,
    "TN": 47,
    "TX": 48,
    "UT": 49,
    "VT": 50,
    "VA": 51,
    "WA": 53,
    "WV": 54,
    "WI": 55,
    "WY": 56,
    "PR": 72,
    "VI": 78,
    "GU": 66,
    "AS": 60,
    "MP": 69,
}


# ============================================================
# DQ WEIGHTS
# SAME AS EXISTING CODE
# ============================================================

DIMENSION_WEIGHTS = {
    "completeness": 0.15,
    "uniqueness": 0.10,
    "validity": 0.15,
    "consistency": 0.15,
    "referential_integrity": 0.10,
    "concordance": 0.10,
    "plausibility": 0.15,
    "correctness": 0.10,
}


# ============================================================
# SEVERITY PENALTIES
# SAME AS EXISTING CODE
# ============================================================

SEVERITY_PENALTY = {
    "critical": 1.0,
    "high": 0.75,
    "warning": 0.40,
    "info": 0.0,
}


# ============================================================
# SEVERITY FUNCTION
# SAME AS EXISTING CODE
# ============================================================

def severity_from_pct(pct):

    if pct > 15:
        return "critical"

    if pct >= 1:
        return "high"

    if pct > 0:
        return "warning"

    return "info"


# ============================================================
# 1. COMPLETENESS
# SAME LOGIC
# ============================================================

def check_completeness(df):

    evidence = []

    n = len(df)

    if n == 0:
        return evidence

    for field in REQUIRED_FIELDS:

        if field not in df.columns:
            continue

        nulls = int(
            df[field].isna().sum()
        )

        if nulls > 0:

            pct = round(
                nulls / n * 100,
                2
            )

            evidence.append({
                "dimension": "completeness",
                "field": field,
                "rule": "not_null",
                "affected_rows": nulls,
                "affected_pct": pct,
                "severity": severity_from_pct(pct),
            })

    return evidence


# ============================================================
# 2. UNIQUENESS
# SAME LOGIC
# ============================================================

def check_uniqueness(df):

    evidence = []

    key = [
        "Prscrbr_NPI",
        "Brnd_Name",
        "Gnrc_Name"
    ]

    existing_key = [
        c for c in key
        if c in df.columns
    ]

    if not existing_key:
        return evidence

    dup_mask = df.duplicated(
        subset=existing_key,
        keep=False
    )

    dup_count = int(
        dup_mask.sum()
    )

    if dup_count > 0:

        pct = round(
            dup_count / len(df) * 100,
            2
        )

        evidence.append({
            "dimension": "uniqueness",
            "field": "+".join(existing_key),
            "rule": "unique_key",
            "affected_rows": dup_count,
            "affected_pct": pct,
            "severity": severity_from_pct(pct),
        })

    return evidence


# ============================================================
# 3. VALIDITY
# SAME LOGIC
# ============================================================

def check_validity(df):

    evidence = []

    n = len(df)

    if n == 0:
        return evidence

    def flag(
        field,
        rule,
        mask
    ):

        cnt = int(
            mask.sum()
        )

        if cnt > 0:

            pct = round(
                cnt / n * 100,
                2
            )

            evidence.append({
                "dimension": "validity",
                "field": field,
                "rule": rule,
                "affected_rows": cnt,
                "affected_pct": pct,
                "severity": severity_from_pct(pct),
            })

    # --------------------------------------------------------
    # NPI
    # --------------------------------------------------------

    npi_str = (
        df["Prscrbr_NPI"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    flag(
        "Prscrbr_NPI",
        "must_be_10_digits",
        ~npi_str.str.match(
            r"^\d{10}$"
        )
    )

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    flag(
        "Prscrbr_State_Abrvtn",
        "must_be_valid_state_code",
        ~df[
            "Prscrbr_State_Abrvtn"
        ]
        .fillna("")
        .isin(
            STATE_FIPS.keys()
        )
    )

    # --------------------------------------------------------
    # PROVIDER TYPE SOURCE
    # --------------------------------------------------------

    flag(
        "Prscrbr_Type_Src",
        "must_be_allowed_value",
        ~df[
            "Prscrbr_Type_Src"
        ]
        .fillna("")
        .isin(
            VALID_TYPE_SRC
        )
    )

    # --------------------------------------------------------
    # NUMERIC VALUES
    # --------------------------------------------------------

    for field in [
        "Tot_Clms",
        "Tot_30day_Fills",
        "Tot_Day_Suply",
        "Tot_Drug_Cst"
    ]:

        numeric = pd.to_numeric(
            df[field],
            errors="coerce"
        )

        flag(
            field,
            "must_be_non_negative",
            numeric < 0
        )

    # --------------------------------------------------------
    # SUPPRESSION FLAGS
    # --------------------------------------------------------

    for flag_field in [
        "GE65_Sprsn_Flag",
        "GE65_Bene_Sprsn_Flag"
    ]:

        if flag_field not in df.columns:
            continue

        vals = (
            df[flag_field]
            .fillna("")
            .astype(str)
            .str.strip()
        )

        flag(
            flag_field,
            "must_be_valid_suppression_symbol",
            ~vals.isin(
                VALID_SUPPRESSION_SYMBOLS
            )
        )

    return evidence


# ============================================================
# 4. CONSISTENCY
# SAME LOGIC
# ============================================================

def check_consistency(df):

    evidence = []

    n = len(df)

    if n == 0:
        return evidence

    def flag(
        field,
        rule,
        mask,
        affected_field_label=None
    ):

        cnt = int(
            mask.sum()
        )

        if cnt > 0:

            pct = round(
                cnt / n * 100,
                2
            )

            evidence.append({
                "dimension": "consistency",

                "field":
                    affected_field_label
                    or field,

                "rule": rule,

                "affected_rows":
                    cnt,

                "affected_pct":
                    pct,

                "severity":
                    severity_from_pct(
                        pct
                    ),
            })

    # --------------------------------------------------------
    # CHILD <= PARENT
    # --------------------------------------------------------

    pairs = [
        (
            "GE65_Tot_Clms",
            "Tot_Clms"
        ),
        (
            "GE65_Tot_30day_Fills",
            "Tot_30day_Fills"
        ),
        (
            "GE65_Tot_Drug_Cst",
            "Tot_Drug_Cst"
        ),
        (
            "GE65_Tot_Day_Suply",
            "Tot_Day_Suply"
        ),
        (
            "GE65_Tot_Benes",
            "Tot_Benes"
        ),
    ]

    for child, parent in pairs:

        if child not in df.columns:
            continue

        if parent not in df.columns:
            continue

        c = pd.to_numeric(
            df[child],
            errors="coerce"
        )

        p = pd.to_numeric(
            df[parent],
            errors="coerce"
        )

        mask = (
            c.notna()
            & p.notna()
            & (c > p)
        )

        flag(
            child,
            f"{child}_must_not_exceed_{parent}",
            mask,
            f"{child} vs {parent}"
        )

    # --------------------------------------------------------
    # BENEFICIARIES <= CLAIMS
    # --------------------------------------------------------

    if "Tot_Benes" in df.columns:

        tb = pd.to_numeric(
            df["Tot_Benes"],
            errors="coerce"
        )

        tc = pd.to_numeric(
            df["Tot_Clms"],
            errors="coerce"
        )

        flag(
            "Tot_Benes",
            "Tot_Benes_must_not_exceed_Tot_Clms",
            (
                tb.notna()
                & tc.notna()
                & (tb > tc)
            )
        )

    # --------------------------------------------------------
    # FILLS VS DAY SUPPLY
    # --------------------------------------------------------

    fills = pd.to_numeric(
        df["Tot_30day_Fills"],
        errors="coerce"
    )

    days = pd.to_numeric(
        df["Tot_Day_Suply"],
        errors="coerce"
    )

    expected = fills * 30

    valid_mask = (
        fills.notna()
        & days.notna()
        & (expected > 0)
    )

    deviation_pct = (
        (days - expected).abs()
        / expected.replace(
            0,
            np.nan
        )
    ) * 100

    soft_mask = (
        valid_mask
        & (deviation_pct > 30)
    )

    cnt = int(
        soft_mask.sum()
    )

    if cnt > 0:

        pct = round(
            cnt / n * 100,
            2
        )

        evidence.append({
            "dimension":
                "consistency",

            "field":
                "Tot_Day_Suply vs Tot_30day_Fills*30",

            "rule":
                "soft_ratio_check_30pct_tolerance",

            "affected_rows":
                cnt,

            "affected_pct":
                pct,

            "severity":
                "warning",
        })

    return evidence


# ============================================================
# 5. PLAUSIBILITY
# SAME LOGIC
# ============================================================

def check_plausibility(df):

    evidence = []

    work = df.copy()

    claims = pd.to_numeric(
        work["Tot_Clms"],
        errors="coerce"
    )

    beneficiaries = pd.to_numeric(
        work["Tot_Benes"],
        errors="coerce"
    )

    ratio = (
        claims
        / beneficiaries.replace(
            0,
            np.nan
        )
    )

    high_ratio_mask = (
        ratio > 20
    )

    cnt = int(
        high_ratio_mask.sum()
    )

    if cnt > 0:

        pct = round(
            cnt / len(df) * 100,
            2
        )

        evidence.append({
            "dimension":
                "plausibility",

            "field":
                "Tot_Clms / Tot_Benes",

            "rule":
                "claims_per_beneficiary_over_20_flagged_for_review",

            "affected_rows":
                cnt,

            "affected_pct":
                pct,

            "severity":
                "warning",
        })

    return evidence


# ============================================================
# 6. CORRECTNESS
# SAME LOGIC
# ============================================================

def check_correctness(
    df,
    expected_row_count=None
):

    evidence = []

    if (
        expected_row_count is not None
        and len(df)
        != expected_row_count
    ):

        evidence.append({
            "dimension":
                "correctness",

            "field":
                "row_count",

            "rule":
                "actual_row_count_must_match_expected_row_count",

            "affected_rows":
                abs(
                    len(df)
                    - expected_row_count
                ),

            "affected_pct":
                None,

            "severity":
                "critical",
        })

    return evidence


# ============================================================
# 7. REFERENTIAL INTEGRITY
#
# No new external reference logic is introduced here.
# The original provider DQ code did not execute a separate
# referential-integrity check inside run_all_checks().
#
# We still store the dimension as 10% with score 10.0,
# matching the existing scoring structure.
# ============================================================

def check_referential_integrity(df):

    return []


# ============================================================
# 8. CONCORDANCE
#
# The original provider DQ runner did not execute an HLSum
# concordance check.
#
# Therefore we do not invent a new rule.
# ============================================================

def check_concordance(df):

    return []


# ============================================================
# RUN ALL DQ CHECKS
# SAME EXISTING RULES
# ============================================================

def run_all_checks(
    df,
    expected_row_count=None
):

    evidence = []

    # 1
    evidence += check_completeness(
        df
    )

    # 2
    evidence += check_uniqueness(
        df
    )

    # 3
    evidence += check_validity(
        df
    )

    # 4
    evidence += check_consistency(
        df
    )

    # 5
    evidence += check_referential_integrity(
        df
    )

    # 6
    evidence += check_concordance(
        df
    )

    # 7
    evidence += check_plausibility(
        df
    )

    # 8
    evidence += check_correctness(
        df,
        expected_row_count
    )

    return evidence


# ============================================================
# DQ QUALITY SCORE
# SAME SCORING LOGIC
# ============================================================

def calculate_quality_score(
    evidence
):

    dimension_findings = {
        dimension: []
        for dimension
        in DIMENSION_WEIGHTS
    }

    # --------------------------------------------------------
    # Put findings into dimensions
    # --------------------------------------------------------

    for finding in evidence:

        dimension = finding.get(
            "dimension"
        )

        if dimension in dimension_findings:

            dimension_findings[
                dimension
            ].append(
                finding
            )

    # --------------------------------------------------------
    # Calculate each dimension score
    # --------------------------------------------------------

    dimension_scores = {}

    for dimension, weight in (
        DIMENSION_WEIGHTS.items()
    ):

        # Original starting score
        score = 10.0

        for finding in dimension_findings[
            dimension
        ]:

            severity = str(
                finding.get(
                    "severity",
                    "info"
                )
            ).lower()

            penalty_factor = (
                SEVERITY_PENALTY.get(
                    severity,
                    0
                )
            )

            affected_pct = (
                finding.get(
                    "affected_pct"
                )
            )

            if affected_pct is None:
                affected_pct = 0

            try:

                affected_pct = float(
                    affected_pct
                )

            except Exception:

                affected_pct = 0

            affected_pct = min(
                max(
                    affected_pct,
                    0
                ),
                100
            )

            penalty = (
                penalty_factor
                * affected_pct
                / 100
                * 10
            )

            score -= penalty

        score = max(
            0,
            min(
                10,
                score
            )
        )

        dimension_scores[
            dimension
        ] = round(
            score,
            4
        )

    # --------------------------------------------------------
    # Overall weighted score
    # --------------------------------------------------------

    overall_score = sum(
        dimension_scores[d]
        * DIMENSION_WEIGHTS[d]
        for d in DIMENSION_WEIGHTS
    )

    overall_score = round(
        overall_score,
        4
    )

    # --------------------------------------------------------
    # Status
    # SAME LOGIC
    # --------------------------------------------------------

    if overall_score >= 9:

        status = "excellent"

    elif overall_score >= 7.5:

        status = "good"

    elif overall_score >= 5:

        status = "moderate"

    elif overall_score >= 2.5:

        status = "poor"

    else:

        status = "critical"

    return (
        overall_score,
        status,
        dimension_scores
    )


# ============================================================
# PROVIDER METRICS
# SAME EXISTING LOGIC
# ============================================================

def calculate_provider_metrics(
    provider_df
):

    claims = pd.to_numeric(
        provider_df["Tot_Clms"],
        errors="coerce"
    ).fillna(0)

    fills = pd.to_numeric(
        provider_df["Tot_30day_Fills"],
        errors="coerce"
    ).fillna(0)

    day_supply = pd.to_numeric(
        provider_df["Tot_Day_Suply"],
        errors="coerce"
    ).fillna(0)

    drug_cost = pd.to_numeric(
        provider_df["Tot_Drug_Cst"],
        errors="coerce"
    ).fillna(0)

    beneficiaries = pd.to_numeric(
        provider_df["Tot_Benes"],
        errors="coerce"
    ).fillna(0)

    total_claims = claims.sum()

    total_fills = fills.sum()

    total_day_supply = (
        day_supply.sum()
    )

    total_drug_cost = (
        drug_cost.sum()
    )

    total_beneficiaries = (
        beneficiaries.sum()
    )

    unique_drugs = (
        provider_df["Gnrc_Name"]
        .dropna()
        .astype(str)
        .str.strip()
        .replace(
            "",
            np.nan
        )
        .nunique()
    )

    cost_per_claim = (
        total_drug_cost
        / total_claims
        if total_claims > 0
        else 0
    )

    claims_per_beneficiary = (
        total_claims
        / total_beneficiaries
        if total_beneficiaries > 0
        else 0
    )

    fills_per_claim = (
        total_fills
        / total_claims
        if total_claims > 0
        else 0
    )

    day_supply_per_claim = (
        total_day_supply
        / total_claims
        if total_claims > 0
        else 0
    )

    return {

        "total_records":
            len(provider_df),

        "total_claims":
            float(total_claims),

        "total_fills":
            float(total_fills),

        "total_day_supply":
            float(total_day_supply),

        "total_drug_cost":
            float(total_drug_cost),

        "total_beneficiaries":
            float(total_beneficiaries),

        "unique_drugs":
            int(unique_drugs),

        "cost_per_claim":
            round(
                cost_per_claim,
                4
            ),

        "claims_per_beneficiary":
            round(
                claims_per_beneficiary,
                4
            ),

        "fills_per_claim":
            round(
                fills_per_claim,
                4
            ),

        "day_supply_per_claim":
            round(
                day_supply_per_claim,
                4
            ),
    }


# ============================================================
# HELPER
# GET FIRST NON-EMPTY VALUE
# ============================================================

def get_first_value(
    provider_df,
    column
):

    if column not in provider_df.columns:
        return ""

    values = (
        provider_df[column]
        .dropna()
        .astype(str)
        .str.strip()
    )

    if values.empty:
        return ""

    return values.iloc[0]


# ============================================================
# PROVIDER-LEVEL PROCESSING
#
# IMPORTANT:
# GROUP BY Prscrbr_NPI
#
# NO PEER COMPARISON
# NO ROBUST Z-SCORE
# NO ANOMALY MODEL
# ============================================================

def process_provider_level(
    df
):

    df = df.copy()

    # --------------------------------------------------------
    # Clean NPI
    # --------------------------------------------------------

    df["Prscrbr_NPI"] = (
        df["Prscrbr_NPI"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    # Remove empty NPI
    df = df[
        df["Prscrbr_NPI"] != ""
    ]

    # --------------------------------------------------------
    # Group by provider
    # --------------------------------------------------------

    grouped = df.groupby(
        "Prscrbr_NPI",
        sort=True
    )

    provider_rows = []

    dimension_rows = []

    evidence_rows = []

    print(
        f"\nTotal providers: "
        f"{len(grouped):,}"
    )

    print(
        "\nRunning DQ provider by provider..."
    )

    # --------------------------------------------------------
    # Process each provider
    # --------------------------------------------------------

    for npi, provider_df in grouped:

        print(
            f"Processing provider NPI: "
            f"{npi} "
            f"({len(provider_df)} records)"
        )

        # ----------------------------------------------------
        # SAME DQ RULES
        # But now only this provider's records
        # ----------------------------------------------------

        evidence = run_all_checks(
            provider_df
        )

        # ----------------------------------------------------
        # SAME QUALITY SCORE
        # ----------------------------------------------------

        (
            quality_score,
            quality_status,
            dimension_scores
        ) = calculate_quality_score(
            evidence
        )

        # ----------------------------------------------------
        # Provider metrics
        # ----------------------------------------------------

        metrics = (
            calculate_provider_metrics(
                provider_df
            )
        )

        # ----------------------------------------------------
        # Provider information
        # ----------------------------------------------------

        last_name = get_first_value(
            provider_df,
            "Prscrbr_Last_Org_Name"
        )

        first_name = get_first_value(
            provider_df,
            "Prscrbr_First_Name"
        )

        provider_type = get_first_value(
            provider_df,
            "Prscrbr_Type"
        )

        state = get_first_value(
            provider_df,
            "Prscrbr_State_Abrvtn"
        )

        # ----------------------------------------------------
        # Severity counts
        # ----------------------------------------------------

        critical_count = 0
        high_count = 0
        warning_count = 0
        info_count = 0

        for finding in evidence:

            severity = str(
                finding.get(
                    "severity",
                    "info"
                )
            ).lower()

            if severity == "critical":
                critical_count += 1

            elif severity == "high":
                high_count += 1

            elif severity == "warning":
                warning_count += 1

            else:
                info_count += 1

        total_violations = (
            critical_count
            + high_count
            + warning_count
        )

        # ----------------------------------------------------
        # Provider summary
        # ----------------------------------------------------

        provider_rows.append({

            "npi":
                npi,

            "provider_last_name":
                last_name,

            "provider_first_name":
                first_name,

            "provider_type":
                provider_type,

            "state":
                state,

            **metrics,

            "quality_score":
                quality_score,

            "quality_status":
                quality_status,

            "critical_count":
                critical_count,

            "high_count":
                high_count,

            "warning_count":
                warning_count,

            "info_count":
                info_count,

            "total_violations":
                total_violations,
        })

        # ----------------------------------------------------
        # Dimension table
        # 8 rows per provider
        # ----------------------------------------------------

        for dimension, score in (
            dimension_scores.items()
        ):

            weight = (
                DIMENSION_WEIGHTS[
                    dimension
                ]
            )

            weighted_contribution = (
                score * weight
            )

            findings_count = len(
                [
                    x for x in evidence
                    if x.get(
                        "dimension"
                    ) == dimension
                ]
            )

            dimension_rows.append({

                "npi":
                    npi,

                "dimension":
                    dimension,

                "weight":
                    weight,

                "score":
                    score,

                "weighted_contribution":
                    round(
                        weighted_contribution,
                        4
                    ),

                "findings_count":
                    findings_count,
            })

        # ----------------------------------------------------
        # Evidence table
        # ----------------------------------------------------

        for finding in evidence:

            evidence_rows.append({

                "npi":
                    npi,

                "dimension":
                    finding.get(
                        "dimension"
                    ),

                "field_name":
                    finding.get(
                        "field"
                    ),

                "rule_name":
                    finding.get(
                        "rule"
                    ),

                "affected_rows":
                    finding.get(
                        "affected_rows"
                    ),

                "affected_pct":
                    finding.get(
                        "affected_pct"
                    ),

                "severity":
                    finding.get(
                        "severity"
                    ),

                "note":
                    finding.get(
                        "note"
                    ),
            })

    return (
        pd.DataFrame(provider_rows),
        pd.DataFrame(dimension_rows),
        pd.DataFrame(evidence_rows)
    )


# ============================================================
# CREATE OUTPUT DATABASE TABLES
# ============================================================

def create_output_database():

    conn = sqlite3.connect(
        OUTPUT_DB
    )

    cursor = conn.cursor()

    # ========================================================
    # PROVIDER SUMMARY
    # ========================================================

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS
        {PROVIDER_SUMMARY_TABLE} (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            run_id TEXT NOT NULL,

            npi TEXT NOT NULL,

            provider_last_name TEXT,

            provider_first_name TEXT,

            provider_type TEXT,

            state TEXT,

            total_records INTEGER,

            total_claims REAL,

            total_fills REAL,

            total_day_supply REAL,

            total_drug_cost REAL,

            total_beneficiaries REAL,

            unique_drugs INTEGER,

            cost_per_claim REAL,

            claims_per_beneficiary REAL,

            fills_per_claim REAL,

            day_supply_per_claim REAL,

            quality_score REAL,

            quality_status TEXT,

            critical_count INTEGER,

            high_count INTEGER,

            warning_count INTEGER,

            info_count INTEGER,

            total_violations INTEGER,

            created_at TEXT
        )
        """
    )

    # ========================================================
    # PROVIDER DIMENSIONS
    # ========================================================

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS
        {PROVIDER_DIMENSION_TABLE} (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            run_id TEXT NOT NULL,

            npi TEXT NOT NULL,

            dimension TEXT NOT NULL,

            weight REAL,

            score REAL,

            weighted_contribution REAL,

            findings_count INTEGER,

            created_at TEXT
        )
        """
    )

    # ========================================================
    # PROVIDER EVIDENCE
    # ========================================================

    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS
        {PROVIDER_EVIDENCE_TABLE} (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            run_id TEXT NOT NULL,

            npi TEXT NOT NULL,

            dimension TEXT,

            field_name TEXT,

            rule_name TEXT,

            affected_rows INTEGER,

            affected_pct REAL,

            severity TEXT,

            note TEXT,

            created_at TEXT
        )
        """
    )

    # ========================================================
    # INDEXES
    # ========================================================

    cursor.execute(
        f"""
        CREATE INDEX IF NOT EXISTS
        idx_provider_dq_summary_npi
        ON {PROVIDER_SUMMARY_TABLE}(npi)
        """
    )

    cursor.execute(
        f"""
        CREATE INDEX IF NOT EXISTS
        idx_provider_dq_dimension_npi
        ON {PROVIDER_DIMENSION_TABLE}(npi)
        """
    )

    cursor.execute(
        f"""
        CREATE INDEX IF NOT EXISTS
        idx_provider_dq_evidence_npi
        ON {PROVIDER_EVIDENCE_TABLE}(npi)
        """
    )

    conn.commit()

    conn.close()


# ============================================================
# SAVE RESULTS INTO pharmacy_database.db
# ============================================================

def save_provider_results(
    provider_df,
    dimension_df,
    evidence_df,
    run_id
):

    create_output_database()

    conn = sqlite3.connect(
        OUTPUT_DB
    )

    try:

        created_at = (
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        )

        # ====================================================
        # PROVIDER SUMMARY
        # ====================================================

        summary = provider_df.copy()

        summary["run_id"] = run_id

        summary["created_at"] = (
            created_at
        )

        summary_columns = [

            "run_id",

            "npi",

            "provider_last_name",

            "provider_first_name",

            "provider_type",

            "state",

            "total_records",

            "total_claims",

            "total_fills",

            "total_day_supply",

            "total_drug_cost",

            "total_beneficiaries",

            "unique_drugs",

            "cost_per_claim",

            "claims_per_beneficiary",

            "fills_per_claim",

            "day_supply_per_claim",

            "quality_score",

            "quality_status",

            "critical_count",

            "high_count",

            "warning_count",

            "info_count",

            "total_violations",

            "created_at",
        ]

        summary[
            summary_columns
        ].to_sql(
            PROVIDER_SUMMARY_TABLE,
            conn,
            if_exists="append",
            index=False
        )

        # ====================================================
        # DIMENSIONS
        # ====================================================

        dimensions = (
            dimension_df.copy()
        )

        dimensions["run_id"] = (
            run_id
        )

        dimensions["created_at"] = (
            created_at
        )

        dimension_columns = [

            "run_id",

            "npi",

            "dimension",

            "weight",

            "score",

            "weighted_contribution",

            "findings_count",

            "created_at",
        ]

        dimensions[
            dimension_columns
        ].to_sql(
            PROVIDER_DIMENSION_TABLE,
            conn,
            if_exists="append",
            index=False
        )

        # ====================================================
        # EVIDENCE
        # ====================================================

        if not evidence_df.empty:

            evidence = (
                evidence_df.copy()
            )

            evidence["run_id"] = (
                run_id
            )

            evidence["created_at"] = (
                created_at
            )

            evidence_columns = [

                "run_id",

                "npi",

                "dimension",

                "field_name",

                "rule_name",

                "affected_rows",

                "affected_pct",

                "severity",

                "note",

                "created_at",
            ]

            evidence[
                evidence_columns
            ].to_sql(
                PROVIDER_EVIDENCE_TABLE,
                conn,
                if_exists="append",
                index=False
            )

        conn.commit()

    finally:

        conn.close()


# ============================================================
# DISPLAY RESULTS
# ============================================================

def display_results(
    provider_df
):

    print(
        "\n"
        + "=" * 90
    )

    print(
        "PROVIDER LEVEL DQ RESULTS"
    )

    print(
        "=" * 90
    )

    display_columns = [

        "npi",

        "provider_last_name",

        "provider_type",

        "state",

        "total_records",

        "quality_score",

        "quality_status",

        "total_violations",
    ]

    print(
        provider_df[
            display_columns
        ]
        .sort_values(
            "quality_score"
        )
        .to_string(
            index=False
        )
    )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Pharmacy Provider-Level "
            "Data Quality Engine"
        )
    )

    parser.add_argument(
        "--db",
        default=SOURCE_DB,
        help=(
            "Source SQLite database. "
            "Default: claim_sentinel.db"
        )
    )

    parser.add_argument(
        "--table",
        default=SOURCE_TABLE,
        help=(
            "Source pharmacy table. "
            "Default: part_d_prescriber_drug"
        )
    )

    args = parser.parse_args()

    # ========================================================
    # RUN ID
    # ========================================================

    run_id = str(
        uuid.uuid4()
    )

    start = time.perf_counter()

    # ========================================================
    # SOURCE DATABASE
    # ========================================================

    source_db = Path(
        args.db
    )

    if not source_db.exists():

        raise FileNotFoundError(
            f"\nDatabase not found:\n"
            f"{source_db.resolve()}"
        )

    print(
        "\n"
        + "=" * 90
    )

    print(
        "PHARMACY PROVIDER-LEVEL DQ ENGINE"
    )

    print(
        "=" * 90
    )

    print(
        f"Source DB       : "
        f"{source_db.resolve()}"
    )

    print(
        f"Source Table    : "
        f"{args.table}"
    )

    print(
        f"Output DB       : "
        f"{Path(OUTPUT_DB).resolve()}"
    )

    print(
        "Peer Logic      : REMOVED"
    )

    print(
        "Anomaly Score   : REMOVED"
    )

    print(
        "Max Anomaly Z   : REMOVED"
    )

    print(
        "Anomaly Status  : REMOVED"
    )

    # ========================================================
    # CONNECT SOURCE DATABASE
    # ========================================================

    conn = sqlite3.connect(
        source_db
    )

    try:

        # ----------------------------------------------------
        # Check tables
        # ----------------------------------------------------

        tables = pd.read_sql_query(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """,
            conn
        )

        table_names = (
            tables["name"]
            .tolist()
        )

        if args.table not in table_names:

            raise ValueError(
                f"\nTable '{args.table}' "
                f"not found.\n\n"
                f"Available tables:\n"
                f"{table_names}"
            )

        # ----------------------------------------------------
        # Load pharmacy data
        # ----------------------------------------------------

        df = pd.read_sql_query(
            f'''
            SELECT *
            FROM "{args.table}"
            ''',
            conn
        )

    finally:

        conn.close()

    print(
        f"\nTotal pharmacy rows : "
        f"{len(df):,}"
    )

    # ========================================================
    # REQUIRED COLUMN CHECK
    # ========================================================

    if "Prscrbr_NPI" not in df.columns:

        raise ValueError(
            "\nPrscrbr_NPI column "
            "not found in source table."
        )

    # ========================================================
    # CHECK REQUIRED DQ COLUMNS
    # ========================================================

    missing_columns = [
        col
        for col in REQUIRED_FIELDS
        if col not in df.columns
    ]

    if missing_columns:

        print(
            "\nMissing required columns:"
        )

        for column in missing_columns:

            print(
                f"  - {column}"
            )

        raise ValueError(
            "\nRequired DQ columns are missing."
        )

    # ========================================================
    # PROVIDER LEVEL PROCESSING
    # ========================================================

    (
        provider_df,
        dimension_df,
        evidence_df
    ) = process_provider_level(
        df
    )

    # ========================================================
    # SAVE EVERYTHING
    # ========================================================

    save_provider_results(

        provider_df,

        dimension_df,

        evidence_df,

        run_id
    )

    # ========================================================
    # DISPLAY
    # ========================================================

    display_results(
        provider_df
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print(
        "\n"
        + "=" * 90
    )

    print(
        "DATABASE STORAGE SUMMARY"
    )

    print(
        "=" * 90
    )

    print(
        f"Database              : "
        f"{Path(OUTPUT_DB).resolve()}"
    )

    print(
        f"Run ID                : "
        f"{run_id}"
    )

    print(
        f"Providers stored      : "
        f"{len(provider_df):,}"
    )

    print(
        f"Dimension rows stored : "
        f"{len(dimension_df):,}"
    )

    print(
        f"Evidence rows stored  : "
        f"{len(evidence_df):,}"
    )

    print(
        "\nTables created:"
    )

    print(
        f"1. {PROVIDER_SUMMARY_TABLE}"
    )

    print(
        f"2. {PROVIDER_DIMENSION_TABLE}"
    )

    print(
        f"3. {PROVIDER_EVIDENCE_TABLE}"
    )

    print(
        "\n"
        "No peer/anomaly calculations were performed."
    )

    print(
        "\nProcessing time: "
        f"{time.perf_counter() - start:.2f} seconds"
    )

    print(
        "=" * 90
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()