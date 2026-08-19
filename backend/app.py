from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3
import os
from math import ceil

app = Flask(__name__)
CORS(app)

# ============================================================
# DATABASE LOCATION
# ============================================================

def resolve_data_dir():
    env_dir = os.environ.get("CLAIMCARE_DATA_DIR")
    if env_dir and os.path.isdir(env_dir):
        return env_dir
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
    
    for candidate in [
        parent_dir,
        os.path.join(parent_dir, "data"),
        os.path.join(parent_dir, "Data"),
        current_dir,
        os.path.join(current_dir, "data"),
    ]:
        if os.path.exists(os.path.join(candidate, "claim_sentinel.db")) or os.path.exists(os.path.join(candidate, "anomalies.db")):
            return candidate
    
    return parent_dir

BASE_DIR = resolve_data_dir()

def find_db_path(*names):
    for name in names:
        candidate = os.path.join(BASE_DIR, name)
        if os.path.exists(candidate):
            return candidate
        candidate_data = os.path.join(BASE_DIR, "Data", name)
        if os.path.exists(candidate_data):
            return candidate_data
    return os.path.join(BASE_DIR, names[-1])

ANOMALIES_DB = find_db_path("anomalies.db")
CLAIMS_SLA_DB = find_db_path("claims_sla_behavior.db")
PHARMACY_SLA_DB = find_db_path("pharmacy_sla_behavior.db")
DRUG_VOLUME_DB = find_db_path("volume_pharmacy(3).db", "volume_pharmacy.db")
VOLUME_DB = find_db_path("voulme.db", "volume.db")
AUTH_VOLUME_DB = find_db_path("auth_volume.db")
AUTH_DAGSTER_DB = find_db_path("auth_dagster.db")
AUTH_SLA_DB = find_db_path("auth_sla.db")
FINAL_SLA_RISK_DB = find_db_path("final_sla_risk.db")
PHARMACY_DQ_DB = find_db_path("pharmacy_database.db")
DAGSTER_DQ_DB = find_db_path("claim_dagster.db")
CLAIM_SENTINEL_DB = find_db_path("claim_sentinel.db")

CLAIM_SENTINEL_DATASETS = {
    "authorization_dataset",
    "beneficiary",
    "carrier",
    "dme",
    "hha",
    "hospice",
    "inpatient",
    "outpatient",
    "snf",
}


# ============================================================
# SQLITE CONNECTION
# ============================================================

def get_connection(db_path):
    if not os.path.exists(db_path):
        raise FileNotFoundError(
            f"Database not found: {db_path}"
        )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def rows_to_dict(rows):
    return [dict(row) for row in rows]


def parse_int_arg(name, default, minimum=1, maximum=None):
    raw = request.args.get(name, str(default)).strip()

    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default

    value = max(minimum, value)

    if maximum is not None:
        value = min(maximum, value)

    return value


def get_table_columns(cursor, table_name):
    cursor.execute(f'PRAGMA table_info("{table_name}")')
    return [row["name"] for row in cursor.fetchall()]


def safe_order_by(requested_field, allowed_fields, fallback_field):
    if requested_field in allowed_fields:
        return requested_field
    return fallback_field


def safe_sort_direction(raw_direction):
    if str(raw_direction or "").lower() == "asc":
        return "ASC"
    return "DESC"


def paginate_payload(total, page, page_size):
    total_pages = max(1, ceil(total / page_size)) if page_size else 1
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
    }


def get_dashboard_module():
    module = request.args.get("module", "claims").strip().lower()

    if module in {"claims", "drugs", "authorization"}:
        return module

    return "claims"


def get_drug_summary_payload():
    conn = get_connection(DRUG_VOLUME_DB)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) AS total_drugs
        FROM pharmacy_drug_volume_risk
    """)
    total_drugs = int(cursor.fetchone()["total_drugs"] or 0)

    cursor.execute("""
        SELECT COUNT(DISTINCT Brnd_Name) AS unique_drugs
        FROM pharmacy_drug_volume_risk
        WHERE Brnd_Name IS NOT NULL
          AND TRIM(Brnd_Name) <> ''
    """)
    unique_drugs = int(cursor.fetchone()["unique_drugs"] or 0)

    cursor.execute("""
        SELECT COUNT(DISTINCT Prscrbr_NPI) AS affected_providers
        FROM pharmacy_npi_volume_risk
        WHERE Prscrbr_NPI IS NOT NULL
          AND TRIM(Prscrbr_NPI) <> ''
    """)
    affected_providers = int(cursor.fetchone()["affected_providers"] or 0)

    cursor.execute("""
        SELECT COUNT(*) AS high_severity
        FROM pharmacy_drug_volume_risk
        WHERE UPPER(COALESCE(volume_risk_level, '')) IN ('HIGH', 'CRITICAL')
    """)
    high_severity = int(cursor.fetchone()["high_severity"] or 0)

    cursor.execute("""
        SELECT COUNT(*) AS active_alerts
        FROM pharmacy_drug_volume_risk
        WHERE UPPER(COALESCE(volume_risk_level, '')) IN ('HIGH', 'CRITICAL')
           OR COALESCE(high_risk_flag_count, 0) > 0
    """)
    active_alerts = int(cursor.fetchone()["active_alerts"] or 0)

    conn.close()

    return {
        "total_drugs": total_drugs,
        "unique_drugs": unique_drugs,
        "affected_providers": affected_providers,
        "high_severity": high_severity,
        "risk_anomalies": high_severity,
        "active_alerts": active_alerts,
    }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/")
def home():
    return jsonify({
        "status": "success",
        "message": "ClaimCare SQLite API is running",
        "database": "SQLite",
        "port": 5000
    })


@app.route("/api/health")
def health():

    databases = {
        "anomalies.db": ANOMALIES_DB,
        "claims_sla_behavior.db": CLAIMS_SLA_DB,
        "pharmacy_sla_behavior.db": PHARMACY_SLA_DB,
        "voulme.db": VOLUME_DB,
        "final_sla_risk.db": FINAL_SLA_RISK_DB,
        "pharmacy_database.db": PHARMACY_DQ_DB,
        "claim_dagster.db": DAGSTER_DQ_DB
    }

    result = {}

    for name, path in databases.items():
        result[name] = {
            "exists": os.path.exists(path),
            "path": path
        }

    return jsonify(result)


# ============================================================
# DASHBOARD SUMMARY
# ============================================================

@app.route("/api/dashboard/summary")
def dashboard_summary():

    try:
        module = get_dashboard_module()

        if module == "drugs":
            summary = get_drug_summary_payload()

            return jsonify({
                "module": module,
                "total_records": summary["total_drugs"],
                "processed_claims": summary["unique_drugs"],
                "total_providers": summary["affected_providers"],
                "sla_breaches": summary["high_severity"],
                "sla_compliance": None,
                "active_alerts": summary["active_alerts"],
                "dq_alerts": 0,
                "volume_alerts": 0,
                "sla_alerts": 0,
                "drug_anomalies": summary["risk_anomalies"],
                "claim_anomalies": 0,
                "total_anomalies": summary["risk_anomalies"],
                "high_risk": summary["high_severity"],
                "affected_providers": summary["affected_providers"],
                "psi_anomalies": summary["risk_anomalies"],
                "robust_z_anomalies": 0,
            })

        if module == "authorization":

            total_records = 0
            processed_records = 0
            total_providers = 0
            sla_breaches = 0
            sla_compliance_pct = None
            dq_alerts = 0
            volume_alerts = 0
            sla_alerts = 0

            conn = get_connection(AUTH_VOLUME_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(DISTINCT NPI) AS total
                FROM authorization_provider_volume_risk
                WHERE NPI IS NOT NULL
                  AND TRIM(NPI) <> ''
            """)
            total_providers = int(cursor.fetchone()["total"] or 0)

            cursor.execute("""
                WITH latest_provider_snapshot AS (
                    SELECT v.*
                    FROM authorization_provider_volume_risk v
                    INNER JOIN (
                        SELECT
                            NPI,
                            MAX(current_period) AS current_period
                        FROM authorization_provider_volume_risk
                        WHERE NPI IS NOT NULL
                          AND TRIM(NPI) <> ''
                        GROUP BY NPI
                    ) latest
                        ON latest.NPI = v.NPI
                       AND latest.current_period = v.current_period
                )
                SELECT COUNT(*) AS total
                FROM latest_provider_snapshot
                WHERE UPPER(COALESCE(risk_level, '')) IN ('HIGH', 'CRITICAL')
            """)
            volume_alerts = int(cursor.fetchone()["total"] or 0)
            conn.close()

            conn = get_connection(AUTH_DAGSTER_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COALESCE(MAX(records_processed), 0) AS total
                FROM dq_run_output
                WHERE step_name = 'authorization_dq_rule'
                  AND records_processed IS NOT NULL
            """)
            processed_records = int(cursor.fetchone()["total"] or 0)

            cursor.execute("""
                SELECT
                    COALESCE(SUM(critical_count), 0)
                    + COALESCE(SUM(high_count), 0) AS total
                FROM dq_run_output
                WHERE step_name = 'authorization_dq_rule'
            """)
            dq_alerts = int(cursor.fetchone()["total"] or 0)
            conn.close()

            conn = get_connection(AUTH_SLA_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COALESCE(total_records, records_processed, 0) AS total_records,
                    COALESCE(failed_records, affected_rows, 0) AS breached_records,
                    COALESCE(passed_records, 0) AS met_records
                FROM dq_run_output
                WHERE step_name = 'authorization_sla_behavior'
                ORDER BY COALESCE(created_at, completed_at, started_at) DESC, id DESC
                LIMIT 1
            """)
            row = cursor.fetchone()

            if row:
                total_records = int(
                    row["total_records"] or total_records
                )
                sla_breaches = int(
                    row["breached_records"] or 0
                )
                met_records = int(
                    row["met_records"] or 0
                )
                evaluable_records = met_records + sla_breaches

                if evaluable_records > 0:
                    sla_compliance_pct = round(
                        (met_records / evaluable_records) * 100,
                        2,
                    )

            if total_records == 0:
                cursor.execute("""
                    SELECT COALESCE(MAX(total_records), 0) AS total_records
                    FROM dq_run_output
                    WHERE step_name = 'authorization_sla'
                """)
                total_records = int(
                    cursor.fetchone()["total_records"] or 0
                )

            if sla_breaches == 0:
                cursor.execute("""
                    SELECT COALESCE(COUNT(*), 0) AS breached_records
                    FROM dq_run_output
                    WHERE step_name = 'authorization_sla'
                      AND UPPER(COALESCE(overall_status, '')) = 'BREACHED'
                """)
                sla_breaches = int(
                    cursor.fetchone()["breached_records"] or 0
                )

            if sla_compliance_pct is None:
                cursor.execute("""
                    SELECT
                        SUM(
                            CASE
                                WHEN UPPER(COALESCE(overall_status, '')) = 'MET'
                                THEN 1 ELSE 0
                            END
                        ) AS met_records,
                        SUM(
                            CASE
                                WHEN UPPER(COALESCE(overall_status, '')) = 'BREACHED'
                                THEN 1 ELSE 0
                            END
                        ) AS breached_records
                    FROM dq_run_output
                    WHERE step_name = 'authorization_sla'
                """)
                row = cursor.fetchone()
                met_records = int(row["met_records"] or 0)
                breached_records = int(row["breached_records"] or 0)
                evaluable_records = met_records + breached_records

                if evaluable_records > 0:
                    sla_compliance_pct = round(
                        (met_records / evaluable_records) * 100,
                        2,
                    )

            if sla_compliance_pct is not None:
                sla_compliance_pct = round(
                    float(sla_compliance_pct),
                    2,
                )

            sla_alerts = sla_breaches
            conn.close()

            return jsonify({
                "module": module,
                "total_records": total_records,
                "processed_claims": processed_records,
                "total_providers": total_providers,
                "sla_breaches": sla_breaches,
                "sla_compliance": sla_compliance_pct,
                "active_alerts": dq_alerts,
                "dq_alerts": dq_alerts,
                "volume_alerts": volume_alerts,
                "sla_alerts": sla_alerts,
                "drug_anomalies": 0,
                "claim_anomalies": 0,
                "total_anomalies": dq_alerts + volume_alerts,
                "high_risk": volume_alerts,
                "affected_providers": total_providers,
                "psi_anomalies": 0,
                "robust_z_anomalies": 0,
            })

        # ====================================================
        # ANOMALIES
        # ====================================================

        conn = get_connection(ANOMALIES_DB)
        cursor = conn.cursor()

        # Drug anomaly count
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM drug_anomalies
        """)

        drug_anomalies = cursor.fetchone()["total"]

        # Claims anomaly count
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM claims_anomalies
        """)

        claim_anomalies = cursor.fetchone()["total"]

        # High severity drug anomalies
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM drug_anomalies
            WHERE UPPER(COALESCE(severity, '')) = 'HIGH'
        """)

        drug_high = cursor.fetchone()["total"]

        # High severity claim anomalies
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM claims_anomalies
            WHERE UPPER(COALESCE(severity, '')) = 'HIGH'
        """)

        claim_high = cursor.fetchone()["total"]

        # Unique providers
        provider_ids = set()

        cursor.execute("""
            SELECT DISTINCT provider_id
            FROM drug_anomalies
            WHERE provider_id IS NOT NULL
        """)

        for row in cursor.fetchall():
            provider_ids.add(str(row["provider_id"]))

        cursor.execute("""
            SELECT DISTINCT provider_id
            FROM claims_anomalies
            WHERE provider_id IS NOT NULL
        """)

        for row in cursor.fetchall():
            provider_ids.add(str(row["provider_id"]))

        affected_providers = len(provider_ids)

        # PSI anomalies
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM drug_anomalies
            WHERE psi_anomaly = 1
        """)

        drug_psi = cursor.fetchone()["total"]

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM claims_anomalies
            WHERE psi_anomaly = 1
        """)

        claim_psi = cursor.fetchone()["total"]

        # Robust Z anomalies
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM drug_anomalies
            WHERE robust_z_anomaly = 1
        """)

        drug_robust = cursor.fetchone()["total"]

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM claims_anomalies
            WHERE robust_z_anomaly = 1
        """)

        claim_robust = cursor.fetchone()["total"]

        conn.close()

        # ====================================================
        # TOTAL RECORDS (combined_provider_claims)
        # ====================================================

        total_records = 0

        try:

            conn = get_connection(VOLUME_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM combined_provider_claims
            """)

            row = cursor.fetchone()

            if row and row["total"] is not None:
                total_records = int(row["total"])

            conn.close()

        except Exception as e:
            print("Total records warning:", e)

        # ====================================================
        # PROCESSED CLAIMS (claim_dagster.db)
        # ====================================================

        processed_claims = 0

        try:

            conn = get_connection(DAGSTER_DQ_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COALESCE(SUM(records_processed), 0) AS total
                FROM dq_run_output
                WHERE records_processed IS NOT NULL
            """)

            row = cursor.fetchone()

            if row:
                processed_claims = int(row["total"])

            conn.close()

        except Exception as e:
            print("Processed claims warning:", e)

        # ====================================================
        # TOTAL PROVIDERS (voulme.db)
        # ====================================================

        total_providers = 0

        try:

            conn = get_connection(VOLUME_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(DISTINCT NPI) AS total
                FROM provider_volume_risk
            """)

            row = cursor.fetchone()

            if row:
                total_providers = int(row["total"])

            conn.close()

        except Exception as e:
            print("Total providers warning:", e)

        # ====================================================
        # SLA BREACHES (claims_sla_behavior.db)
        # ====================================================

        sla_breaches = 0

        try:

            conn = get_connection(CLAIMS_SLA_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COALESCE(SUM(sla_breached_count), 0) AS total
                FROM claims_sla_behavior
                WHERE sla_breached_count IS NOT NULL
            """)

            row = cursor.fetchone()

            if row:
                sla_breaches = int(row["total"])

            conn.close()

        except Exception as e:
            print("SLA breaches warning:", e)

        # ====================================================
        # SLA COMPLIANCE % (claims_sla_behavior.db)
        # Formula: (SUM(sla_met_count) / SUM(sla_evaluable_runs)) * 100
        # ====================================================

        sla_compliance_pct = None

        try:

            conn = get_connection(CLAIMS_SLA_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COALESCE(SUM(sla_met_count), 0) AS met,
                    COALESCE(SUM(sla_evaluable_runs), 0) AS evaluable
                FROM claims_sla_behavior
            """)

            row = cursor.fetchone()

            if row and row["evaluable"] > 0:
                sla_compliance_pct = round(
                    (row["met"] / row["evaluable"]) * 100,
                    2
                )

            conn.close()

        except Exception as e:
            print("SLA compliance warning:", e)

        # ====================================================
        # ACTIVE ALERTS (DQ + Volume + SLA combined)
        # ====================================================

        active_alerts = 0

        # DQ critical + high alerts from claim_dagster.db
        dq_alerts = 0

        try:

            conn = get_connection(DAGSTER_DQ_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM dq_run_output
                WHERE UPPER(COALESCE(severity, '')) IN ('CRITICAL', 'HIGH')
            """)

            row = cursor.fetchone()

            if row:
                dq_alerts = row["total"]

            conn.close()

        except Exception as e:
            print("DQ alerts warning:", e)

        # Volume high + critical alerts from voulme.db
        volume_alerts = 0

        try:

            conn = get_connection(VOLUME_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM provider_volume_risk
                WHERE UPPER(COALESCE(risk_level, '')) IN ('HIGH', 'CRITICAL')
            """)

            row = cursor.fetchone()

            if row:
                volume_alerts = row["total"]

            conn.close()

        except Exception as e:
            print("Volume alerts warning:", e)

        # SLA breach alerts from claims_sla_behavior.db
        sla_alerts = sla_breaches

        active_alerts = dq_alerts + volume_alerts + sla_alerts

        # ====================================================
        # FINAL RESPONSE
        # ====================================================

        return jsonify({

            "total_records": total_records,

            "processed_claims": processed_claims,

            "total_providers": total_providers,

            "sla_breaches": sla_breaches,

            "sla_compliance": sla_compliance_pct,

            "active_alerts": active_alerts,

            "dq_alerts": dq_alerts,

            "volume_alerts": volume_alerts,

            "sla_alerts": sla_alerts,

            "drug_anomalies":
                drug_anomalies,

            "claim_anomalies":
                claim_anomalies,

            "total_anomalies":
                drug_anomalies + claim_anomalies,

            "high_risk":
                drug_high + claim_high,

            "affected_providers":
                affected_providers,

            "psi_anomalies":
                drug_psi + claim_psi,

            "robust_z_anomalies":
                drug_robust + claim_robust
        })

    except Exception as e:

        print("SUMMARY ERROR:", repr(e))

        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/drugs/summary")
def drug_summary():
    try:
        return jsonify(get_drug_summary_payload())
    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/drugs/risk-distribution")
def drug_risk_distribution():
    try:
        conn = get_connection(DRUG_VOLUME_DB)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COALESCE(NULLIF(TRIM(volume_risk_level), ''), 'UNKNOWN') AS volume_risk_level,
                COUNT(*) AS drug_count
            FROM pharmacy_drug_volume_risk
            GROUP BY COALESCE(NULLIF(TRIM(volume_risk_level), ''), 'UNKNOWN')
            ORDER BY drug_count DESC
        """)
        rows = rows_to_dict(cursor.fetchall())
        conn.close()

        return jsonify([
            {
                "label": str(row["volume_risk_level"]).upper(),
                "value": int(row["drug_count"] or 0),
            }
            for row in rows
        ])
    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/drugs/top-risk")
def drug_top_risk():
    try:
        conn = get_connection(DRUG_VOLUME_DB)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                Brnd_Name,
                Gnrc_Name,
                volume_risk_score,
                volume_risk_level
            FROM pharmacy_drug_volume_risk
            WHERE volume_risk_score IS NOT NULL
            ORDER BY volume_risk_score DESC
            LIMIT 5
        """)
        rows = rows_to_dict(cursor.fetchall())
        conn.close()

        return jsonify(rows)
    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/drugs/claims-by-drug")
def drug_claims_by_drug():
    try:
        conn = get_connection(DRUG_VOLUME_DB)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                Brnd_Name,
                Gnrc_Name,
                total_claims
            FROM pharmacy_drug_volume_risk
            WHERE Brnd_Name IS NOT NULL
              AND total_claims IS NOT NULL
            ORDER BY total_claims DESC
            LIMIT 10
        """)
        rows = rows_to_dict(cursor.fetchall())
        conn.close()

        return jsonify(rows)
    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/drugs/utilization")
def drug_utilization():
    try:
        conn = get_connection(DRUG_VOLUME_DB)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                Brnd_Name,
                total_claims,
                total_fills,
                total_day_supply
            FROM pharmacy_drug_volume_risk
            WHERE total_claims IS NOT NULL
            ORDER BY total_claims DESC
            LIMIT 10
        """)
        rows = rows_to_dict(cursor.fetchall())
        conn.close()

        return jsonify(rows)
    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/drugs/risk-vs-beneficiaries")
def drug_risk_vs_beneficiaries():
    try:
        conn = get_connection(DRUG_VOLUME_DB)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                Brnd_Name,
                Gnrc_Name,
                total_beneficiaries,
                volume_risk_score,
                total_claims,
                volume_risk_level
            FROM pharmacy_drug_volume_risk
            WHERE total_beneficiaries IS NOT NULL
              AND volume_risk_score IS NOT NULL
        """)
        rows = rows_to_dict(cursor.fetchall())
        conn.close()

        return jsonify(rows)
    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/drugs/overall-trend")
def drug_overall_trend():
    try:
        conn = get_connection(DRUG_VOLUME_DB)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                calendar_year,
                total_claims,
                total_standardized_30_day_fills,
                total_beneficiaries,
                final_volume_risk_score,
                volume_risk_level
            FROM pharmacy_overall_volume_risk
            ORDER BY calendar_year ASC
        """)
        rows = rows_to_dict(cursor.fetchall())
        conn.close()

        return jsonify(rows)
    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/drugs/records")
def drug_records():
    try:
        page = parse_int_arg("page", 1, 1)
        page_size = parse_int_arg("page_size", 25, 1, 200)
        offset = (page - 1) * page_size

        dataset = (
            request.args.get("dataset", "drug-volume")
            .strip()
            .lower()
        )

        if dataset not in {
            "drug-volume",
            "provider-impact",
            "overall-trend",
        }:
            dataset = "drug-volume"

        conn = get_connection(DRUG_VOLUME_DB)
        cursor = conn.cursor()

        risk_levels = []
        years = []

        if dataset == "provider-impact":
            table_name = "pharmacy_npi_volume_risk"
            columns = get_table_columns(cursor, table_name)
            sort_by = safe_order_by(
                request.args.get(
                    "sort_by", "volume_risk_score"
                ).strip(),
                columns,
                "volume_risk_score",
            )
            sort_dir = safe_sort_direction(
                request.args.get("sort_dir", "desc")
            )

            provider_search = request.args.get(
                "provider_search", ""
            ).strip()
            risk_level = request.args.get(
                "risk_level", ""
            ).strip().upper()

            where_clauses = []
            params = []

            if provider_search:
                where_clauses.append("""
                    (
                        Prscrbr_NPI LIKE ?
                        OR Prscrbr_Last_Org_Name LIKE ?
                        OR Prscrbr_First_Name LIKE ?
                    )
                """)
                like_value = f"%{provider_search}%"
                params.extend([
                    like_value,
                    like_value,
                    like_value,
                ])

            if risk_level:
                where_clauses.append(
                    "UPPER(COALESCE(volume_risk_level, '')) = ?"
                )
                params.append(risk_level)

            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)

            cursor.execute(f"""
                SELECT COUNT(*) AS total
                FROM {table_name}
                {where_sql}
            """, params)
            total = int(cursor.fetchone()["total"] or 0)

            cursor.execute(f"""
                SELECT
                    COUNT(*) AS provider_count,
                    COALESCE(SUM(total_claims), 0) AS total_claims,
                    COALESCE(SUM(total_drug_cost), 0) AS total_drug_cost,
                    COALESCE(AVG(volume_risk_score), 0) AS avg_risk_score
                FROM {table_name}
                {where_sql}
            """, params)
            summary_row = dict(cursor.fetchone())

            cursor.execute(f"""
                SELECT *
                FROM {table_name}
                {where_sql}
                ORDER BY {sort_by} {sort_dir}, Prscrbr_NPI ASC
                LIMIT ? OFFSET ?
            """, params + [page_size, offset])
            rows = rows_to_dict(cursor.fetchall())

            cursor.execute("""
                SELECT DISTINCT UPPER(COALESCE(volume_risk_level, ''))
                FROM pharmacy_npi_volume_risk
                WHERE volume_risk_level IS NOT NULL
                  AND TRIM(volume_risk_level) <> ''
                ORDER BY 1
            """)
            risk_levels = [
                row[0]
                for row in cursor.fetchall()
                if row[0]
            ]

            conn.close()

            return jsonify({
                "dataset": dataset,
                "columns": columns,
                "items": rows,
                "pagination": paginate_payload(
                    total,
                    page,
                    page_size,
                ),
                "filters": {
                    "dataset": dataset,
                    "provider_search": provider_search,
                    "risk_level": risk_level,
                    "sort_by": sort_by,
                    "sort_dir": sort_dir.lower(),
                },
                "summary": {
                    "total_records": total,
                    "provider_count": int(summary_row["provider_count"] or 0),
                    "total_claims": int(summary_row["total_claims"] or 0),
                    "total_drug_cost": float(summary_row["total_drug_cost"] or 0),
                    "avg_risk_score": float(summary_row["avg_risk_score"] or 0),
                },
                "filter_options": {
                    "risk_levels": risk_levels,
                    "years": years,
                },
            })

        if dataset == "overall-trend":
            table_name = "pharmacy_overall_volume_risk"
            columns = get_table_columns(cursor, table_name)
            sort_by = safe_order_by(
                request.args.get(
                    "sort_by", "calendar_year"
                ).strip(),
                columns,
                "calendar_year",
            )
            sort_dir = safe_sort_direction(
                request.args.get("sort_dir", "desc")
            )

            calendar_year = request.args.get(
                "calendar_year", ""
            ).strip()

            where_clauses = []
            params = []

            if calendar_year:
                where_clauses.append(
                    "CAST(calendar_year AS TEXT) = ?"
                )
                params.append(calendar_year)

            where_sql = ""
            if where_clauses:
                where_sql = "WHERE " + " AND ".join(where_clauses)

            cursor.execute(f"""
                SELECT COUNT(*) AS total
                FROM {table_name}
                {where_sql}
            """, params)
            total = int(cursor.fetchone()["total"] or 0)

            cursor.execute(f"""
                SELECT
                    COUNT(*) AS total_records,
                    COALESCE(SUM(total_claims), 0) AS total_claims,
                    COALESCE(AVG(final_volume_risk_score), 0) AS avg_risk_score,
                    COALESCE(MAX(calendar_year), 0) AS latest_year
                FROM {table_name}
                {where_sql}
            """, params)
            summary_row = dict(cursor.fetchone())

            cursor.execute(f"""
                SELECT *
                FROM {table_name}
                {where_sql}
                ORDER BY {sort_by} {sort_dir}
                LIMIT ? OFFSET ?
            """, params + [page_size, offset])
            rows = rows_to_dict(cursor.fetchall())

            cursor.execute("""
                SELECT DISTINCT calendar_year
                FROM pharmacy_overall_volume_risk
                WHERE calendar_year IS NOT NULL
                ORDER BY calendar_year DESC
            """)
            years = [
                row["calendar_year"]
                for row in cursor.fetchall()
                if row["calendar_year"] is not None
            ]

            conn.close()

            return jsonify({
                "dataset": dataset,
                "columns": columns,
                "items": rows,
                "pagination": paginate_payload(
                    total,
                    page,
                    page_size,
                ),
                "filters": {
                    "dataset": dataset,
                    "calendar_year": calendar_year,
                    "sort_by": sort_by,
                    "sort_dir": sort_dir.lower(),
                },
                "summary": {
                    "total_records": int(summary_row["total_records"] or 0),
                    "total_claims": int(summary_row["total_claims"] or 0),
                    "avg_risk_score": float(summary_row["avg_risk_score"] or 0),
                    "latest_year": int(summary_row["latest_year"] or 0),
                },
                "filter_options": {
                    "risk_levels": risk_levels,
                    "years": years,
                },
            })

        table_name = "pharmacy_drug_volume_risk"
        columns = get_table_columns(cursor, table_name)
        sort_by = safe_order_by(
            request.args.get(
                "sort_by", "volume_risk_score"
            ).strip(),
            columns,
            "volume_risk_score",
        )
        sort_dir = safe_sort_direction(
            request.args.get("sort_dir", "desc")
        )

        brand_name = request.args.get(
            "brand_name", ""
        ).strip()
        generic_name = request.args.get(
            "generic_name", ""
        ).strip()
        risk_level = request.args.get(
            "risk_level", ""
        ).strip().upper()
        risk_bucket = request.args.get(
            "risk_bucket", ""
        ).strip().lower()

        where_clauses = []
        params = []

        if brand_name:
            where_clauses.append("Brnd_Name LIKE ?")
            params.append(f"%{brand_name}%")

        if generic_name:
            where_clauses.append("Gnrc_Name LIKE ?")
            params.append(f"%{generic_name}%")

        if risk_level:
            where_clauses.append(
                "UPPER(COALESCE(volume_risk_level, '')) = ?"
            )
            params.append(risk_level)

        if risk_bucket == "high_severity":
            where_clauses.append(
                "UPPER(COALESCE(volume_risk_level, '')) IN ('HIGH', 'CRITICAL')"
            )
        elif risk_bucket == "active_alerts":
            where_clauses.append("""
                (
                    UPPER(COALESCE(volume_risk_level, '')) IN ('HIGH', 'CRITICAL')
                    OR COALESCE(high_risk_flag_count, 0) > 0
                )
            """)

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        cursor.execute(f"""
            SELECT COUNT(*) AS total
            FROM {table_name}
            {where_sql}
        """, params)
        total = int(cursor.fetchone()["total"] or 0)

        cursor.execute(f"""
            SELECT
                COUNT(*) AS total_records,
                COUNT(DISTINCT COALESCE(Brnd_Name, Gnrc_Name)) AS unique_drugs,
                COALESCE(SUM(total_claims), 0) AS total_claims,
                COALESCE(SUM(total_drug_cost), 0) AS total_drug_cost,
                COALESCE(AVG(volume_risk_score), 0) AS avg_risk_score
            FROM {table_name}
            {where_sql}
        """, params)
        summary_row = dict(cursor.fetchone())

        cursor.execute(f"""
            SELECT *
            FROM {table_name}
            {where_sql}
            ORDER BY {sort_by} {sort_dir}, Brnd_Name ASC, Gnrc_Name ASC
            LIMIT ? OFFSET ?
        """, params + [page_size, offset])
        rows = rows_to_dict(cursor.fetchall())

        cursor.execute("""
            SELECT DISTINCT UPPER(COALESCE(volume_risk_level, ''))
            FROM pharmacy_drug_volume_risk
            WHERE volume_risk_level IS NOT NULL
              AND TRIM(volume_risk_level) <> ''
            ORDER BY 1
        """)
        risk_levels = [
            row[0]
            for row in cursor.fetchall()
            if row[0]
        ]

        conn.close()

        return jsonify({
            "dataset": dataset,
            "columns": columns,
            "items": rows,
            "pagination": paginate_payload(
                total,
                page,
                page_size,
            ),
            "filters": {
                "dataset": dataset,
                "brand_name": brand_name,
                "generic_name": generic_name,
                "risk_level": risk_level,
                "risk_bucket": risk_bucket,
                "sort_by": sort_by,
                "sort_dir": sort_dir.lower(),
            },
            "summary": {
                "total_records": int(summary_row["total_records"] or 0),
                "unique_drugs": int(summary_row["unique_drugs"] or 0),
                "total_claims": int(summary_row["total_claims"] or 0),
                "total_drug_cost": float(summary_row["total_drug_cost"] or 0),
                "avg_risk_score": float(summary_row["avg_risk_score"] or 0),
            },
            "filter_options": {
                "risk_levels": risk_levels,
                "years": years,
            },
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# SEVERITY DISTRIBUTION
# ============================================================

@app.route("/api/dashboard/severity")
def severity_distribution():

    try:

        conn = get_connection(ANOMALIES_DB)
        cursor = conn.cursor()

        severity = {
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0
        }

        # Drug
        cursor.execute("""
            SELECT
                UPPER(severity) AS severity,
                COUNT(*) AS count
            FROM drug_anomalies
            GROUP BY UPPER(severity)
        """)

        for row in cursor.fetchall():

            if row["severity"] in severity:
                severity[row["severity"]] += row["count"]

        # Claims
        cursor.execute("""
            SELECT
                UPPER(severity) AS severity,
                COUNT(*) AS count
            FROM claims_anomalies
            GROUP BY UPPER(severity)
        """)

        for row in cursor.fetchall():

            if row["severity"] in severity:
                severity[row["severity"]] += row["count"]

        conn.close()

        return jsonify({
            "labels": [
                "HIGH",
                "MEDIUM",
                "LOW"
            ],
            "values": [
                severity["HIGH"],
                severity["MEDIUM"],
                severity["LOW"]
            ]
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# DRUG VS CLAIM
# ============================================================

@app.route("/api/dashboard/anomaly-comparison")
def anomaly_comparison():

    try:

        conn = get_connection(ANOMALIES_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*)
            FROM drug_anomalies
        """)

        drug_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM claims_anomalies
        """)

        claim_count = cursor.fetchone()[0]

        conn.close()

        return jsonify({
            "labels": [
                "Drug Anomalies",
                "Claim Anomalies"
            ],
            "values": [
                drug_count,
                claim_count
            ]
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# TOP RISKY PROVIDERS
# ============================================================

@app.route("/api/dashboard/top-providers")
def top_providers():

    try:

        conn = get_connection(ANOMALIES_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                provider_id,
                COUNT(*) AS anomaly_count
            FROM (

                SELECT provider_id
                FROM drug_anomalies
                WHERE provider_id IS NOT NULL

                UNION ALL

                SELECT provider_id
                FROM claims_anomalies
                WHERE provider_id IS NOT NULL

            )

            GROUP BY provider_id

            ORDER BY anomaly_count DESC

            LIMIT 10
        """)

        results = rows_to_dict(
            cursor.fetchall()
        )

        conn.close()

        return jsonify(results)

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# CLAIM TYPE ANOMALIES
# ============================================================

@app.route("/api/dashboard/claim-types")
def claim_types():

    try:

        conn = get_connection(ANOMALIES_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                claim_type,
                COUNT(*) AS anomaly_count
            FROM claims_anomalies
            WHERE claim_type IS NOT NULL
            GROUP BY claim_type
            ORDER BY anomaly_count DESC
        """)

        results = rows_to_dict(
            cursor.fetchall()
        )

        conn.close()

        return jsonify(results)

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# TOP ANOMALOUS DRUGS
# ============================================================

@app.route("/api/dashboard/drugs")
def top_drugs():

    try:

        conn = get_connection(ANOMALIES_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                drug,
                COUNT(*) AS anomaly_count
            FROM drug_anomalies
            WHERE drug IS NOT NULL
            GROUP BY drug
            ORDER BY anomaly_count DESC
            LIMIT 10
        """)

        results = rows_to_dict(
            cursor.fetchall()
        )

        conn.close()

        return jsonify(results)

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# CLAIM ANOMALY TREND
# ============================================================

@app.route("/api/dashboard/trend")
def anomaly_trend():

    try:

        conn = get_connection(ANOMALIES_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                batch_month,
                COUNT(*) AS anomaly_count
            FROM claims_anomalies
            WHERE batch_month IS NOT NULL
            GROUP BY batch_month
            ORDER BY batch_month
        """)

        results = rows_to_dict(
            cursor.fetchall()
        )

        conn.close()

        return jsonify(results)

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# ROBUST Z VS PSI
# ============================================================

@app.route("/api/dashboard/risk-scatter")
def risk_scatter():

    try:

        conn = get_connection(ANOMALIES_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                provider_id,
                drug AS category,
                robust_z_score,
                psi_score,
                severity,
                'DRUG' AS anomaly_type
            FROM drug_anomalies
            WHERE
                robust_z_score IS NOT NULL
                OR psi_score IS NOT NULL

            UNION ALL

            SELECT
                provider_id,
                claim_type AS category,
                robust_z_score,
                psi_score,
                severity,
                'CLAIM' AS anomaly_type
            FROM claims_anomalies
            WHERE
                robust_z_score IS NOT NULL
                OR psi_score IS NOT NULL

            LIMIT 500
        """)

        results = rows_to_dict(
            cursor.fetchall()
        )

        conn.close()

        return jsonify(results)

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# OPERATIONAL SIGNALS
# ============================================================

@app.route("/api/dashboard/operational-signals")
def operational_signals():

    signals = []

    # ========================================================
    # CLAIMS
    # ========================================================

    try:

        conn = get_connection(CLAIMS_SLA_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                current_period,
                sla_compliance_percentage,
                sla_status,
                total_claim_volume,
                processing_time_minutes,
                provider_count,
                behavior_status,
                records_processed
            FROM claims_sla_behavior
            ORDER BY id DESC
            LIMIT 1
        """)

        row = cursor.fetchone()

        conn.close()

        if row:

            signals.append({

                "type": "Claims",

                "period":
                    row["current_period"],

                "compliance":
                    row["sla_compliance_percentage"],

                "status":
                    row["sla_status"],

                "records":
                    row["total_claim_volume"],

                "processing_time":
                    row["processing_time_minutes"],

                "providers":
                    row["provider_count"],

                "behavior":
                    row["behavior_status"],

                "records_processed":
                    row["records_processed"]

            })

    except Exception as e:

        print(
            "Claims signal error:",
            e
        )

    # ========================================================
    # PHARMACY
    # ========================================================

    try:

        conn = get_connection(PHARMACY_SLA_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                calendar_year,
                sla_compliance_percentage,
                sla_status,
                total_claims,
                processing_time_minutes,
                total_prescribers,
                behavior_status,
                records_processed
            FROM pharmacy_sla_behavior
            ORDER BY id DESC
            LIMIT 1
        """)

        row = cursor.fetchone()

        conn.close()

        if row:

            signals.append({

                "type": "Pharmacy",

                "period":
                    row["calendar_year"],

                "compliance":
                    row["sla_compliance_percentage"],

                "status":
                    row["sla_status"],

                "records":
                    row["total_claims"],

                "processing_time":
                    row["processing_time_minutes"],

                "providers":
                    row["total_prescribers"],

                "behavior":
                    row["behavior_status"],

                "records_processed":
                    row["records_processed"]

            })

    except Exception as e:

        print(
            "Pharmacy signal error:",
            e
        )

    return jsonify(signals)


# ============================================================
# VOLUME RISK
# ============================================================

@app.route("/api/dashboard/volume-risk")
def volume_risk():

    try:

        conn = get_connection(VOLUME_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                NPI,
                current_period,
                current_month_volume,
                baseline_volume,
                deviation_pct,
                volume_risk,
                risk_level,
                root_cause,
                recommendation
            FROM provider_volume_risk
            ORDER BY volume_risk DESC
            LIMIT 20
        """)

        results = rows_to_dict(
            cursor.fetchall()
        )

        conn.close()

        return jsonify(results)

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# DATA QUALITY
# ============================================================

@app.route("/api/dashboard/data-quality")
def data_quality():

    try:

        conn = get_connection(PHARMACY_DQ_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                AVG(quality_score) AS average_quality_score,
                COUNT(*) AS providers,
                SUM(critical_count) AS critical_count,
                SUM(high_count) AS high_count,
                SUM(warning_count) AS warning_count,
                SUM(info_count) AS info_count,
                SUM(total_violations) AS total_violations
            FROM provider_dq_summary
        """)

        row = cursor.fetchone()

        conn.close()

        return jsonify(dict(row))

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# ROOT CAUSES
# ============================================================

@app.route("/api/dashboard/root-causes")
def root_causes():

    causes = []

    # --------------------------------------------------------
    # CLAIM SLA ROOT CAUSES
    # --------------------------------------------------------

    try:

        conn = get_connection(CLAIMS_SLA_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                root_cause,
                COUNT(*) AS count
            FROM claims_sla_behavior
            WHERE root_cause IS NOT NULL
            GROUP BY root_cause
            ORDER BY count DESC
        """)

        for row in cursor.fetchall():

            causes.append({
                "source": "Claims SLA",
                "root_cause": row["root_cause"],
                "count": row["count"]
            })

        conn.close()

    except Exception as e:

        print("Claims root cause error:", e)

    # --------------------------------------------------------
    # PHARMACY ROOT CAUSES
    # --------------------------------------------------------

    try:

        conn = get_connection(PHARMACY_SLA_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                root_cause,
                COUNT(*) AS count
            FROM pharmacy_sla_behavior
            WHERE root_cause IS NOT NULL
            GROUP BY root_cause
            ORDER BY count DESC
        """)

        for row in cursor.fetchall():

            causes.append({
                "source": "Pharmacy SLA",
                "root_cause": row["root_cause"],
                "count": row["count"]
            })

        conn.close()

    except Exception as e:

        print("Pharmacy root cause error:", e)

    # --------------------------------------------------------
    # VOLUME ROOT CAUSES
    # --------------------------------------------------------

    try:

        conn = get_connection(VOLUME_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                root_cause,
                COUNT(*) AS count
            FROM provider_volume_risk
            WHERE root_cause IS NOT NULL
            GROUP BY root_cause
            ORDER BY count DESC
        """)

        for row in cursor.fetchall():

            causes.append({
                "source": "Provider Volume",
                "root_cause": row["root_cause"],
                "count": row["count"]
            })

        conn.close()

    except Exception as e:

        print("Volume root cause error:", e)

    return jsonify(causes)


# ============================================================
# ALERT CENTER
# ============================================================

@app.route("/api/dashboard/alerts")
def alerts():

    alerts = []

    try:

        conn = get_connection(ANOMALIES_DB)
        cursor = conn.cursor()

        # ----------------------------------------------------
        # HIGH DRUG ANOMALIES
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                provider_id,
                drug,
                severity,
                anomaly_reason,
                anomaly_count
            FROM drug_anomalies
            WHERE UPPER(severity) = 'HIGH'
            ORDER BY anomaly_count DESC
            LIMIT 10
        """)

        for row in cursor.fetchall():

            alerts.append({

                "type": "Drug anomaly",

                "provider_id":
                    row["provider_id"],

                "category":
                    row["drug"],

                "severity":
                    "High",

                "reason":
                    row["anomaly_reason"],

                "count":
                    row["anomaly_count"]

            })

        # ----------------------------------------------------
        # HIGH CLAIM ANOMALIES
        # ----------------------------------------------------

        cursor.execute("""
            SELECT
                provider_id,
                claim_type,
                batch_month,
                severity,
                anomaly_reason,
                anomaly_count
            FROM claims_anomalies
            WHERE UPPER(severity) = 'HIGH'
            ORDER BY anomaly_count DESC
            LIMIT 10
        """)

        for row in cursor.fetchall():

            alerts.append({

                "type": "Claim anomaly",

                "provider_id":
                    row["provider_id"],

                "category":
                    row["claim_type"],

                "period":
                    row["batch_month"],

                "severity":
                    "High",

                "reason":
                    row["anomaly_reason"],

                "count":
                    row["anomaly_count"]

            })

        conn.close()

    except Exception as e:

        print(
            "Alert error:",
            e
        )

    return jsonify(alerts)


# ============================================================
# PROVIDER PROFILE
# ============================================================

@app.route("/api/dashboard/provider/<provider_id>")
def provider_profile(provider_id):

    result = {

        "provider_id":
            provider_id,

        "drug_anomalies": [],

        "claim_anomalies": [],

        "volume_risk": None,

        "data_quality": None

    }

    # ========================================================
    # ANOMALIES
    # ========================================================

    try:

        conn = get_connection(ANOMALIES_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                provider_id,
                drug,
                robust_z_score,
                robust_z_anomaly,
                psi_score,
                psi_anomaly,
                anomaly_count,
                severity,
                anomaly_reason
            FROM drug_anomalies
            WHERE provider_id = ?
            ORDER BY anomaly_count DESC
        """, (provider_id,))

        result["drug_anomalies"] = rows_to_dict(
            cursor.fetchall()
        )

        cursor.execute("""
            SELECT
                claim_type,
                provider_id,
                batch_month,
                robust_z_score,
                robust_z_anomaly,
                psi_score,
                psi_anomaly,
                anomaly_count,
                severity,
                anomaly_reason
            FROM claims_anomalies
            WHERE provider_id = ?
            ORDER BY anomaly_count DESC
        """, (provider_id,))

        result["claim_anomalies"] = rows_to_dict(
            cursor.fetchall()
        )

        conn.close()

    except Exception as e:

        print(
            "Provider anomaly error:",
            e
        )

    # ========================================================
    # PROVIDER VOLUME
    # ========================================================

    try:

        conn = get_connection(VOLUME_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM provider_volume_risk
            WHERE NPI = ?
            ORDER BY current_period DESC
            LIMIT 1
        """, (provider_id,))

        row = cursor.fetchone()

        if row:
            result["volume_risk"] = dict(row)

        conn.close()

    except Exception as e:

        print(
            "Provider volume error:",
            e
        )

    # ========================================================
    # PROVIDER DATA QUALITY
    # ========================================================

    try:

        conn = get_connection(PHARMACY_DQ_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM provider_dq_summary
            WHERE npi = ?
            ORDER BY id DESC
            LIMIT 1
        """, (provider_id,))

        row = cursor.fetchone()

        if row:
            result["data_quality"] = dict(row)

        conn.close()

    except Exception as e:

        print(
            "Provider DQ error:",
            e
        )

    return jsonify(result)


# ============================================================
# PROVIDER RISK DISTRIBUTION
# ============================================================

@app.route("/api/dashboard/provider-risk-distribution")
def provider_risk_distribution():

    try:
        module = get_dashboard_module()

        if module == "drugs":
            conn = get_connection(ANOMALIES_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    UPPER(COALESCE(severity, 'UNKNOWN')) AS risk_level,
                    COUNT(*) AS total
                FROM drug_anomalies
                GROUP BY UPPER(COALESCE(severity, 'UNKNOWN'))
            """)

            rows = rows_to_dict(cursor.fetchall())
            conn.close()

            counts = {
                row["risk_level"]: int(row["total"])
                for row in rows
            }

            return jsonify([
                {"label": label, "value": value}
                for label, value in counts.items()
            ])

        source_db = VOLUME_DB if module == "claims" else AUTH_VOLUME_DB
        source_table = (
            "provider_volume_risk"
            if module == "claims"
            else "authorization_provider_volume_risk"
        )

        conn = get_connection(source_db)
        cursor = conn.cursor()

        if module == "authorization":
            cursor.execute(f"""
                WITH latest_provider_snapshot AS (
                    SELECT v.*
                    FROM {source_table} v
                    INNER JOIN (
                        SELECT
                            NPI,
                            MAX(current_period) AS current_period
                        FROM {source_table}
                        WHERE NPI IS NOT NULL
                          AND TRIM(NPI) <> ''
                        GROUP BY NPI
                    ) latest
                        ON latest.NPI = v.NPI
                       AND latest.current_period = v.current_period
                )
                SELECT
                    UPPER(COALESCE(risk_level, 'UNKNOWN')) AS risk_level,
                    COUNT(DISTINCT NPI) AS total
                FROM latest_provider_snapshot
                GROUP BY UPPER(COALESCE(risk_level, 'UNKNOWN'))
            """)
        else:
            cursor.execute(f"""
                SELECT
                    UPPER(COALESCE(risk_level, 'UNKNOWN')) AS risk_level,
                    COUNT(*) AS total
                FROM {source_table}
                GROUP BY UPPER(COALESCE(risk_level, 'UNKNOWN'))
            """)

        rows = rows_to_dict(cursor.fetchall())
        conn.close()

        preferred_order = [
            "CRITICAL",
            "HIGH",
            "MEDIUM",
            "MODERATE",
            "LOW",
            "INSUFFICIENT_HISTORY",
            "LOW_VOLUME",
            "UNKNOWN",
        ]

        counts = {
            row["risk_level"]: int(row["total"])
            for row in rows
        }

        ordered = []

        for label in preferred_order:
            if label in counts:
                ordered.append({
                    "label": label,
                    "value": counts.pop(label),
                })

        for label in sorted(counts.keys()):
            ordered.append({
                "label": label,
                "value": counts[label],
            })

        return jsonify(ordered)

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# CLAIM VOLUME TREND
# ============================================================

@app.route("/api/dashboard/claim-volume-trend")
def claim_volume_trend():

    try:
        module = get_dashboard_module()

        if module == "drugs":
            conn = get_connection(ANOMALIES_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    SUBSTR(COALESCE(run_timestamp, ''), 1, 7) AS period,
                    COUNT(*) AS total_claims,
                    AVG(anomaly_count) AS baseline_claims
                FROM drug_anomalies
                WHERE run_timestamp IS NOT NULL
                  AND TRIM(run_timestamp) <> ''
                GROUP BY SUBSTR(COALESCE(run_timestamp, ''), 1, 7)
                ORDER BY period DESC
                LIMIT 12
            """)

            rows = rows_to_dict(cursor.fetchall())
            conn.close()

            return jsonify([
                {
                    "period": row["period"],
                    "total_claims": int(row["total_claims"] or 0),
                    "baseline_claims": (
                        float(row["baseline_claims"])
                        if row["baseline_claims"] is not None
                        else None
                    ),
                }
                for row in reversed(rows)
            ])

        if module == "authorization":
            conn = get_connection(AUTH_VOLUME_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    period,
                    SUM(COALESCE(monthly_volume, 0)) AS total_claims,
                    AVG(COALESCE(monthly_volume, 0)) AS baseline_claims
                FROM authorization_provider_monthly_volume
                WHERE period IS NOT NULL
                GROUP BY period
                ORDER BY period DESC
                LIMIT 12
            """)

            rows = rows_to_dict(cursor.fetchall())
            conn.close()

            return jsonify([
                {
                    "period": row["period"],
                    "total_claims": int(row["total_claims"] or 0),
                    "baseline_claims": (
                        float(row["baseline_claims"])
                        if row["baseline_claims"] is not None
                        else None
                    ),
                }
                for row in reversed(rows)
            ])

        conn = get_connection(VOLUME_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                claims.period AS period,
                COUNT(*) AS total_claims,
                AVG(history.baseline_volume) AS baseline_claims
            FROM combined_provider_claims claims
            LEFT JOIN provider_volume_rolling_history history
                ON history.NPI = claims.NPI
               AND history.period = claims.period
            WHERE claims.period IS NOT NULL
            GROUP BY claims.period
            ORDER BY claims.period DESC
            LIMIT 12
        """)

        rows = rows_to_dict(cursor.fetchall())
        conn.close()

        result = []

        for row in reversed(rows):
            result.append({
                "period": row["period"],
                "total_claims": int(row["total_claims"] or 0),
                "baseline_claims": (
                    float(row["baseline_claims"])
                    if row["baseline_claims"] is not None
                    else None
                ),
            })

        return jsonify(result)

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# SLA PERFORMANCE TREND
# ============================================================

@app.route("/api/dashboard/authorization-sla-funnel")
def authorization_sla_funnel():
    """Return the authorization SLA workflow stages from auth_sla.db."""
    try:
        conn = get_connection(AUTH_SLA_DB)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) AS total_authorizations,
                SUM(CASE
                    WHEN overall_status IS NULL
                      OR UPPER(TRIM(overall_status)) IN ('N/A', 'NA', 'NOT AVAILABLE', '')
                    THEN 1 ELSE 0
                END) AS pending_na,
                SUM(CASE WHEN UPPER(TRIM(overall_status)) = 'MET' THEN 1 ELSE 0 END) AS sla_met,
                SUM(CASE WHEN UPPER(TRIM(overall_status)) = 'BREACHED' THEN 1 ELSE 0 END) AS sla_breached
            FROM dq_run_output
            WHERE step_name = 'authorization_sla'
        """)
        row = dict(cursor.fetchone())
        conn.close()

        return jsonify({
            "total_authorizations": int(row["total_authorizations"] or 0),
            "pending_na": int(row["pending_na"] or 0),
            "sla_met": int(row["sla_met"] or 0),
            "sla_breached": int(row["sla_breached"] or 0),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/dashboard/authorization-provider-sla-breaches")
def authorization_provider_sla_breaches():
    """Top provider SLA breach rates joined to authorization volume risk."""
    try:
        conn = get_connection(AUTH_SLA_DB)
        cursor = conn.cursor()
        cursor.execute("ATTACH DATABASE ? AS auth_volume", (AUTH_VOLUME_DB,))
        cursor.execute("""
            WITH sla_by_provider AS (
                SELECT
                    CASE
                        WHEN TRIM(npi) LIKE '%.0'
                        THEN SUBSTR(TRIM(npi), 1, LENGTH(TRIM(npi)) - 2)
                        ELSE TRIM(npi)
                    END AS npi,
                    COUNT(*) AS total_authorizations,
                    SUM(CASE
                        WHEN overall_status IS NULL
                          OR UPPER(TRIM(overall_status)) IN ('N/A', 'NA', 'NOT AVAILABLE', '')
                        THEN 1 ELSE 0
                    END) AS pending_na,
                    SUM(CASE WHEN UPPER(TRIM(overall_status)) = 'MET' THEN 1 ELSE 0 END) AS sla_met,
                    SUM(CASE WHEN UPPER(TRIM(overall_status)) = 'BREACHED' THEN 1 ELSE 0 END) AS sla_breached
                FROM dq_run_output
                WHERE step_name = 'authorization_sla'
                  AND npi IS NOT NULL
                  AND TRIM(npi) <> ''
                  AND LENGTH(TRIM(npi)) <= 12
                GROUP BY 1
            ),
            volume_ranked AS (
                SELECT
                    CASE
                        WHEN TRIM(NPI) LIKE '%.0'
                        THEN SUBSTR(TRIM(NPI), 1, LENGTH(TRIM(NPI)) - 2)
                        ELSE TRIM(NPI)
                    END AS npi,
                    current_month_volume,
                    baseline_volume,
                    volume_risk,
                    ROW_NUMBER() OVER (
                        PARTITION BY CASE
                            WHEN TRIM(NPI) LIKE '%.0'
                            THEN SUBSTR(TRIM(NPI), 1, LENGTH(TRIM(NPI)) - 2)
                            ELSE TRIM(NPI)
                        END
                        ORDER BY current_period DESC
                    ) AS row_number
                FROM auth_volume.authorization_provider_volume_risk
            ),
            volume_by_provider AS (
                SELECT npi, current_month_volume, baseline_volume, volume_risk
                FROM volume_ranked
                WHERE row_number = 1
            )
            SELECT
                s.npi,
                s.total_authorizations,
                s.pending_na,
                s.sla_met,
                s.sla_breached,
                ROUND(
                    100.0 * s.sla_breached / NULLIF(s.total_authorizations, 0),
                    1
                ) AS sla_breach_pct,
                v.current_month_volume,
                v.baseline_volume,
                v.volume_risk
            FROM sla_by_provider s
            INNER JOIN volume_by_provider v ON v.npi = s.npi
            WHERE s.total_authorizations > 0
            ORDER BY sla_breach_pct DESC, s.sla_breached DESC, s.total_authorizations DESC
            LIMIT 10
        """)
        rows = rows_to_dict(cursor.fetchall())
        conn.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/dashboard/sla-performance-trend")
def sla_performance_trend():

    try:
        module = get_dashboard_module()

        if module == "drugs":
            conn = get_connection(ANOMALIES_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    SUBSTR(COALESCE(run_timestamp, ''), 1, 7) AS period,
                    COUNT(*) AS total_anomalies,
                    COALESCE(AVG(anomaly_count), 0) AS avg_anomalies,
                    COALESCE(AVG(psi_score), 0) AS psi_avg
                FROM drug_anomalies
                WHERE run_timestamp IS NOT NULL
                  AND TRIM(run_timestamp) <> ''
                GROUP BY SUBSTR(COALESCE(run_timestamp, ''), 1, 7)
                ORDER BY period DESC
                LIMIT 12
            """)

            rows = rows_to_dict(cursor.fetchall())
            conn.close()

            points = []
            for index, row in enumerate(reversed(rows), start=1):
                points.append({
                    "run": index,
                    "period": row["period"] or f"Run {index}",
                    "processing_time": float(row["total_anomalies"] or 0),
                    "sla_limit": float(row["avg_anomalies"] or 0),
                })

            return jsonify({
                "points": points,
                "avg_processing_time": (
                    sum(point["processing_time"] for point in points) / len(points)
                    if points else 0.0
                ),
                "max_processing_time": max(
                    [point["processing_time"] for point in points] or [0.0]
                ),
                "sla_limit": (
                    sum(point["sla_limit"] for point in points) / len(points)
                    if points else 0.0
                ),
            })

        if module == "authorization":
            conn = get_connection(AUTH_SLA_DB)
            cursor = conn.cursor()

            cursor.execute("""
                WITH authorization_sla_points AS (
                    SELECT
                        batch_id,
                        DATE(started_at) AS processing_date,
                        started_at,
                        completed_at,
                        duration_seconds AS turnaround_time,
                        CASE
                            WHEN root_cause LIKE '%72-hour SLA%'
                                 OR message LIKE '%72%'
                            THEN 72.0
                            ELSE NULL
                        END AS sla_limit
                    FROM dq_run_output
                    WHERE step_name = 'authorization_sla'
                      AND duration_seconds IS NOT NULL
                )
                SELECT
                    COALESCE(AVG(turnaround_time), 0) AS avg_processing_time,
                    COALESCE(MAX(turnaround_time), 0) AS max_processing_time,
                    COALESCE(AVG(sla_limit), 72.0) AS sla_limit
                FROM authorization_sla_points
            """)

            summary_row = dict(cursor.fetchone())

            cursor.execute("""
                WITH authorization_sla_points AS (
                    SELECT
                        batch_id,
                        DATE(started_at) AS processing_date,
                        duration_seconds AS turnaround_time,
                        CASE
                            WHEN root_cause LIKE '%72-hour SLA%'
                                 OR message LIKE '%72%'
                            THEN 72.0
                            ELSE NULL
                        END AS sla_limit,
                        overall_status
                    FROM dq_run_output
                    WHERE step_name = 'authorization_sla'
                      AND duration_seconds IS NOT NULL
                )
                SELECT
                    batch_id,
                    processing_date,
                    turnaround_time,
                    COALESCE(sla_limit, 72.0) AS sla_limit,
                    overall_status
                FROM authorization_sla_points
                WHERE processing_date IS NOT NULL
                ORDER BY processing_date DESC, batch_id DESC
                LIMIT 12
            """)

            rows = rows_to_dict(cursor.fetchall())
            conn.close()

            points = []
            for index, row in enumerate(reversed(rows), start=1):
                points.append({
                    "run": index,
                    "period": row["processing_date"] or f"Run {index}",
                    "processing_time": float(row["turnaround_time"] or 0),
                    "sla_limit": float(row["sla_limit"]),
                    "status": row["overall_status"],
                })

            return jsonify({
                "points": points,
                "avg_processing_time": float(
                    summary_row["avg_processing_time"] or 0
                ),
                "max_processing_time": float(
                    summary_row["max_processing_time"] or 0
                ),
                "sla_limit": float(
                    summary_row["sla_limit"] or 72.0
                ),
            })

        conn = get_connection(CLAIMS_SLA_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COALESCE(AVG(processing_time_minutes), 0) AS avg_processing_time,
                COALESCE(MAX(processing_time_minutes), 0) AS max_processing_time,
                COALESCE(AVG(sla_limit_minutes), 60.0) AS sla_limit
            FROM claims_sla_behavior
            WHERE processing_time_minutes IS NOT NULL
        """)

        summary_row = dict(cursor.fetchone())

        cursor.execute("""
            SELECT
                id,
                current_period,
                processing_time_minutes AS processing_time,
                COALESCE(sla_limit_minutes, 60.0) AS sla_limit
            FROM claims_sla_behavior
            WHERE processing_time_minutes IS NOT NULL
            ORDER BY id DESC
            LIMIT 30
        """)

        rows = rows_to_dict(cursor.fetchall())
        conn.close()

        points = []

        for index, row in enumerate(reversed(rows), start=1):
            points.append({
                "run": index,
                "period": row["current_period"] or f"Run {index}",
                "processing_time": float(row["processing_time"]),
                "sla_limit": float(row["sla_limit"]),
            })

        return jsonify({
            "points": points,
            "avg_processing_time": float(
                summary_row["avg_processing_time"] or 0
            ),
            "max_processing_time": float(
                summary_row["max_processing_time"] or 0
            ),
            "sla_limit": float(
                summary_row["sla_limit"] or 60.0
            ),
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# ALERT / ISSUE DISTRIBUTION
# ============================================================

@app.route("/api/dashboard/alert-issue-distribution")
def alert_issue_distribution():

    result = {
        "Critical": 0,
        "High": 0,
        "Warning": 0,
        "Info": 0,
    }

    try:

        conn = get_connection(DAGSTER_DQ_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM dq_run_output
            WHERE UPPER(COALESCE(severity, '')) = 'CRITICAL'
        """)

        row = cursor.fetchone()

        if row:
            result["Critical"] += int(row["total"])

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM dq_run_output
            WHERE UPPER(COALESCE(severity, '')) = 'HIGH'
        """)

        row = cursor.fetchone()

        if row:
            result["High"] += int(row["total"])

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM dq_run_output
            WHERE UPPER(COALESCE(severity, '')) = 'WARNING'
        """)

        row = cursor.fetchone()

        if row:
            result["Warning"] += int(row["total"])

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM dq_run_output
            WHERE UPPER(COALESCE(severity, '')) = 'INFO'
        """)

        row = cursor.fetchone()

        if row:
            result["Info"] += int(row["total"])

        conn.close()

    except Exception as e:
        print("Alert split DQ warning:", e)

    try:

        conn = get_connection(VOLUME_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM provider_volume_risk
            WHERE UPPER(COALESCE(risk_level, '')) IN ('HIGH', 'CRITICAL')
        """)

        row = cursor.fetchone()

        if row:
            result["Critical"] += int(row["total"])

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM provider_volume_risk
            WHERE UPPER(COALESCE(risk_level, '')) = 'HIGH'
        """)

        row = cursor.fetchone()

        if row:
            result["High"] += int(row["total"])

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM provider_volume_risk
            WHERE UPPER(COALESCE(risk_level, '')) = 'LOW'
        """)

        row = cursor.fetchone()

        if row:
            result["Info"] += int(row["total"])

        conn.close()

    except Exception as e:
        print("Alert split provider risk warning:", e)

    try:

        conn = get_connection(CLAIMS_SLA_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM claims_sla_behavior
            WHERE UPPER(COALESCE(behavior_status, '')) LIKE '%ANOMAL%'
        """)

        row = cursor.fetchone()

        if row:
            result["Warning"] += int(row["total"])

        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM claims_sla_behavior
            WHERE UPPER(COALESCE(sla_status, '')) = 'MET'
        """)

        row = cursor.fetchone()

        if row:
            result["Info"] += int(row["total"])

        conn.close()

    except Exception as e:
        print("Alert split SLA warning:", e)

    return jsonify([
        {"label": label, "value": value}
        for label, value in result.items()
    ])


# ============================================================
# PROVIDER RISK RADAR PROFILE
# ============================================================

@app.route("/api/dashboard/provider-risk-profile")
def provider_risk_profile():

    npi = request.args.get("npi", "").strip()
    module = get_dashboard_module()

    try:
        if module == "drugs":

            conn = get_connection(ANOMALIES_DB)
            cursor = conn.cursor()

            if npi:
                cursor.execute("""
                    SELECT provider_id
                    FROM drug_anomalies
                    WHERE provider_id = ?
                    LIMIT 1
                """, (npi,))
                provider_row = cursor.fetchone()
                selected_npi = npi if provider_row else ""
            else:
                cursor.execute("""
                    SELECT provider_id
                    FROM drug_anomalies
                    WHERE provider_id IS NOT NULL
                    GROUP BY provider_id
                    ORDER BY COUNT(*) DESC
                    LIMIT 1
                """)
                provider_row = cursor.fetchone()
                selected_npi = str(provider_row["provider_id"]) if provider_row else ""

            if not selected_npi:
                conn.close()
                return jsonify({
                    "npi": "",
                    "risk_level": "UNKNOWN",
                    "axes": [],
                })

            cursor.execute("""
                SELECT
                    COUNT(*) AS total_rows,
                    COALESCE(AVG(psi_score), 0) AS psi_avg,
                    COALESCE(AVG(robust_z_score), 0) AS robust_avg,
                    COALESCE(SUM(anomaly_count), 0) AS anomaly_total,
                    COALESCE(SUM(CASE WHEN UPPER(COALESCE(severity, '')) = 'HIGH' THEN 1 ELSE 0 END), 0) AS high_count,
                    COUNT(DISTINCT drug) AS unique_drugs
                FROM drug_anomalies
                WHERE provider_id = ?
            """, (selected_npi,))
            metrics = dict(cursor.fetchone())

            cursor.execute("""
                SELECT
                    UPPER(COALESCE(severity, 'UNKNOWN')) AS severity,
                    COUNT(*) AS total
                FROM drug_anomalies
                WHERE provider_id = ?
                GROUP BY UPPER(COALESCE(severity, 'UNKNOWN'))
                ORDER BY total DESC
                LIMIT 1
            """, (selected_npi,))
            severity_row = cursor.fetchone()
            conn.close()

            total_rows = max(1, int(metrics["total_rows"] or 0))

            return jsonify({
                "npi": selected_npi,
                "risk_level": severity_row["severity"] if severity_row else "UNKNOWN",
                "axes": [
                    {"metric": "PSI", "value": min(100.0, float(metrics["psi_avg"] or 0) * 25.0)},
                    {"metric": "Robust Z", "value": min(100.0, float(metrics["robust_avg"] or 0) * 20.0)},
                    {"metric": "Anomalies", "value": min(100.0, float(metrics["anomaly_total"] or 0) / max(total_rows, 1) * 50.0)},
                    {"metric": "High Sev", "value": min(100.0, (float(metrics["high_count"] or 0) / total_rows) * 100.0)},
                    {"metric": "Drugs", "value": min(100.0, float(metrics["unique_drugs"] or 0) / 5.0)},
                ],
            })

        if module == "authorization":

            conn = get_connection(AUTH_VOLUME_DB)
            cursor = conn.cursor()

            if npi:
                cursor.execute("""
                    SELECT *
                    FROM authorization_provider_volume_risk
                    WHERE NPI = ?
                    ORDER BY current_period DESC
                    LIMIT 1
                """, (npi,))
            else:
                cursor.execute("""
                    SELECT *
                    FROM authorization_provider_volume_risk
                    ORDER BY COALESCE(volume_risk, -1) DESC, total_authorization_volume DESC
                    LIMIT 1
                """)

            provider_row = cursor.fetchone()
            conn.close()

            if provider_row is None:
                return jsonify({
                    "npi": npi or "",
                    "axes": [],
                    "risk_level": "UNKNOWN",
                })

            selected_npi = str(provider_row["NPI"])
            volume_score = min(
                100.0,
                max(0.0, float(provider_row["volume_risk"] or 0) * 100.0),
            )

            conn = get_connection(AUTH_DAGSTER_DB)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COALESCE(AVG(quality_score), 0) AS quality_score,
                    COALESCE(SUM(critical_count), 0) AS critical_count,
                    COALESCE(SUM(total_violations), 0) AS violations
                FROM dq_run_output
                WHERE npi = ?
            """, (selected_npi,))
            dq_row = dict(cursor.fetchone())
            conn.close()

            conn = get_connection(AUTH_SLA_DB)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COUNT(*) AS total,
                    SUM(
                        CASE
                            WHEN UPPER(COALESCE(overall_status, '')) != 'BREACHED'
                            THEN 1 ELSE 0
                        END
                    ) AS met
                FROM dq_run_output
                WHERE npi = ?
            """, (selected_npi,))
            sla_row = dict(cursor.fetchone())
            conn.close()

            total_sla = float(sla_row["total"] or 0)
            sla_score = (
                ((float(sla_row["met"] or 0) / total_sla) * 100.0)
                if total_sla > 0 else 0.0
            )

            return jsonify({
                "npi": selected_npi,
                "risk_level": provider_row["risk_level"],
                "axes": [
                    {"metric": "Volume", "value": round(volume_score, 1)},
                    {"metric": "DQ", "value": round(min(100.0, float(dq_row["quality_score"] or 0)), 1)},
                    {"metric": "SLA", "value": round(sla_score, 1)},
                    {"metric": "Critical", "value": round(min(100.0, float(dq_row["critical_count"] or 0) * 10.0), 1)},
                    {"metric": "Violations", "value": round(min(100.0, float(dq_row["violations"] or 0) * 5.0), 1)},
                ],
            })

        conn = get_connection(VOLUME_DB)
        cursor = conn.cursor()

        if npi:
            cursor.execute("""
                SELECT *
                FROM provider_volume_risk
                WHERE NPI = ?
                ORDER BY current_period DESC
                LIMIT 1
            """, (npi,))
        else:
            cursor.execute("""
                SELECT *
                FROM provider_volume_risk
                ORDER BY volume_risk DESC
                LIMIT 1
            """)

        provider_row = cursor.fetchone()
        conn.close()

        if provider_row is None:
            return jsonify({
                "npi": npi or "",
                "axes": [
                    {"metric": "Volume", "value": 0.0},
                    {"metric": "Behavior", "value": 0.0},
                    {"metric": "DQ", "value": 0.0},
                    {"metric": "SLA", "value": 0.0},
                    {"metric": "Claims", "value": 0.0},
                ]
            })

        selected_npi = str(provider_row["NPI"])

        volume_score = min(
            100.0,
            max(0.0, float(provider_row["volume_risk"] or 0) * 100.0)
        )

        conn = get_connection(ANOMALIES_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COALESCE(SUM(anomaly_count), 0) AS total
            FROM claims_anomalies
            WHERE provider_id = ?
        """, (selected_npi,))

        claim_anomaly_total = int(cursor.fetchone()["total"])

        cursor.execute("""
            SELECT MAX(total_count) AS max_total
            FROM (
                SELECT COALESCE(SUM(anomaly_count), 0) AS total_count
                FROM claims_anomalies
                WHERE provider_id IS NOT NULL
                GROUP BY provider_id
            ) x
        """)

        max_claim_anomaly_total = int(cursor.fetchone()["max_total"] or 0)

        conn.close()

        claims_score = 0.0

        if max_claim_anomaly_total > 0:
            claims_score = min(
                100.0,
                (claim_anomaly_total / max_claim_anomaly_total) * 100.0
            )

        conn = get_connection(PHARMACY_DQ_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT quality_score
            FROM provider_dq_summary
            WHERE npi = ?
            ORDER BY id DESC
            LIMIT 1
        """, (selected_npi,))

        dq_row = cursor.fetchone()
        conn.close()

        dq_score = 0.0

        if dq_row and dq_row["quality_score"] is not None:
            dq_score = min(
                100.0,
                max(0.0, float(dq_row["quality_score"]))
            )

        conn = get_connection(CLAIMS_SLA_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COALESCE(AVG(sla_compliance_percentage), 0) AS avg_sla
            FROM claims_sla_behavior
        """)

        sla_score = float(cursor.fetchone()["avg_sla"] or 0)

        cursor.execute("""
            SELECT
                COALESCE(AVG(total_claim_volume), 0) AS avg_volume,
                COALESCE(MAX(total_claim_volume), 0) AS max_volume
            FROM claims_sla_behavior
        """)

        claim_volume_row = cursor.fetchone()
        conn.close()

        avg_volume = float(claim_volume_row["avg_volume"] or 0)
        max_volume = float(claim_volume_row["max_volume"] or 0)

        behavior_score = 0.0

        if max_volume > 0:
            behavior_score = min(
                100.0,
                max(0.0, (avg_volume / max_volume) * 100.0)
            )

        # The profile trend is scoped to the selected provider.  Claims
        # anomaly history is the only period-level risk data available for
        # this NPI, so use its most recent 12 recorded periods.
        conn = get_connection(ANOMALIES_DB)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                batch_month AS period,
                COALESCE(SUM(anomaly_count), 0) AS anomaly_total
            FROM claims_anomalies
            WHERE provider_id = ?
              AND batch_month IS NOT NULL
            GROUP BY batch_month
            ORDER BY batch_month DESC
            LIMIT 12
        """, (selected_npi,))
        trend_rows = list(reversed(cursor.fetchall()))
        conn.close()

        max_trend_anomalies = max(
            [float(row["anomaly_total"] or 0) for row in trend_rows] or [1.0]
        )
        risk_trend = [
            {
                "period": row["period"],
                "value": round(
                    min(
                        100.0,
                        (float(row["anomaly_total"] or 0) /
                         max_trend_anomalies) * 100.0
                    ),
                    1,
                ),
            }
            for row in trend_rows
        ]

        return jsonify({
            "npi": selected_npi,
            "risk_level": provider_row["risk_level"],
            "overall_risk_score": round(volume_score, 1),
            "axes": [
                {"metric": "Volume", "value": round(volume_score, 1)},
                {"metric": "Behavior", "value": round(behavior_score, 1)},
                {"metric": "DQ", "value": round(dq_score, 1)},
                {"metric": "SLA", "value": round(sla_score, 1)},
                {"metric": "Claims", "value": round(claims_score, 1)},
            ],
            "risk_trend": risk_trend,
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


# ============================================================
# PROVIDER OPTIONS
# ============================================================

@app.route("/api/dashboard/provider-options")
def provider_options():

    try:
        module = get_dashboard_module()

        if module == "drugs":
            conn = get_connection(ANOMALIES_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT DISTINCT provider_id
                FROM drug_anomalies
                WHERE provider_id IS NOT NULL
                ORDER BY provider_id
                LIMIT 500
            """)

            rows = cursor.fetchall()
            conn.close()

            return jsonify([
                {"npi": str(row["provider_id"])}
                for row in rows
            ])

        if module == "authorization":
            conn = get_connection(AUTH_VOLUME_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT DISTINCT NPI
                FROM authorization_provider_volume_risk
                WHERE NPI IS NOT NULL
                ORDER BY NPI
                LIMIT 500
            """)

            rows = cursor.fetchall()
            conn.close()

            return jsonify([
                {"npi": str(row["NPI"])}
                for row in rows
            ])

        conn = get_connection(VOLUME_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT DISTINCT NPI
            FROM provider_volume_risk
            WHERE NPI IS NOT NULL
            ORDER BY NPI
            LIMIT 500
        """)

        rows = cursor.fetchall()
        conn.close()

        return jsonify([
            {"npi": str(row["NPI"])}
            for row in rows
        ])

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/dashboard/data")
def claim_sentinel_data():

    dataset = request.args.get("dataset", "carrier").strip()

    if dataset not in CLAIM_SENTINEL_DATASETS:
        return jsonify({
            "error": "Unsupported claim_sentinel dataset"
        }), 400

    try:
        page = parse_int_arg("page", 1, 1)
        page_size = parse_int_arg("page_size", 50, 1, 100)
        offset = (page - 1) * page_size

        conn = get_connection(CLAIM_SENTINEL_DB)
        cursor = conn.cursor()
        columns = get_table_columns(cursor, dataset)

        cursor.execute(
            f'SELECT COUNT(*) AS total FROM "{dataset}"'
        )
        total = int(cursor.fetchone()["total"] or 0)

        cursor.execute(
            f'SELECT * FROM "{dataset}" LIMIT ? OFFSET ?',
            [page_size, offset],
        )
        rows = rows_to_dict(cursor.fetchall())
        conn.close()

        return jsonify({
            "dataset": dataset,
            "columns": columns,
            "items": rows,
            "pagination": paginate_payload(
                total, page, page_size
            ),
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/dashboard/claims")
def claims_listing():

    try:

        page = parse_int_arg("page", 1, 1)
        page_size = parse_int_arg("page_size", 25, 1, 200)
        offset = (page - 1) * page_size

        claim_id = request.args.get("claim_id", "").strip()
        npi = request.args.get("npi", "").strip()
        source = request.args.get("source", "").strip()
        period = request.args.get("period", "").strip()
        date_from = request.args.get("date_from", "").strip()
        date_to = request.args.get("date_to", "").strip()

        conn = get_connection(VOLUME_DB)
        cursor = conn.cursor()

        columns = get_table_columns(cursor, "combined_provider_claims")
        sort_by = safe_order_by(
            request.args.get("sort_by", "DT").strip(),
            columns,
            "DT",
        )
        sort_dir = safe_sort_direction(
            request.args.get("sort_dir", "desc")
        )

        where_clauses = []
        params = []

        if claim_id:
            where_clauses.append("CLM_ID LIKE ?")
            params.append(f"%{claim_id}%")

        if npi:
            where_clauses.append("NPI LIKE ?")
            params.append(f"%{npi}%")

        if source:
            where_clauses.append("source = ?")
            params.append(source)

        if period:
            where_clauses.append("period = ?")
            params.append(period)

        if date_from:
            where_clauses.append("DATE(DT) >= DATE(?)")
            params.append(date_from)

        if date_to:
            where_clauses.append("DATE(DT) <= DATE(?)")
            params.append(date_to)

        where_sql = ""

        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        count_sql = f"""
            SELECT COUNT(*) AS total
            FROM combined_provider_claims
            {where_sql}
        """

        cursor.execute(count_sql, params)
        total = int(cursor.fetchone()["total"])

        query_sql = f"""
            SELECT *
            FROM combined_provider_claims
            {where_sql}
            ORDER BY {sort_by} {sort_dir}, CLM_ID ASC
            LIMIT ? OFFSET ?
        """

        cursor.execute(
            query_sql,
            params + [page_size, offset]
        )

        rows = rows_to_dict(cursor.fetchall())

        cursor.execute("""
            SELECT DISTINCT source
            FROM combined_provider_claims
            WHERE source IS NOT NULL AND TRIM(source) <> ''
            ORDER BY source
        """)

        sources = [
            row["source"]
            for row in cursor.fetchall()
        ]

        cursor.execute("""
            SELECT DISTINCT period
            FROM combined_provider_claims
            WHERE period IS NOT NULL AND TRIM(period) <> ''
            ORDER BY period DESC
        """)

        periods = [
            row["period"]
            for row in cursor.fetchall()
        ]

        conn.close()

        return jsonify({
            "columns": columns,
            "items": rows,
            "pagination": paginate_payload(
                total,
                page,
                page_size,
            ),
            "filters": {
                "claim_id": claim_id,
                "npi": npi,
                "source": source,
                "period": period,
                "date_from": date_from,
                "date_to": date_to,
                "sort_by": sort_by,
                "sort_dir": sort_dir.lower(),
            },
            "filter_options": {
                "sources": sources,
                "periods": periods,
            },
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/dashboard/claims/<claim_id>")
def claim_detail(claim_id):

    try:

        conn = get_connection(VOLUME_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM combined_provider_claims
            WHERE CLM_ID = ?
            LIMIT 1
        """, (claim_id,))

        claim_row = cursor.fetchone()

        if claim_row is None:
            conn.close()
            return jsonify({
                "error": "Claim not found"
            }), 404

        claim = dict(claim_row)
        provider_risk = None
        npi = str(claim.get("NPI") or "").strip()

        if npi:
            cursor.execute("""
                SELECT *
                FROM provider_volume_risk
                WHERE NPI = ?
                ORDER BY current_period DESC
                LIMIT 1
            """, (npi,))

            risk_row = cursor.fetchone()

            if risk_row:
                provider_risk = dict(risk_row)

        conn.close()

        quality_context = None

        if npi:
            conn = get_connection(DAGSTER_DQ_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT *
                FROM dq_run_output
                WHERE npi = ?
                ORDER BY COALESCE(created_at, completed_at, started_at) DESC, id DESC
                LIMIT 1
            """, (npi,))

            dq_row = cursor.fetchone()
            conn.close()

            if dq_row:
                dq_dict = dict(dq_row)
                quality_context = {
                    key: value
                    for key, value in dq_dict.items()
                    if value not in (None, "")
                }

        return jsonify({
            "claim": claim,
            "provider_risk": provider_risk,
            "quality_context": quality_context,
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/dashboard/providers")
def providers_listing():

    try:

        page = parse_int_arg("page", 1, 1)
        page_size = parse_int_arg("page_size", 25, 1, 200)
        offset = (page - 1) * page_size

        npi = request.args.get("npi", "").strip()
        risk_level = request.args.get("risk_level", "").strip().upper()
        source = request.args.get("source", "").strip()

        conn = get_connection(VOLUME_DB)
        cursor = conn.cursor()

        columns = get_table_columns(cursor, "provider_volume_risk")
        sort_by = safe_order_by(
            request.args.get("sort_by", "volume_risk").strip(),
            columns,
            "volume_risk",
        )
        sort_dir = safe_sort_direction(
            request.args.get("sort_dir", "desc")
        )

        where_clauses = []
        params = []

        if npi:
            where_clauses.append("NPI LIKE ?")
            params.append(f"%{npi}%")

        if risk_level:
            where_clauses.append(
                "UPPER(COALESCE(risk_level, '')) = ?"
            )
            params.append(risk_level)

        if source:
            where_clauses.append(
                "LOWER(COALESCE(sources, '')) LIKE ?"
            )
            params.append(f"%{source.lower()}%")

        where_sql = ""

        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        cursor.execute(f"""
            SELECT COUNT(*) AS total
            FROM provider_volume_risk
            {where_sql}
        """, params)
        total = int(cursor.fetchone()["total"])

        cursor.execute(f"""
            SELECT
                COALESCE(SUM(total_claim_volume), 0) AS total_claims,
                COALESCE(AVG(current_month_volume), 0) AS avg_monthly_volume,
                COALESCE(AVG(deviation_pct), 0) AS avg_deviation
            FROM provider_volume_risk
            {where_sql}
        """, params)
        summary_row = dict(cursor.fetchone())

        cursor.execute(f"""
            SELECT *
            FROM provider_volume_risk
            {where_sql}
            ORDER BY {sort_by} {sort_dir}, NPI ASC
            LIMIT ? OFFSET ?
        """, params + [page_size, offset])
        rows = rows_to_dict(cursor.fetchall())

        cursor.execute("""
            SELECT DISTINCT UPPER(COALESCE(risk_level, ''))
            FROM provider_volume_risk
            WHERE risk_level IS NOT NULL AND TRIM(risk_level) <> ''
            ORDER BY 1
        """)
        risk_levels = [
            row[0]
            for row in cursor.fetchall()
            if row[0]
        ]

        cursor.execute("""
            SELECT DISTINCT source
            FROM combined_provider_claims
            WHERE source IS NOT NULL AND TRIM(source) <> ''
            ORDER BY source
        """)
        sources = [
            row["source"]
            for row in cursor.fetchall()
        ]

        conn.close()

        return jsonify({
            "columns": columns,
            "items": rows,
            "pagination": paginate_payload(
                total,
                page,
                page_size,
            ),
            "filters": {
                "npi": npi,
                "risk_level": risk_level,
                "source": source,
                "sort_by": sort_by,
                "sort_dir": sort_dir.lower(),
            },
            "summary": {
                "provider_count": total,
                "total_claims": int(summary_row["total_claims"] or 0),
                "avg_monthly_volume": float(summary_row["avg_monthly_volume"] or 0),
                "avg_deviation": float(summary_row["avg_deviation"] or 0),
            },
            "filter_options": {
                "risk_levels": risk_levels,
                "sources": sources,
            },
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/dashboard/providers/<npi>")
def provider_detail(npi):

    try:

        conn = get_connection(VOLUME_DB)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM provider_volume_risk
            WHERE NPI = ?
            ORDER BY current_period DESC
            LIMIT 1
        """, (npi,))

        provider_row = cursor.fetchone()

        if provider_row is None:
            conn.close()
            return jsonify({
                "error": "Provider not found"
            }), 404

        cursor.execute("""
            SELECT *
            FROM provider_volume_rolling_history
            WHERE NPI = ?
            ORDER BY period
        """, (npi,))
        history = rows_to_dict(cursor.fetchall())

        cursor.execute("""
            SELECT *
            FROM combined_provider_claims
            WHERE NPI = ?
            ORDER BY DT DESC, CLM_ID ASC
        """, (npi,))
        claims = rows_to_dict(cursor.fetchall())
        conn.close()

        quality_context = None

        conn = get_connection(DAGSTER_DQ_DB)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT *
            FROM dq_run_output
            WHERE npi = ?
            ORDER BY COALESCE(created_at, completed_at, started_at) DESC, id DESC
            LIMIT 1
        """, (npi,))
        dq_row = cursor.fetchone()
        conn.close()

        if dq_row:
            quality_context = {
                key: value
                for key, value in dict(dq_row).items()
                if value not in (None, "")
            }

        return jsonify({
            "provider": dict(provider_row),
            "history": history,
            "claims": claims,
            "quality_context": quality_context,
        })

    except Exception as e:

        return jsonify({
            "error": str(e)
        }), 500


@app.route("/api/dashboard/alerts/drilldown")
def alert_drilldown():

    level = request.args.get("level", "").strip().upper()

    if level not in {"CRITICAL", "HIGH", "WARNING", "INFO"}:
        return jsonify({
            "error": "level must be one of CRITICAL, HIGH, WARNING, INFO"
        }), 400

    result = {
        "level": level,
        "data_quality": [],
        "provider_risk": [],
        "sla_behavior": [],
    }

    try:
        module = get_dashboard_module()

        if module == "drugs":
            conn = get_connection(ANOMALIES_DB)
            cursor = conn.cursor()

            for label in ["CRITICAL", "HIGH", "WARNING", "INFO", "LOW"]:
                cursor.execute("""
                    SELECT COUNT(*) AS total
                    FROM drug_anomalies
                    WHERE UPPER(COALESCE(severity, '')) = ?
                """, (label,))
                row = cursor.fetchone()
                if row:
                    mapped = (
                        "Critical" if label == "CRITICAL"
                        else "High" if label == "HIGH"
                        else "Warning" if label == "WARNING"
                        else "Info"
                    )
                    result[mapped] += int(row["total"] or 0)

            conn.close()

            return jsonify([
                {"label": label, "value": value}
                for label, value in result.items()
            ])

        if module == "authorization":
            conn = get_connection(AUTH_DAGSTER_DB)
            cursor = conn.cursor()

            for label in ["CRITICAL", "HIGH", "WARNING", "INFO"]:
                cursor.execute("""
                    SELECT COUNT(*) AS total
                    FROM dq_run_output
                    WHERE UPPER(COALESCE(severity, '')) = ?
                """, (label,))
                row = cursor.fetchone()
                if row:
                    result[label.title()] += int(row["total"] or 0)

            conn.close()

            conn = get_connection(AUTH_VOLUME_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM authorization_provider_volume_risk
                WHERE UPPER(COALESCE(risk_level, '')) = 'CRITICAL'
            """)
            result["Critical"] += int(cursor.fetchone()["total"] or 0)

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM authorization_provider_volume_risk
                WHERE UPPER(COALESCE(risk_level, '')) = 'HIGH'
            """)
            result["High"] += int(cursor.fetchone()["total"] or 0)
            conn.close()

            conn = get_connection(AUTH_SLA_DB)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(*) AS total
                FROM dq_run_output
                WHERE UPPER(COALESCE(overall_status, '')) = 'BREACHED'
            """)
            result["Critical"] += int(cursor.fetchone()["total"] or 0)
            conn.close()

            return jsonify([
                {"label": label, "value": value}
                for label, value in result.items()
            ])

        conn = get_connection(DAGSTER_DQ_DB)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT *
            FROM dq_run_output
            WHERE UPPER(COALESCE(severity, '')) = ?
            ORDER BY COALESCE(created_at, completed_at, started_at) DESC, id DESC
            LIMIT 200
        """, (level,))
        result["data_quality"] = rows_to_dict(cursor.fetchall())
        conn.close()
    except Exception as e:
        print("Alert drilldown DQ warning:", e)

    try:
        conn = get_connection(VOLUME_DB)
        cursor = conn.cursor()

        provider_level = None

        if level == "CRITICAL":
            provider_level = "CRITICAL"
        elif level == "HIGH":
            provider_level = "HIGH"
        elif level == "INFO":
            provider_level = "LOW"

        if provider_level:
            cursor.execute("""
                SELECT *
                FROM provider_volume_risk
                WHERE UPPER(COALESCE(risk_level, '')) = ?
                ORDER BY volume_risk DESC, NPI ASC
                LIMIT 200
            """, (provider_level,))
            result["provider_risk"] = rows_to_dict(cursor.fetchall())

        conn.close()
    except Exception as e:
        print("Alert drilldown provider warning:", e)

    try:
        conn = get_connection(CLAIMS_SLA_DB)
        cursor = conn.cursor()

        if level == "WARNING":
            cursor.execute("""
                SELECT *
                FROM claims_sla_behavior
                WHERE UPPER(COALESCE(behavior_status, '')) LIKE '%ANOMAL%'
                ORDER BY COALESCE(created_at, processing_end_at, processing_start_at) DESC, id DESC
                LIMIT 200
            """)
        elif level == "HIGH":
            cursor.execute("""
                SELECT *
                FROM claims_sla_behavior
                WHERE UPPER(COALESCE(sla_status, '')) = 'BREACHED'
                   OR COALESCE(sla_breached_count, 0) > 0
                ORDER BY COALESCE(created_at, processing_end_at, processing_start_at) DESC, id DESC
                LIMIT 200
            """)
        elif level == "INFO":
            cursor.execute("""
                SELECT *
                FROM claims_sla_behavior
                WHERE UPPER(COALESCE(sla_status, '')) = 'MET'
                   OR UPPER(COALESCE(behavior_status, '')) = 'NORMAL'
                ORDER BY COALESCE(created_at, processing_end_at, processing_start_at) DESC, id DESC
                LIMIT 200
            """)
        else:
            cursor.execute("""
                SELECT *
                FROM claims_sla_behavior
                WHERE 1 = 0
            """)

        result["sla_behavior"] = rows_to_dict(cursor.fetchall())
        conn.close()
    except Exception as e:
        print("Alert drilldown SLA warning:", e)

    return jsonify(result)


# ============================================================
# RUN SERVER
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 70)
    print("CLAIMCARE - SQLITE BACKEND")
    print("=" * 70)

    print()
    print("Base directory:")
    print(BASE_DIR)

    print()
    print("Anomaly database:")
    print(ANOMALIES_DB)

    print()
    print("Required anomaly tables:")
    print("  - drug_anomalies")
    print("  - claims_anomalies")

    print()
    print("API:")
    print("  http://localhost:5000")

    print("=" * 70)
    print()

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )
