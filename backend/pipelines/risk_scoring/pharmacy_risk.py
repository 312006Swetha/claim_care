import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

DQ_DB = Path("pharmacy_database.db")
VOLUME_DB = Path("volume_pharmacy.db")

OUTPUT_DB = Path("provider_risk.db")
OUTPUT_CSV = Path("provider_risk.csv")


# ============================================================
# FINAL RISK WEIGHTS
# ============================================================
#
# SLA Risk and Behavior Risk have been REMOVED.
#
# Original remaining weights:
#
# DQ          = 0.20
# Volume      = 0.15
# Robust Z    = 0.15
# PSI         = 0.10
# Arrival     = 0.10
#
# Total = 0.70
#
# They are normalized to 1.00.
#
# ============================================================

WEIGHTS = {
    "DQ_Risk": 0.285714,
    "Volume_Risk": 0.214286,
    "RobustZ_Risk": 0.214286,
    "PSI_Risk": 0.142857,
    "ArrivalDelay_Risk": 0.142857,
}


# ============================================================
# ARRIVAL DELAY RISK
# ============================================================
#
# TEMPORARY HARD-CODED VALUE
#
# Replace this value later with the actual
# arrival delay risk calculation.
#
# 0.00 = No arrival delay risk
# 1.00 = Maximum arrival delay risk
#
# ============================================================

ARRIVAL_DELAY_RISK = 0.20


# ============================================================
# ROBUST-Z CONFIGURATION
# ============================================================

ROBUST_Z_CAP = 3.5

EPSILON = 1e-6


# ============================================================
# PSI CONFIGURATION
# ============================================================

PSI_BINS = np.array(
    [
        0,
        10,
        20,
        30,
        40,
        50,
        60,
        70,
        80,
        90,
        100.000001,
    ],
    dtype=float
)


# ============================================================
# DATABASE FUNCTIONS
# ============================================================

def check_database(path):

    if not path.exists():

        raise FileNotFoundError(
            f"Database not found: {path.resolve()}"
        )


def read_sqlite(path, query):

    check_database(path)

    with sqlite3.connect(path) as conn:

        return pd.read_sql_query(
            query,
            conn
        )


# ============================================================
# BASIC HELPERS
# ============================================================

def clip01(value):

    value = pd.to_numeric(
        value,
        errors="coerce"
    )

    if pd.isna(value):

        return 0.0

    return float(
        np.clip(
            value,
            0.0,
            1.0
        )
    )


# ============================================================
# ROBUST Z-SCORE
# ============================================================

def robust_z_score(series):

    x = pd.to_numeric(
        series,
        errors="coerce"
    ).astype(float)

    median = x.median()

    valid_values = x.dropna()

    if valid_values.empty:

        return pd.Series(
            0.0,
            index=x.index
        )

    mad = np.median(
        np.abs(
            valid_values - median
        )
    )

    # --------------------------------------------------------
    # If MAD = 0, use standard deviation
    # --------------------------------------------------------

    if (
        not np.isfinite(mad)
        or mad == 0
    ):

        std = x.std(
            ddof=0
        )

        if (
            not np.isfinite(std)
            or std == 0
        ):

            return pd.Series(
                0.0,
                index=x.index
            )

        return (
            x - median
        ) / std

    return (
        0.6745
        *
        (x - median)
        /
        mad
    )


# ============================================================
# ROBUST-Z TO RISK
# ============================================================

def robust_z_to_risk(z):

    z = pd.to_numeric(
        z,
        errors="coerce"
    ).fillna(0.0)

    # Only unusually HIGH values are treated as risk.
    positive_z = np.maximum(
        z,
        0.0
    )

    return np.clip(
        positive_z / ROBUST_Z_CAP,
        0.0,
        1.0
    )


# ============================================================
# PSI DISTRIBUTION
# ============================================================

def weighted_distribution(
    values,
    bins,
    weights=None
):

    values = np.asarray(
        values,
        dtype=float
    )

    valid = np.isfinite(
        values
    )

    values = values[
        valid
    ]

    if weights is not None:

        weights = np.asarray(
            weights,
            dtype=float
        )[valid]

        weights = np.nan_to_num(
            weights,
            nan=0.0,
            posinf=0.0,
            neginf=0.0
        )

        weights = np.maximum(
            weights,
            0.0
        )

    if len(values) == 0:

        return np.zeros(
            len(bins) - 1
        )

    if weights is None:

        counts, _ = np.histogram(
            values,
            bins=bins
        )

    else:

        counts, _ = np.histogram(
            values,
            bins=bins,
            weights=weights
        )

    counts = np.asarray(
        counts,
        dtype=float
    )

    total = counts.sum()

    if total <= 0:

        return np.zeros(
            len(bins) - 1
        )

    return counts / total


# ============================================================
# PSI CALCULATION
# ============================================================

def calculate_psi(
    baseline_values,
    current_values,
    bins,
    baseline_weights=None,
    current_weights=None
):

    baseline = weighted_distribution(
        baseline_values,
        bins,
        baseline_weights
    )

    current = weighted_distribution(
        current_values,
        bins,
        current_weights
    )

    if current.sum() == 0:

        return 0.0

    baseline = np.clip(
        baseline,
        EPSILON,
        None
    )

    current = np.clip(
        current,
        EPSILON,
        None
    )

    baseline = (
        baseline
        /
        baseline.sum()
    )

    current = (
        current
        /
        current.sum()
    )

    psi = np.sum(
        (
            current
            -
            baseline
        )
        *
        np.log(
            current
            /
            baseline
        )
    )

    return max(
        float(psi),
        0.0
    )


# ============================================================
# PSI TO 0-1 RISK
# ============================================================

def psi_to_risk(psi):

    psi = max(
        float(psi),
        0.0
    )

    return float(
        np.clip(
            1.0
            -
            np.exp(-psi),
            0.0,
            1.0
        )
    )


# ============================================================
# LOAD DATA QUALITY DATABASE
# ============================================================

print()
print("=" * 70)
print("LOADING DATA QUALITY OUTPUT")
print("=" * 70)


dq = read_sqlite(
    DQ_DB,

    """
    SELECT
        npi,
        provider_last_name,
        provider_first_name,
        provider_type,
        state,
        quality_score,
        quality_status,
        critical_count,
        high_count,
        warning_count,
        info_count,
        total_violations,
        created_at

    FROM provider_dq_summary

    WHERE run_id = (

        SELECT run_id

        FROM provider_dq_summary

        ORDER BY
            created_at DESC,
            id DESC

        LIMIT 1

    )
    """
)


if dq.empty:

    raise RuntimeError(
        "No provider DQ output found."
    )


dq["npi"] = (
    dq["npi"]
    .astype(str)
)


# ============================================================
# DQ RISK
# ============================================================
#
# quality_score:
#
# 10 = Best quality
# 0  = Worst quality
#
# Therefore:
#
# DQ Risk = 1 - quality_score / 10
#
# ============================================================

dq["DQ_Risk"] = (

    1.0
    -
    pd.to_numeric(
        dq["quality_score"],
        errors="coerce"
    )
    .fillna(0.0)
    .clip(
        0,
        10
    )
    /
    10.0
)


# ============================================================
# LOAD PROVIDER VOLUME DATA
# ============================================================

print()
print("=" * 70)
print("LOADING VOLUME OUTPUT")
print("=" * 70)


volume = read_sqlite(
    VOLUME_DB,

    """
    SELECT *

    FROM pharmacy_npi_volume_risk
    """
)


if volume.empty:

    raise RuntimeError(
        "No provider volume-risk output found."
    )


volume["npi"] = (
    volume[
        "Prscrbr_NPI"
    ]
    .astype(str)
)


# ============================================================
# VOLUME RISK
# ============================================================
#
# Existing score is 0-100.
#
# Convert to 0-1.
#
# ============================================================

volume["Volume_Risk"] = (

    pd.to_numeric(
        volume[
            "volume_risk_score"
        ],
        errors="coerce"
    )
    .fillna(0.0)
    .clip(
        0,
        100
    )
    /
    100.0
)


# ============================================================
# ROBUST-Z RISK
# ============================================================
#
# Calculate provider-level anomaly risk using
# multiple volume metrics.
#
# ============================================================

robust_metrics = [
    "total_claims",
    "total_fills",
    "total_day_supply",
    "total_beneficiaries",
    "total_drug_cost"
]


robust_risk = pd.DataFrame(
    {
        "npi": volume[
            "npi"
        ].astype(str)
    }
)


for metric in robust_metrics:

    # Make sure metric exists.
    if metric not in volume.columns:

        robust_risk[
            f"{metric}_robust_z"
        ] = 0.0

        robust_risk[
            f"{metric}_robust_z_risk"
        ] = 0.0

        continue

    z = robust_z_score(
        volume[
            metric
        ]
    )

    robust_risk[
        f"{metric}_robust_z"
    ] = z

    robust_risk[
        f"{metric}_robust_z_risk"
    ] = robust_z_to_risk(
        z
    )


risk_columns = [
    f"{metric}_robust_z_risk"
    for metric in robust_metrics
]


# Maximum anomaly across the metrics
# becomes the provider Robust-Z risk.

robust_risk[
    "RobustZ_Risk"
] = robust_risk[
    risk_columns
].max(
    axis=1
)


# ============================================================
# LOAD PROVIDER-DRUG DETAIL
# ============================================================

print()
print("=" * 70)
print("LOADING PROVIDER-DRUG DATA")
print("=" * 70)


detail = read_sqlite(
    VOLUME_DB,

    """
    SELECT
        Prscrbr_NPI,
        Brnd_Name,
        Gnrc_Name,
        Tot_Clms

    FROM pharmacy_npi_drug_detail
    """
)


# ============================================================
# LOAD DRUG VOLUME RISK
# ============================================================

drug = read_sqlite(
    VOLUME_DB,

    """
    SELECT
        Brnd_Name,
        Gnrc_Name,
        total_claims,
        volume_risk_score

    FROM pharmacy_drug_volume_risk
    """
)


# ============================================================
# NORMALIZE DRUG KEYS
# ============================================================

for frame in (
    detail,
    drug
):

    frame[
        "brand_key"
    ] = (
        frame[
            "Brnd_Name"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    frame[
        "generic_key"
    ] = (
        frame[
            "Gnrc_Name"
        ]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )


detail["drug_key"] = (
    detail[
        "brand_key"
    ]
    +
    "||"
    +
    detail[
        "generic_key"
    ]
)


drug["drug_key"] = (
    drug[
        "brand_key"
    ]
    +
    "||"
    +
    drug[
        "generic_key"
    ]
)


# ============================================================
# CREATE DRUG LOOKUP
# ============================================================

drug_lookup = drug[
    [
        "drug_key",
        "total_claims",
        "volume_risk_score"
    ]
].drop_duplicates(
    "drug_key"
)


# ============================================================
# JOIN PROVIDER DRUG DATA
# ============================================================

provider_drug = detail.merge(
    drug_lookup,
    on="drug_key",
    how="left"
)


provider_drug["npi"] = (
    provider_drug[
        "Prscrbr_NPI"
    ]
    .astype(str)
)


provider_drug[
    "Tot_Clms"
] = pd.to_numeric(
    provider_drug[
        "Tot_Clms"
    ],
    errors="coerce"
).fillna(0.0)


provider_drug[
    "volume_risk_score"
] = pd.to_numeric(
    provider_drug[
        "volume_risk_score"
    ],
    errors="coerce"
)


# ============================================================
# PSI RISK
# ============================================================
#
# Baseline:
# Overall drug volume-risk distribution.
#
# Current:
# Individual provider's drug volume-risk distribution.
#
# ============================================================

print()
print("=" * 70)
print("CALCULATING PSI RISK")
print("=" * 70)


baseline_values = pd.to_numeric(
    drug[
        "volume_risk_score"
    ],
    errors="coerce"
).values


baseline_weights = pd.to_numeric(
    drug[
        "total_claims"
    ],
    errors="coerce"
).fillna(
    0.0
).values


psi_records = []


for npi, group in provider_drug.groupby(
    "npi"
):

    current_values = pd.to_numeric(
        group[
            "volume_risk_score"
        ],
        errors="coerce"
    )

    valid = (
        current_values.notna()
    )

    current_values = (
        current_values[
            valid
        ].values
    )

    current_weights = (
        group.loc[
            valid,
            "Tot_Clms"
        ].values
    )

    psi_value = calculate_psi(
        baseline_values,
        current_values,
        PSI_BINS,
        baseline_weights,
        current_weights
    )

    psi_records.append(
        {
            "npi": npi,
            "PSI": psi_value,
            "PSI_Risk": psi_to_risk(
                psi_value
            )
        }
    )


psi = pd.DataFrame(
    psi_records
)


# Ensure every provider has a PSI value.

psi = volume[
    [
        "npi"
    ]
].merge(
    psi,
    on="npi",
    how="left"
)


psi[
    "PSI"
] = psi[
    "PSI"
].fillna(0.0)


psi[
    "PSI_Risk"
] = psi[
    "PSI_Risk"
].fillna(0.0)


# ============================================================
# BUILD PROVIDER-LEVEL RESULT
# ============================================================

print()
print("=" * 70)
print("BUILDING PROVIDER-LEVEL RISK")
print("=" * 70)


result = volume[
    [
        "npi",
        "Prscrbr_Last_Org_Name",
        "Prscrbr_First_Name",
        "Prscrbr_City",
        "Prscrbr_State_Abrvtn",
        "Prscrbr_Type",
        "volume_risk_score",
        "volume_risk_level",
        "Volume_Risk"
    ]
].copy()


# ============================================================
# MERGE DQ
# ============================================================

result = result.merge(
    dq[
        [
            "npi",
            "quality_score",
            "quality_status",
            "critical_count",
            "high_count",
            "warning_count",
            "total_violations",
            "DQ_Risk"
        ]
    ],
    on="npi",
    how="left"
)


# ============================================================
# MERGE ROBUST-Z
# ============================================================

result = result.merge(
    robust_risk[
        [
            "npi",
            "RobustZ_Risk"
        ]
    ],
    on="npi",
    how="left"
)


# ============================================================
# MERGE PSI
# ============================================================

result = result.merge(
    psi[
        [
            "npi",
            "PSI",
            "PSI_Risk"
        ]
    ],
    on="npi",
    how="left"
)


# ============================================================
# FILL MISSING VALUES
# ============================================================

result[
    "DQ_Risk"
] = result[
    "DQ_Risk"
].fillna(0.0)


result[
    "Volume_Risk"
] = result[
    "Volume_Risk"
].fillna(0.0)


result[
    "RobustZ_Risk"
] = result[
    "RobustZ_Risk"
].fillna(0.0)


result[
    "PSI_Risk"
] = result[
    "PSI_Risk"
].fillna(0.0)


result[
    "PSI"
] = result[
    "PSI"
].fillna(0.0)


# ============================================================
# ARRIVAL DELAY RISK
# ============================================================
#
# Temporary hard-coded value.
#
# Replace this column later with your actual
# provider-level arrival delay calculation.
#
# ============================================================

result[
    "ArrivalDelay_Risk"
] = clip01(
    ARRIVAL_DELAY_RISK
)


# ============================================================
# FINAL PROVIDER RISK SCORE
# ============================================================

result[
    "Final_Risk_Score"
] = (

    WEIGHTS[
        "DQ_Risk"
    ]
    *
    result[
        "DQ_Risk"
    ]

    +

    WEIGHTS[
        "Volume_Risk"
    ]
    *
    result[
        "Volume_Risk"
    ]

    +

    WEIGHTS[
        "RobustZ_Risk"
    ]
    *
    result[
        "RobustZ_Risk"
    ]

    +

    WEIGHTS[
        "PSI_Risk"
    ]
    *
    result[
        "PSI_Risk"
    ]

    +

    WEIGHTS[
        "ArrivalDelay_Risk"
    ]
    *
    result[
        "ArrivalDelay_Risk"
    ]
)


# ============================================================
# GUARANTEE SCORE BETWEEN 0 AND 1
# ============================================================

result[
    "Final_Risk_Score"
] = result[
    "Final_Risk_Score"
].clip(
    0.0,
    1.0
)


# ============================================================
# RISK LEVEL
# ============================================================

result[
    "Risk_Level"
] = pd.cut(

    result[
        "Final_Risk_Score"
    ],

    bins=[
        -0.000001,
        0.25,
        0.50,
        0.75,
        1.000001
    ],

    labels=[
        "Low",
        "Moderate",
        "High",
        "Critical"
    ],

    include_lowest=True
)


# ============================================================
# ROUND SCORES
# ============================================================

score_columns = [
    "DQ_Risk",
    "Volume_Risk",
    "RobustZ_Risk",
    "PSI_Risk",
    "ArrivalDelay_Risk",
    "Final_Risk_Score"
]


for column in score_columns:

    result[
        column
    ] = (
        pd.to_numeric(
            result[
                column
            ],
            errors="coerce"
        )
        .fillna(0.0)
        .clip(
            0.0,
            1.0
        )
        .round(6)
    )


result[
    "PSI"
] = (
    pd.to_numeric(
        result[
            "PSI"
        ],
        errors="coerce"
    )
    .fillna(0.0)
    .round(6)
)


# ============================================================
# SORT BY HIGHEST RISK
# ============================================================

result = result.sort_values(
    "Final_Risk_Score",
    ascending=False
).reset_index(
    drop=True
)


# ============================================================
# SAVE CSV
# ============================================================

result.to_csv(
    OUTPUT_CSV,
    index=False
)


# ============================================================
# SAVE SQLITE
# ============================================================

with sqlite3.connect(
    OUTPUT_DB
) as conn:

    result.to_sql(
        "provider_risk",
        conn,
        if_exists="replace",
        index=False
    )


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 70)
print("PROVIDER RISK CALCULATION COMPLETE")
print("=" * 70)

print(
    f"Providers processed : "
    f"{len(result):,}"
)

print(
    f"Arrival delay risk  : "
    f"{ARRIVAL_DELAY_RISK:.4f}"
)

print(
    f"Minimum risk score  : "
    f"{result['Final_Risk_Score'].min():.6f}"
)

print(
    f"Maximum risk score  : "
    f"{result['Final_Risk_Score'].max():.6f}"
)

print(
    f"Average risk score  : "
    f"{result['Final_Risk_Score'].mean():.6f}"
)

print()
print("Risk distribution:")
print()

print(
    result[
        "Risk_Level"
    ]
    .value_counts()
    .sort_index()
    .to_string()
)

print()
print("=" * 70)
print("TOP 20 PROVIDERS BY FINAL RISK")
print("=" * 70)

print()

print(
    result[
        [
            "npi",
            "Prscrbr_Last_Org_Name",
            "Prscrbr_First_Name",
            "DQ_Risk",
            "Volume_Risk",
            "RobustZ_Risk",
            "PSI_Risk",
            "ArrivalDelay_Risk",
            "Final_Risk_Score",
            "Risk_Level"
        ]
    ]
    .head(20)
    .to_string(
        index=False
    )
)

print()
print(
    f"CSV output: "
    f"{OUTPUT_CSV.resolve()}"
)

print(
    f"SQLite output: "
    f"{OUTPUT_DB.resolve()}"
)

print("=" * 70)