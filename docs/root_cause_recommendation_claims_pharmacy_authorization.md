# Root Cause and Recommendation Analysis

## Purpose

This document describes the root-cause analysis (RCA) and recommendation logic implemented for the Claims, Pharmacy, and Authorization workflows. The review is based on the code in this project. The RCA layer is explainability logic: it explains a failure, risk score, SLA result, or behavior anomaly that has already been calculated; it does not change the underlying detection rules.

Each output carries two fields:

- `root_cause`: a plain-language explanation of the detected signal.
- `recommendation`: the next operational or data-remediation action.

## Common Approach Used

Across the workflows, the implementation follows this pattern:

1. Run data-quality, volume, SLA, or behavior calculations.
2. Use the resulting status, score, deviation, baseline, and supporting metrics to select an RCA message.
3. Write the RCA and recommendation with the analysis output so the dashboard and downstream users can review both the alert and the required action.

Recommendations are prioritized by severity. Critical signals call for immediate investigation, high or moderate signals call for review and monitoring, and normal signals receive routine-monitoring guidance.

---

## 1. Claims

### A. Claims data quality

**Code:** `hard_quality.py`

I implemented a deterministic mapping from failed DQ rule names to root causes and corrective actions. The mapping checks specific rule patterns first, then uses the DQ dimension as a fallback for newly added rules.

| Failed-rule area | Root cause described | Recommendation generated |
| --- | --- | --- |
| Missing fields | Required value is absent | Make the field mandatory at ingestion, validate before processing, and correct incomplete records. |
| NPI / beneficiary ID | Provider identifier is invalid, or beneficiary ID is missing, duplicated, or cannot be linked | Validate the identifier and reconcile it with provider or enrollment reference data. |
| Diagnosis / ICD / HCPCS | Code is missing, malformed, or not valid for its coding standard | Validate against the applicable approved code set and correct the code. |
| Duplicate records | Claim or beneficiary key appears more than once | Apply duplicate-key validation and quarantine or reconcile duplicates. |
| Amount, payment, or negative value | Financial value is implausible or inconsistent | Reconcile financial fields and validate permitted numeric ranges. |
| Dates, age, state, sex, utilization | Value is malformed, outside a valid range, or inconsistent with linked data | Standardize values, validate against approved references, and correct affected records. |
| Unknown rule | The DQ dimension describes the failure | Apply the dimension-specific fallback, such as mandatory-field, referential-integrity, plausibility, internal-consistency, or conformance remediation. |

This ensures that every failed claims DQ rule receives an actionable explanation, including a fallback when the rule has no dedicated entry.

### B. Claims volume risk

**Code:** `volume.py`  
**Output:** `voulme.db`

I created RCA messages from the provider's current claim count, rolling six-month baseline, percentage deviation, available history, and calculated risk level.

| Condition | Root cause described | Recommendation generated |
| --- | --- | --- |
| Validation failure | A named property or validation failed | Review failed records, correct values, and rerun validation. |
| Insufficient history | Not enough monthly data for a reliable baseline | Continue collecting data until the minimum historical period is available. |
| Critical | Current claims have a critical deviation from the prior six-month baseline | Immediately investigate abnormal activity, duplicates, missing or incorrectly loaded data, source changes, and operational changes. |
| High | Claim volume has a high deviation from baseline | Compare recent volume with source records and investigate unusual provider activity, missing records, or duplicates. |
| Medium / Moderate | Volume is moderately or slightly different from baseline | Monitor and review source data if the deviation persists or grows. |
| Low | Volume is within expected historical range | No correction required; continue routine monitoring. |
| Unknown | Risk cannot be derived from available values | Validate volume, baseline, and risk-calculation fields. |

The RCA includes the deviation percentage and the current-versus-baseline counts when those values are available.

### C. Claims SLA and behavior analysis

**Code:** `claim_sla.py`  
**Output:** `claims_sla_behavior.db`

I added separate RCA logic for processing-time SLA performance and claim-volume behavior.

| Process | Signal | Root cause and recommendation |
| --- | --- | --- |
| SLA | `BREACHED` | Explains the number of minutes above the SLA and directs investigation of queueing, retries, volume spikes, failed/repeated steps, and downstream delays. |
| SLA | `MINOR_OVERRUN` | Identifies a small delay or transient overhead; recommends monitoring and investigating repeating overruns. |
| SLA | `MET` | States that no breach was detected and no immediate remediation is needed. |
| Behavior | `ANOMALOUS` increase | Explains the deviation from the prior three-month baseline; recommends review of provider concentration, source or batch changes, and processing activity. |
| Behavior | `ANOMALOUS` decrease | Explains the reduction from baseline; recommends validation of missing batches, source delays, processing failures, or a genuine utilization decline. |

Claims anomaly detection (`claims_anomaly.py`) identifies anomalous patterns, but it does not currently generate dedicated `root_cause` and `recommendation` columns. The claims RCA implementation is in the DQ, volume, and SLA/behavior processes above.

---

## 2. Pharmacy

### A. Pharmacy volume risk

**Code:** `volume_pharmacy.py`  
**Output:** `volume_pharmacy.db`

I implemented RCA at four pharmacy volume levels. The logic identifies the strongest existing component driver and scales the recommendation from the final risk score.

| Analysis level | Root-cause method | Recommendation generated |
| --- | --- | --- |
| Overall annual volume | Finds the highest component risk among claims, standardized 30-day fills, beneficiaries, and prescribers | For scores of 75 or more, run priority utilization review against the three-year baseline; for 50 or more, review and monitor the leading component; otherwise use routine monitoring. |
| NPI / provider | Finds the highest peer percentile among claims, 30-day fills, day supply, and beneficiaries | High scores trigger provider-level utilization review, peer comparison, and drill-down to high-volume drugs. Medium scores trigger targeted review of the leading component. |
| Drug | Finds the highest peer percentile for the same utilization measures | High scores trigger targeted drug utilization review of prescriber concentration, beneficiary distribution, claims, and day supply. |
| NPI-drug detail | Flags the combination as contributing to provider utilization when it has measurable claims | Review the combination when its associated provider or drug risk is elevated. |

The root-cause text labels the strongest driver as primary, main contributing, or elevated according to the component score or percentile. It also handles insufficient history or peer data instead of attempting to infer a cause from incomplete inputs.

### B. Pharmacy SLA, DQ execution, and behavior analysis

**Code:** `pharmacy_sla.py`  
**Output:** `pharmacy_sla_behavior.db`

I used an explicit RCA priority order so that the most actionable failure is selected:

1. DQ or property failure
2. Material SLA breach
3. Minor SLA breach
4. Annual behavior anomaly
5. No failure

| Condition | Root cause described | Recommendation generated |
| --- | --- | --- |
| DQ failure | A named data-quality property or processing step failed | Identify the affected records or fields, correct the data issue, and rerun validation. |
| SLA `BREACHED` | Processing materially exceeded the configured limit | Investigate bottlenecks, queueing, retries, database/query performance, volume spikes, and slow pipeline steps; optimize before the next batch. |
| SLA `MINOR_BREACH` | Processing was slightly above the SLA but within the configured minor-breach tolerance | Review transient overhead or upstream/downstream delay and monitor subsequent runs. |
| Annual behavior anomaly | Pharmacy claim volume differs materially from the previous three-calendar-year baseline | Check incoming volume, missing or duplicate records, source-system changes, and unusual pharmacy activity. |
| No failure | No SLA, DQ, or behavior failure occurred | No corrective action is required. |

`pharmacy_quality.py` calculates pharmacy DQ results, but it does not currently add dedicated RCA/recommendation fields. `pharmacy_anomaly.py` detects anomalies without dedicated RCA/recommendation output. The executable RCA support for pharmacy is therefore implemented in volume risk and SLA/DQ/behavior analysis.

---

## 3. Authorization

### A. Authorization data quality

**Code:** `auth_dq.py`  
**Output:** `auth_dagster.db`

I created rule-level root causes and recommendations and append them to every failed authorization record. If a record fails multiple checks, its failed rules, root causes, and recommendations are concatenated. The same information is then grouped into provider-level output.

| Rule group | Examples of root cause | Recommendation generated |
| --- | --- | --- |
| Required identifiers and fields | Missing authorization ID, beneficiary ID, provider NPI, service code, or request date | Populate the valid missing value. |
| Provider NPI validity | NPI is not exactly 10 numeric digits | Correct the provider identifier with a valid 10-digit NPI. |
| Status and urgency validity | Authorization status or urgency is outside the allowed values | Use the allowed authorization statuses and allowed urgency values. |
| Timestamp consistency | Approval precedes request; expiry precedes approval; a status does not agree with the required date | Correct the related timestamps or align the authorization status with the date information. |
| Duplicates | Authorization ID or authorization business record occurs more than once | Investigate and remove unintended duplicate records. |
| Pending timeliness | Authorization remains pending beyond the configured SLA | Review and process the pending authorization. |

### B. Authorization volume risk

**Code:** `auth_volume.py`  
**Output:** `auth_volume.db`

I generated provider-level RCA from the current authorization count, prior three-month baseline, deviation percentage, and risk level.

| Condition | Root cause described | Recommendation generated |
| --- | --- | --- |
| Insufficient history | Too little monthly data to establish a reliable baseline | Continue collecting history until the minimum number of prior calendar months is available. |
| Low volume | Baseline is too small for percentage change to be reliable | Monitor and collect more history before treating percentage changes as material risk. |
| New activity after zero baseline | Current authorizations exist even though the baseline is zero | Validate whether the activity is expected, source-driven, or related to a batch or service-code change. |
| Critical increase | Large increase from the three-month baseline | Immediately check service-code activity, urgent requests, duplicates, batch changes, and source-system changes. |
| Critical decrease | Large decrease from baseline | Validate missing records, incomplete batches, source delays, or ingestion failures. |
| High / Moderate | Elevated or moderate deviation from baseline | Review recent activity and source, batch, service-code, and urgency changes; monitor future months. |
| Normal | Volume is within expected range | No correction required; continue routine monitoring. |

### C. Authorization SLA and behavior analysis

**Code:** `auth_sla.py`  
**Output:** `auth_sla.db`

I added RCA for turnaround-time performance and authorization-volume behavior.

| Process | Signal | Root cause and recommendation |
| --- | --- | --- |
| SLA | `BREACHED` | States the hours above the configured SLA and directs review of processing, queueing, approval, manual-review, and dependency bottlenecks. |
| SLA | `MINOR_BREACH` | Explains a small delay or transient overhead and recommends monitoring for repeated overruns. |
| Behavior | Anomalous increase | States the current count, three-month baseline, and deviation; recommends review of provider concentration, service-code changes, urgent requests, and source/batch changes. |
| Behavior | Anomalous decrease | States the deviation from baseline; recommends validation of missing batches, source delays, ingestion problems, or a real utilization decline. |

## Where the RCA Is Stored and Used

The generated `root_cause` and `recommendation` values are persisted alongside the relevant DQ, volume, and SLA/behavior outputs. `app.py` also reads these fields to provide root-cause summaries through the dashboard API. This connects detected operational signals to concrete review and remediation actions.
