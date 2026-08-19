# Volume Risk: Claims, Pharmacy, and Authorization

This document summarizes the volume-risk monitoring implemented across the three healthcare operations domains. Each workflow compares current utilization with historical behavior, assigns a risk level, and provides a likely cause and recommended action.

## Claims Volume Risk

Claims volume monitoring evaluates provider-level monthly claim activity across the available FFS claim sources.

- **Aggregation:** monthly claim counts by provider.
- **Baseline:** prior six months of provider history.
- **Risk signal:** deviation of the current month from the historical baseline.
- **Output:** risk score and category — Low, Moderate, Medium, High, or Critical.
- **Supporting insight:** root-cause and recommendation fields for operational follow-up.

Implementation: `volume.py`  
Output database: `voulme.db`

## Pharmacy Volume Risk

Pharmacy volume monitoring evaluates annual Medicare Part D utilization trends at several levels.

- **Aggregation:** overall, NPI, drug, and NPI–drug utilization views.
- **Baseline:** rolling three-year comparison.
- **Risk signal:** Z-score and percentile-based change detection.
- **Output:** yearly, NPI-level, drug-level, and NPI–drug risk results with a risk category.
- **Supporting insight:** root-cause and recommendation fields for review of unusual utilization changes.

Implementation: `volume_pharmacy.py`  
Output database: `volume_pharmacy.db`

## Authorization Volume Risk

Authorization volume monitoring evaluates provider workload using monthly authorization-request counts.

- **Aggregation:** monthly authorization counts by provider.
- **Baseline:** at least three months of historical provider activity, using a median baseline.
- **Risk signal:** deviation of the current request volume from that baseline.
- **Special handling:** low-volume providers are evaluated with dedicated logic to limit misleading alerts.
- **Output:** risk score and category from Low through Critical, plus root cause and recommendation.

Implementation: `auth_volume.py`  
Output database: `auth_volume.db`

## Comparison

| Domain | Time grain | Historical baseline | Primary analysis level |
| --- | --- | --- | --- |
| Claims | Monthly | Six months | Provider |
| Pharmacy | Annual | Three years | Overall, NPI, drug, NPI–drug |
| Authorization | Monthly | Three months | Provider |
