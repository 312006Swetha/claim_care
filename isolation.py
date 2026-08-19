"""Run DME isolation analysis locally with optional OpenRouter enrichment."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from urllib import request

import joblib
import numpy as np
import pandas as pd

FEATURES = [
    "batch_volume", "avg_lag_days", "max_lag_days", "avg_submitted_amt",
    "allowed_submitted_ratio", "missing_hcpcs_ratio",
]
INPUT_COLUMNS = [
    "CLM_ID", "CLM_FROM_DT", "NCH_WKLY_PROC_DT", "LINE_SBMTD_CHRG_AMT",
    "LINE_ALOWD_CHRG_AMT", "HCPCS_CD",
]
MODEL_FEATURES = FEATURES


def args() -> argparse.Namespace:
    root = Path(__file__).resolve().parent
    candidates = [root / "dme (2).csv", root / "dme.csv"]
    default_input = next((path for path in candidates if path.exists()), candidates[0])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=default_input)
    parser.add_argument("--model", type=Path, default=root / "claims_isolation_forest.joblib")
    parser.add_argument("--output", type=Path, default=root / "claims_batch_anomaly_results.csv")
    parser.add_argument("--database", type=Path, default=root / "claim_sentinel.db")
    return parser.parse_args()


def build_features(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"DME CSV not found: {path}")
    frame = pd.read_csv(path, usecols=INPUT_COLUMNS)
    frame["CLM_FROM_DT"] = pd.to_datetime(frame["CLM_FROM_DT"], errors="coerce")
    frame["NCH_WKLY_PROC_DT"] = pd.to_datetime(frame["NCH_WKLY_PROC_DT"], errors="coerce")
    for column in ("LINE_SBMTD_CHRG_AMT", "LINE_ALOWD_CHRG_AMT"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["lag_days"] = (frame["NCH_WKLY_PROC_DT"] - frame["CLM_FROM_DT"]).dt.days
    frame.loc[frame["lag_days"] < 0, "lag_days"] = np.nan
    batches = frame.groupby("NCH_WKLY_PROC_DT").agg(
        batch_volume=("CLM_ID", "count"),
        avg_lag_days=("lag_days", "mean"),
        max_lag_days=("lag_days", "max"),
        avg_submitted_amt=("LINE_SBMTD_CHRG_AMT", "mean"),
        avg_allowed_amt=("LINE_ALOWD_CHRG_AMT", "mean"),
        missing_hcpcs_ratio=("HCPCS_CD", lambda values: values.isna().mean()),
    ).reset_index()
    batches["allowed_submitted_ratio"] = batches["avg_allowed_amt"] / batches["avg_submitted_amt"].replace(0, np.nan)
    for column in FEATURES:
        batches[column] = pd.to_numeric(batches[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        batches[column] = batches[column].fillna(batches[column].median()).fillna(0)
    return batches


def fallback(row: pd.Series, message: str) -> str:
    return json.dumps({
        "anomaly_status": str(row["status"]),
        "anomaly_score": float(row["anomaly_score"]),
        "primary_cause": "Isolation Forest anomaly",
        "impact": "Requires operational review",
        "root_cause_interpretation": message,
        "recommended_action": "Review the batch metrics and source claims manually.",
        "analyst_summary": message,
    })


def parse_json_response(content: str | None) -> str:
    if not content:
        raise ValueError("OpenRouter returned an empty response")
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.dumps(json.loads(cleaned))
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.dumps(json.loads(cleaned[start:end + 1]))


def openrouter_analysis(row: pd.Series, api_key: str) -> str:
    payload = {
        "model": os.environ.get("OPENROUTER_MODEL", "openrouter/free"),
        "messages": [{
            "role": "user",
            "content": (
                "Return JSON with anomaly_status, anomaly_score, primary_cause, impact, "
                "root_cause_interpretation, recommended_action, analyst_summary. "
                "Do not call an anomaly fraud. Data: "
                + json.dumps({column: float(row[column]) for column in FEATURES})
                + f"; status={row['status']}; score={float(row['anomaly_score'])}"
            ),
        }],
        "temperature": 0.1,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
    }
    api_request = request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(api_request, timeout=60) as response:
        result = json.loads(response.read().decode())
    content = result["choices"][0]["message"]["content"]
    return parse_json_response(content)


def main() -> None:
    options = args()
    if not options.model.exists():
        raise FileNotFoundError(f"Model file not found: {options.model}")
    print(f"Loading claims: {options.input}")
    batches = build_features(options.input)
    model = joblib.load(options.model)
    expected = list(getattr(model, "feature_names_in_", MODEL_FEATURES))
    if expected != MODEL_FEATURES:
        raise ValueError(f"Model features {expected} do not match {MODEL_FEATURES}")
    batches["anomaly_prediction"] = model.predict(batches[FEATURES])
    batches["anomaly_score"] = model.decision_function(batches[FEATURES])
    batches["is_anomaly"] = batches["anomaly_prediction"] == -1
    batches["status"] = np.where(batches["is_anomaly"], "CRITICAL ANOMALY", "HEALTHY")
    batches["openrouter_status"] = "NOT_REQUESTED"
    batches["openrouter_model"] = os.environ.get("OPENROUTER_MODEL", "openrouter/free")
    batches["openrouter_structured_output"] = None
    api_key = os.environ.get("OPENROUTER_API_KEY")
    for index in batches.index[batches["is_anomaly"]]:
        row = batches.loc[index]
        if not api_key:
            batches.at[index, "openrouter_status"] = "SKIPPED_NO_API_KEY"
            batches.at[index, "openrouter_structured_output"] = fallback(row, "OpenRouter API key is not configured.")
            continue
        try:
            batches.at[index, "openrouter_status"] = "SUCCESS"
            batches.at[index, "openrouter_structured_output"] = openrouter_analysis(row, api_key)
        except Exception as error:
            batches.at[index, "openrouter_status"] = "FAILED"
            batches.at[index, "openrouter_structured_output"] = fallback(row, f"OpenRouter request failed: {error}")
            print(f"OpenRouter failed for batch {index}: {error}")
    options.output.parent.mkdir(parents=True, exist_ok=True)
    batches.to_csv(options.output, index=False)
    options.database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(options.database) as connection:
        batches.to_sql("dme_batch_anomalies", connection, if_exists="replace", index=False)
    populated = int(batches["openrouter_structured_output"].notna().sum())
    print(f"Processed batches: {len(batches):,}")
    print(f"Anomalous batches: {int(batches['is_anomaly'].sum()):,}")
    print(f"OpenRouter records: {populated:,}")
    print(f"Results CSV: {options.output}")
    print(f"Results database: {options.database}")


if __name__ == "__main__":
    main()
