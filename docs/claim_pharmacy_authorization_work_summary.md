# Claim, Pharmacy, and Authorization Work Summary

## Project Overview

This project builds an end-to-end healthcare operations monitoring platform around three domains:

- Claims
- Pharmacy
- Authorization

The overall goal was to turn raw payer datasets into operational intelligence by building pipelines for:

- data ingestion and batch preparation
- data quality validation
- volume risk detection
- SLA and behavior monitoring
- anomaly detection
- root cause and recommendation generation
- API and dashboard integration

The solution uses Python, SQLite, Flask, and a frontend dashboard to convert large healthcare datasets into actionable monitoring outputs.

---

## 1. Claims Work

### Data Preparation and Batch Processing

For claims data, the work starts from multiple CMS-style FFS claim sources such as:

- carrier
- dme
- hha
- hospice
- inpatient
- outpatient
- snf

These datasets were prepared and split into manageable batch files for downstream processing. The splitting utilities and preprocessing flow support large-file handling and structured batch-based execution.

Main related files:

- `create.py`
- `preprocess.py`
- `preprocess_large.py`
- batch folders such as `split_carrier`, `split_inpatient`, `outpatient_batches`, `dme_splits`, `snf_split`, `hha_splits`, and `hospice_splits`

### Claims Data Quality Engine

A rule-based data quality engine was built for claim tables and executed against the SQLite source database. The claims DQ layer reads directly from `claim_sentinel.db` and stores run-level output in `claim_dagster.db`.

The claims quality framework covers multiple dimensions, including:

- completeness
- conformance
- correctness
- concordance
- plausibility
- internal consistency
- provider-level quality tracking

This layer also produces rule-level evidence output files for failed checks and stores execution metadata compatible with a Dagster-style run table.

Main related files:

- `hard_quality.py`
- `data_quality.py`
- output database: `claim_dagster.db`
- DQ evidence folder: `dq_output`

### Claims Volume Risk

A provider-level claims volume monitoring pipeline was created to measure monthly volume drift against historical baselines. It combines multiple claim sources and calculates provider-level risk using prior-month behavior.

The claims volume logic includes:

- provider-wise monthly aggregation
- 6-month rolling history requirement
- deviation from historical baseline
- conversion of deviation into risk score
- risk categorization into low, moderate, medium, high, and critical
- root cause and recommendation generation

The results are stored in `voulme.db`.

Main related file:

- `volume.py`

### Claims SLA and Behavior Monitoring

An SLA and behavior analysis layer was developed on top of claims volume and DQ execution history. This does not calculate new volume risk; instead, it evaluates operational processing performance.

The claims SLA layer includes:

- SLA compliance measurement using processing duration
- minor breach vs breached classification
- simple moving-average behavior baseline
- deviation-based anomaly flagging
- root cause and recommendation support

This layer reads from:

- `voulme.db`
- `claim_dagster.db`

and writes to:

- `claims_sla_behavior.db`

Main related file:

- `claim_sla.py`

### Claims Anomaly Detection

A dedicated anomaly detection pipeline was built for claims to identify suspicious provider-month patterns across multiple claim types.

The claims anomaly logic includes:

- robust Z-score analysis
- rolling historical PSI analysis
- rule-based anomaly validation
- provider-month peer comparison
- claim-type-aware anomaly storage
- preservation of historical runs using run IDs and timestamps

The anomaly outputs are stored in:

- `anomalies.db`

Main related file:

- `claims_anomaly.py`

---

## 2. Pharmacy Work

### Pharmacy Data Preparation

The pharmacy workflow was built around Medicare Part D datasets and prescriber-drug level information. Input preparation supports provider-drug analysis, annual trend analysis, and reference table usage.

Main related files:

- `preprocess_pharmacy.py`
- `preprocess_hlsum.py`
- pharmacy split folders such as `split_pharmacy`, `split_pharmacy_dlsum`, and `split_pharmacy_hlsum`

### Pharmacy Data Quality Engine

A provider-level pharmacy data quality pipeline was created for the `part_d_prescriber_drug` dataset. The quality engine evaluates prescriber, drug, geography, suppression, and numeric integrity fields and stores detailed provider-level DQ outputs.

This layer includes:

- completeness checks for required prescriber and drug fields
- validity checks for specialty source, state, FIPS, and suppression logic
- consistency checks across linked values
- referential and concordance checks
- plausibility and correctness checks
- weighted quality scoring
- provider-level summary, dimension, and evidence tables

The results are stored in:

- `pharmacy_database.db`

Main related file:

- `pharmacy_quality.py`

### Pharmacy Volume Risk

A pharmacy volume-risk engine was built using Part D annual datasets. It evaluates utilization shifts at multiple levels.

The pharmacy volume layer produces:

- overall yearly volume risk
- NPI-level volume risk
- drug-level volume risk
- NPI-drug detail output

The logic includes:

- 3-year rolling baseline comparison
- Z-score-based and percentile-based risk mapping
- risk category generation
- root cause and recommendation generation

The results are stored in:

- `volume_pharmacy.db`

Main related file:

- `volume_pharmacy.py`

### Pharmacy SLA and Behavior Monitoring

An SLA and behavior layer was built for pharmacy processing by combining pharmacy volume-risk outputs with pharmacy DQ execution history.

This layer includes:

- SLA compliance tracking
- annual behavior comparison using previous 3 calendar years
- detection of anomalous utilization change
- enrichment of the existing output table with root cause and recommendation

The results are stored in:

- `pharmacy_sla_behavior.db`

Main related file:

- `pharmacy_sla.py`

### Pharmacy Anomaly Detection

A separate anomaly pipeline was created for drug and prescriber behavior. It focuses on provider-drug utilization and pharmacy-specific peer patterns.

This layer includes:

- provider-drug utilization anomaly detection
- cost-per-claim anomaly detection
- claims-per-beneficiary anomaly detection
- days-supply anomaly detection
- multi-metric provider anomaly logic
- specialty PSI anomaly detection
- geographic/provider PSI anomaly detection
- yearly trend anomaly detection

Outputs are written to:

- `anomalies.db`

Main related file:

- `pharmacy_anomaly.py`

### Optional Database Movement Utility

An additional utility was created to move selected pharmacy tables from SQLite into MySQL after normalizing column names.

Main related file:

- `pharmacy_db.py`

---

## 3. Authorization Work

### Authorization Dataset Integration

Authorization processing was built around the `authorization_dataset` source. This brought authorization into the same monitoring framework used for claims and pharmacy.

Main source:

- `authorization_dataset` table

### Authorization Data Quality Pipeline

A dedicated DQ pipeline was created for authorization records and writes output into a Dagster-style run table.

The authorization DQ logic includes checks for:

- valid authorization status values
- valid urgency values
- pending SLA age thresholds
- date quality and status/date consistency
- quality scoring and severity ranking
- root cause and recommendation generation

The results are stored in:

- `auth_dagster.db`

Main related file:

- `auth_dq.py`

### Authorization SLA and Behavior Analysis

An authorization SLA engine was built using request and approval timestamps. This adapts the same operational monitoring model used in claims, but with authorization-specific business rules.

The authorization SLA logic includes:

- turnaround time calculation from `request_date` to `approval_date`
- SLA limit of 72 hours
- classification into met, minor breach, and breached
- monthly authorization count tracking
- previous 3-month average baseline
- deviation-based behavior anomaly flagging
- output schema aligned with the claims Dagster/DQ structure

The results are stored in:

- `auth_sla.db`

Main related file:

- `auth_sla.py`

### Authorization Provider Volume Risk

A provider-level volume-risk pipeline was created for authorization workload monitoring.

The authorization volume logic includes:

- monthly authorization aggregation by provider
- 3-month historical baseline requirement
- median baseline comparison
- deviation-to-risk conversion
- low-volume handling
- risk levels from low to critical
- root cause and recommendation generation

The results are stored in:

- `auth_volume.db`

Main related file:

- `auth_volume.py`

---

## 4. Shared Platform Work

### SQLite-Based Operational Data Layer

A consistent SQLite architecture was used to store intermediate and final outputs across all three domains. This created a lightweight analytics layer for:

- claims DQ
- claims SLA
- claims anomaly detection
- pharmacy DQ
- pharmacy SLA
- pharmacy anomaly detection
- authorization DQ
- authorization SLA
- authorization volume risk

### Expected Time Ingestion

A utility was created to ingest provider expected-time CSV files into SQLite tables for reference and future operational checks.

Main related file:

- `ingest.py`

Output database:

- `expected_time_check.db`

### Backend API

A Flask API was created to expose dashboard data from the SQLite databases. The API supports:

- health checks
- dashboard summary metrics
- anomaly counts
- severity views
- operational signals
- claim-type summaries
- provider and SLA-related endpoints

Main related file:

- `app.py`

### Frontend Dashboard

A frontend dashboard was built to present the monitoring platform as ClaimCare. It includes:

- landing page
- login flow
- overview dashboard
- data quality section
- processing section
- SLA and behavior section
- anomalies section
- insights section
- alerts section
- latest batch view

The frontend is wired to the Flask API and surfaces claims and pharmacy operational metrics in a live dashboard experience.

Main related files:

- `frontend/components/claimcare-app.tsx`
- `frontend/app/page.tsx`
- `frontend/app/layout.tsx`
- `frontend/app/globals.css`

---

## 5. Final Outcome

Across claims, pharmacy, and authorization, the completed work established a healthcare operations monitoring system that:

- ingests and organizes raw datasets
- validates data quality with explainable rules
- calculates provider and population-level volume risk
- monitors SLA compliance and behavioral drift
- detects anomalies using robust statistical methods where needed
- generates root causes and recommendations
- serves results through a backend API
- presents them in a product-style monitoring dashboard

In short, the work was not just dataset processing. It became a full operational intelligence platform for payer workflows across claims, pharmacy, and authorization.
