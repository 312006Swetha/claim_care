"""
Medicare FFS Claims + Enrollment — Data Quality Rule Engine
=============================================================
Implements 7 data-quality dimensions against the actual uploaded files:

  1. Completeness            5. Plausibility
  2. Correctness              6. Internal Consistency
  3. Concordance              7. Conformance / Standardization
  4. Referential Integrity   

Data sources (column names below are copied EXACTLY from the file headers):

  beneficiary_2025.csv   -> Enrollment / member master table (key: BENE_ID)
  All_FFS_Claims.zip     -> carrier.csv, dme.csv, hha.csv, hospice.csv,
                             inpatient.csv, outpatient.csv, snf.csv
                             (claim-line level, key: BENE_ID + CLM_ID)

All claim/enrollment files are '|' delimited. Dates are 'DD-Mon-YYYY'
(e.g. 16-Aug-1999). Missing values are blank / whitespace-only strings.

Output: one violations CSV per rule per file, plus a JSON summary with
counts, written to OUT_DIR. Violations are QUARANTINED (flagged), never
silently dropped — see `action` column in every output.

--------------------------------------------------------------------------
CHANGE LOG (this revision)
--------------------------------------------------------------------------
- FIX: ICD_DGNS_VRSN_CD / PRNCPAL_DGNS_VRSN_CD only exist in carrier.csv
  and dme.csv. The other 5 claim files (hha, hospice, inpatient,
  outpatient, snf) carry ICD_DGNS_CD1-25 / PRNCPAL_DGNS_CD with NO version
  indicator, so the original check_correctness() silently skipped
  diagnosis-code validation entirely for those 5 files (no code+version
  column pair ever matched). Added infer_icd_version_from_date() +
  a second pass in check_correctness() that infers ICD-9 vs ICD-10 from
  CLM_FROM_DT against the Oct 1, 2015 CMS cutover date, then validates
  the diagnosis codes against the inferred version. Findings from the
  inferred path are written under a distinct rule name
  (invalid_diag_code_inferred_<col>) and a lower-confidence action
  (flag_for_review_inferred_version, not quarantine) since the version
  is inferred, not stated on the record.
- DOC FIX: corrected the admission/discharge date-pair comment — hospice
  and outpatient do NOT carry CLM_ADMSN_DT (only hha/inpatient/snf do),
  so that pairing already no-ops for hospice/outpatient today; this was
  previously mis-described as applying to hospice too.
- Confirmed-but-unchanged (already correct in the prior version, kept
  as-is): state code validation already uses two separate patterns
  (SSA_STATE_RE for beneficiary STATE_CODE, USPS_STATE_RE for claims
  PRVDR_STATE_CD, which accepts either the 2-letter carrier.csv form or
  the 2-digit form used by the other 6 files); NPI validation is
  format-only (no checksum); is_blank() already strips whitespace so a
  lone " " is treated as missing.
"""

import os
import re
import json
import zipfile
import pandas as pd
from datetime import datetime
from collections import defaultdict

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------
BENE_FILE   = "/mnt/user-data/uploads/beneficiary_2025.csv"
CLAIMS_ZIP  = "/mnt/user-data/uploads/All_FFS_Claims.zip"
OUT_DIR     = "/home/claude/work/dq_output"
CHUNKSIZE   = 200_000
DELIM       = "|"
DATE_FMT    = "%d-%b-%Y"
TODAY       = pd.Timestamp(datetime.now().date())
MAX_SAMPLES = 5000          # cap sample rows written per rule (keeps files small)

# CMS ICD-9-CM -> ICD-10-CM mandatory cutover date. Claims with
# CLM_FROM_DT on/after this date must use ICD-10; before it, ICD-9.
# Used only for the 5 claim files that carry no ICD_DGNS_VRSN_CD field.
ICD10_CUTOVER = pd.Timestamp("2015-10-01")

os.makedirs(OUT_DIR, exist_ok=True)

CLAIM_FILES = ["carrier.csv", "dme.csv", "hha.csv", "hospice.csv",
               "inpatient.csv", "outpatient.csv", "snf.csv"]

# --------------------------------------------------------------------------
# HELPERS
# --------------------------------------------------------------------------
def to_date(series):
    """Parse 'DD-Mon-YYYY' safely; blanks/garbage -> NaT (does not raise)."""
    return pd.to_datetime(series.astype(str).str.strip(), format=DATE_FMT, errors="coerce")

def is_blank(series):
    s = series.astype(str).str.strip()
    return s.eq("") | s.isin(["nan", "NaN", "None"]) | series.isna()

def existing(df, cols):
    """Return only the columns from `cols` that actually exist in df."""
    return [c for c in cols if c in df.columns]

NPI_RE   = re.compile(r"^\d{10}$")
ICD10_RE = re.compile(r"^[A-Z][0-9][0-9A-Z](\.?[0-9A-Z]{0,4})?$", re.IGNORECASE)  # incl. U07/U09 (COVID)
ICD9_RE  = re.compile(r"^(\d{3}(\.\d{1,2})?|[EV]\d{2,3}(\.\d{1,2})?)$", re.IGNORECASE)
HCPCS_RE = re.compile(r"^[A-Z0-9]{5}$")
SSA_STATE_RE = re.compile(r"^\d{2}$")       # beneficiary_2025.csv STATE_CODE (SSA numeric)
USPS_STATE_RE = re.compile(r"^([A-Z]{2}|\d{2})$")  # claims PRVDR_STATE_CD: carrier.csv uses USPS
                                                      # alpha ('AL'); dme/hha/hospice/inpatient/
                                                      # outpatient/snf use SSA numeric ('01'). Both
                                                      # are valid CMS RIF conventions.

def valid_diag_code(code, version):
    """version: '0' = ICD-10-CM, '9' = ICD-9-CM (CMS RIF convention)."""
    if code is None or str(code).strip() == "":
        return True  # blank diag is a completeness issue, not correctness
    code = str(code).strip()
    v = str(version).strip()
    if v == "0":
        return bool(ICD10_RE.match(code))
    if v == "9":
        return bool(ICD9_RE.match(code))
    return True  # unknown version flag -> can't judge, don't false-flag

def infer_icd_version_from_date(clm_from_dt_series):
    """
    Infer ICD-9 vs ICD-10 from CLM_FROM_DT for files that carry no
    ICD_DGNS_VRSN_CD field at all (hha, hospice, inpatient, outpatient,
    snf), using the CMS mandatory cutover of Oct 1, 2015.

    Returns an object Series aligned to the input index:
      '0' (ICD-10) for CLM_FROM_DT >= ICD10_CUTOVER
      '9' (ICD-9)  for CLM_FROM_DT <  ICD10_CUTOVER
      pd.NA        for unparseable / missing CLM_FROM_DT (can't infer,
                    don't guess -> caller must skip these rows)
    """
    dt = to_date(clm_from_dt_series)
    version = pd.Series(pd.NA, index=dt.index, dtype="object")
    version[dt.notna() & (dt >= ICD10_CUTOVER)] = "0"
    version[dt.notna() & (dt <  ICD10_CUTOVER)] = "9"
    return version

# --------------------------------------------------------------------------
# VIOLATION SINK
# --------------------------------------------------------------------------
class ViolationSink:
    """Accumulates violation counts + a capped sample per (file, rule)."""
    def __init__(self):
        self.counts = defaultdict(int)
        self.samples = defaultdict(list)

    def add(self, file, dimension, rule, action, df_bad, id_cols, extra_cols=None):
        if df_bad.empty:
            return
        key = (file, dimension, rule)
        self.counts[key] += len(df_bad)
        room = MAX_SAMPLES - len(self.samples[key])
        if room > 0:
            cols = existing(df_bad, id_cols + (extra_cols or []))
            samp = df_bad[cols].head(room).copy()
            samp.insert(0, "action", action)
            samp.insert(0, "rule", rule)
            samp.insert(0, "dimension", dimension)
            samp.insert(0, "file", file)
            self.samples[key].append(samp)

    def flush(self, out_dir):
        summary = []
        for (file, dim, rule), cnt in self.counts.items():
            fname = f"{file.replace('.csv','')}__{dim}__{rule}.csv".replace(" ", "_").replace("/", "-")
            if self.samples[(file, dim, rule)]:
                pd.concat(self.samples[(file, dim, rule)], ignore_index=True).to_csv(
                    os.path.join(out_dir, fname), index=False)
            summary.append({"file": file, "dimension": dim, "rule": rule,
                             "violation_count": cnt, "sample_file": fname})
        with open(os.path.join(out_dir, "dq_summary.json"), "w") as f:
            json.dump(summary, f, indent=2)
        return pd.DataFrame(summary).sort_values(["file", "dimension"]) if summary else pd.DataFrame()

SINK = ViolationSink()

# --------------------------------------------------------------------------
# 0. LOAD ENROLLMENT MASTER  (drives Referential Integrity + Concordance)
# --------------------------------------------------------------------------
def load_enrollment_master(path):
    cols = ["BENE_ID", "STATE_CODE", "BENE_BIRTH_DT", "BENE_DEATH_DT",
            "BENE_ENROLLMT_REF_YR", "AGE_AT_END_REF_YR", "VALID_DEATH_DT_SW",
            "SEX_IDENT_CD", "BENE_RACE_CD", "BENE_HI_CVRAGE_TOT_MONS",
            "BENE_SMI_CVRAGE_TOT_MONS"]
    df = pd.read_csv(path, sep=DELIM, usecols=lambda c: c in cols, dtype=str,
                      keep_default_na=False)
    df["BENE_BIRTH_DT_P"] = to_date(df["BENE_BIRTH_DT"])
    df["BENE_DEATH_DT_P"] = to_date(df["BENE_DEATH_DT"]) if "BENE_DEATH_DT" in df else pd.NaT
    df = df.drop_duplicates(subset=["BENE_ID"])
    return df.reset_index(drop=True)

print("Loading enrollment master ...")
enroll = load_enrollment_master(BENE_FILE)
VALID_BENE_IDS = set(enroll["BENE_ID"])
print(f"  {len(VALID_BENE_IDS):,} unique BENE_ID in enrollment master")

# ==========================================================================
# 1. COMPLETENESS  — required key fields must not be missing
# ==========================================================================
CLAIM_REQUIRED = ["BENE_ID", "CLM_ID", "CLM_FROM_DT", "CLM_THRU_DT", "CLM_PMT_AMT"]

def check_completeness(df, file):
    req = existing(df, CLAIM_REQUIRED)
    for col in req:
        bad = df[is_blank(df[col])]
        SINK.add(file, "Completeness", f"missing_{col}", "quarantine",
                  bad, ["BENE_ID", "CLM_ID"], [col])

def check_completeness_bene(df):
    req = ["BENE_ID", "STATE_CODE", "BENE_BIRTH_DT", "SEX_IDENT_CD", "BENE_ENROLLMT_REF_YR"]
    for col in existing(df, req):
        bad = df[is_blank(df[col])]
        SINK.add("beneficiary_2025.csv", "Completeness", f"missing_{col}",
                  "quarantine", bad, ["BENE_ID"], [col])

# ==========================================================================
# 2. CORRECTNESS  — values are valid / accurate, not just present
# ==========================================================================
NPI_FIELDS = ["ORG_NPI_NUM", "AT_PHYSN_NPI", "OP_PHYSN_NPI", "OT_PHYSN_NPI",
              "RNDRNG_PHYSN_NPI", "RFR_PHYSN_NPI", "PRF_PHYSN_NPI",
              "CARR_CLM_BLG_NPI_NUM", "PRVDR_NPI"]

def check_correctness(df, file):
    # invalid NPI format (present but not 10 digits) — format-only check,
    # deliberately no Luhn/checksum validation: this dataset uses synthetic
    # placeholder NPIs (e.g. 9999971093) that are structurally valid but
    # would never pass a real checksum.
    for col in existing(df, NPI_FIELDS):
        present = ~is_blank(df[col])
        bad_fmt = present & ~df[col].astype(str).str.strip().str.match(NPI_RE)
        SINK.add(file, "Correctness", f"invalid_npi_format_{col}", "quarantine",
                  df[bad_fmt], ["BENE_ID", "CLM_ID"], [col])

    # --- diagnosis codes: files that carry an explicit ICD_DGNS_VRSN_CD ---
    # (carrier.csv, dme.csv only). '0' = ICD-10-CM, '9' = ICD-9-CM.
    diag_pairs = []
    diag_code_cols_no_version = []
    for i in list(range(1, 26)) + [""]:
        suf = "" if i == "" else str(i)
        code_col, ver_col = f"ICD_DGNS_CD{suf}", f"ICD_DGNS_VRSN_CD{suf}"
        if suf == "":
            code_col, ver_col = "PRNCPAL_DGNS_CD", "PRNCPAL_DGNS_VRSN_CD"
        if code_col in df.columns and ver_col in df.columns:
            diag_pairs.append((code_col, ver_col))
        elif code_col in df.columns and ver_col not in df.columns:
            # NEW: this file has the diagnosis code column but no matching
            # version column (hha, hospice, inpatient, outpatient, snf).
            diag_code_cols_no_version.append(code_col)

    for code_col, ver_col in diag_pairs:
        mask = ~df.apply(lambda r: valid_diag_code(r[code_col], r[ver_col]), axis=1)
        SINK.add(file, "Correctness", f"invalid_diag_code_{code_col}", "quarantine",
                  df[mask], ["BENE_ID", "CLM_ID"], [code_col, ver_col])

    # --- NEW: diagnosis codes in files with NO version column at all ---
    # Infer ICD-9 vs ICD-10 from CLM_FROM_DT vs. the Oct 1, 2015 cutover,
    # then validate against the inferred version. Lower confidence than
    # the stated-version path above, so: distinct rule name, and a
    # "flag_for_review" action instead of "quarantine" — a claim spanning
    # the cutover month, or a late/corrected filing, can legitimately use
    # the "wrong side" version relative to CLM_FROM_DT alone.
    if diag_code_cols_no_version and "CLM_FROM_DT" in df.columns:
        inferred_ver = infer_icd_version_from_date(df["CLM_FROM_DT"])
        for code_col in diag_code_cols_no_version:
            codes = df[code_col]
            # only judge rows where we have both a code and an inferred version
            checkable = inferred_ver.notna() & ~is_blank(codes)
            if not checkable.any():
                continue
            valid_mask = pd.Series(True, index=df.index)
            valid_mask.loc[checkable] = [
                valid_diag_code(c, v)
                for c, v in zip(codes[checkable], inferred_ver[checkable])
            ]
            bad_mask = checkable & ~valid_mask
            if not bad_mask.any():
                continue
            bad = df.loc[bad_mask].copy()
            bad["_INFERRED_ICD_VRSN"] = inferred_ver[bad_mask]
            SINK.add(file, "Correctness", f"invalid_diag_code_inferred_{code_col}",
                      "flag_for_review_inferred_version", bad,
                      ["BENE_ID", "CLM_ID"], [code_col, "CLM_FROM_DT", "_INFERRED_ICD_VRSN"])

    # HCPCS code format (5 alphanumeric chars) when present
    if "HCPCS_CD" in df.columns:
        present = ~is_blank(df["HCPCS_CD"])
        bad = present & ~df["HCPCS_CD"].astype(str).str.strip().str.match(HCPCS_RE)
        SINK.add(file, "Correctness", "invalid_hcpcs_format", "quarantine",
                  df[bad], ["BENE_ID", "CLM_ID"], ["HCPCS_CD"])

def check_correctness_bene(df):
    if "SEX_IDENT_CD" in df.columns:
        bad = ~df["SEX_IDENT_CD"].astype(str).str.strip().isin(["0", "1", "2"])
        SINK.add("beneficiary_2025.csv", "Correctness", "invalid_sex_code",
                  "quarantine", df[bad], ["BENE_ID"], ["SEX_IDENT_CD"])
    if "STATE_CODE" in df.columns:
        bad = ~df["STATE_CODE"].astype(str).str.strip().str.match(SSA_STATE_RE)
        SINK.add("beneficiary_2025.csv", "Correctness", "invalid_state_code",
                  "quarantine", df[bad], ["BENE_ID"], ["STATE_CODE"])

# ==========================================================================
# 3. CONCORDANCE  — same fact agrees across enrollment vs. claims
# ==========================================================================
def check_concordance(df, file):
    if "BENE_ID" not in df.columns or "CLM_FROM_DT" not in df.columns:
        return
    merged = df.merge(enroll[["BENE_ID", "BENE_BIRTH_DT_P", "BENE_DEATH_DT_P",
                               "BENE_ENROLLMT_REF_YR"]],
                       on="BENE_ID", how="inner", suffixes=("", "_ENR"))
    frm = to_date(merged["CLM_FROM_DT"])

    # (a) service date after date of death -> enrollment vs. claims disagree
    has_death = merged["BENE_DEATH_DT_P"].notna()
    bad = merged[has_death & frm.notna() & (frm > merged["BENE_DEATH_DT_P"])]
    SINK.add(file, "Concordance", "service_after_death_date", "quarantine",
             bad, ["BENE_ID", "CLM_ID"], ["CLM_FROM_DT", "BENE_DEATH_DT_P"])

    # (b) claim service year does not match beneficiary's enrollment reference year
    if "BENE_ENROLLMT_REF_YR" in merged.columns:
        clm_year = frm.dt.year.astype("Int64")
        enr_year = pd.to_numeric(merged["BENE_ENROLLMT_REF_YR"], errors="coerce").astype("Int64")
        bad2 = merged[clm_year.notna() & enr_year.notna() & (clm_year != enr_year)]
        SINK.add(file, "Concordance", "claim_year_vs_enrollment_year", "flag",
                 bad2, ["BENE_ID", "CLM_ID"], ["CLM_FROM_DT", "BENE_ENROLLMT_REF_YR"])

    # (c) beneficiary age at service date implausible vs. birth date on file
    age_at_service = (frm - merged["BENE_BIRTH_DT_P"]).dt.days / 365.25
    bad3 = merged[frm.notna() & merged["BENE_BIRTH_DT_P"].notna() &
                  ((age_at_service < 0) | (age_at_service > 115))]
    SINK.add(file, "Concordance", "claim_age_vs_birth_date_mismatch", "quarantine",
             bad3, ["BENE_ID", "CLM_ID"], ["CLM_FROM_DT", "BENE_BIRTH_DT_P"])

# ==========================================================================
# 4. REFERENTIAL INTEGRITY  — foreign keys must exist in the master table
# ==========================================================================
def check_referential_integrity(df, file):
    if "BENE_ID" in df.columns:
        bad = df[~df["BENE_ID"].isin(VALID_BENE_IDS) & ~is_blank(df["BENE_ID"])]
        SINK.add(file, "Referential Integrity", "bene_id_not_in_enrollment",
                  "route_to_data_exception_queue", bad, ["BENE_ID", "CLM_ID"])

    # duplicate primary key (BENE_ID + CLM_ID + LINE_NUM) within the chunk
    line_col = next((c for c in ["LINE_NUM", "CLM_LINE_NUM"] if c in df.columns), None)
    if "CLM_ID" in df.columns:
        key_cols = ["BENE_ID", "CLM_ID"] + ([line_col] if line_col else [])
        dup_mask = df.duplicated(subset=key_cols, keep=False)
        SINK.add(file, "Referential Integrity", "duplicate_claim_line_key",
                  "quarantine_pend_before_payment", df[dup_mask], key_cols)

# ==========================================================================
# 5. PLAUSIBILITY  — values make logical / clinical sense
# ==========================================================================
DATE_PAIRS = [  # (from, thru) — thru must be >= from
    ("CLM_FROM_DT", "CLM_THRU_DT"),
    # CLM_ADMSN_DT / NCH_BENE_DSCHRG_DT only exist together in hha,
    # inpatient, and snf. hospice and outpatient do NOT carry
    # CLM_ADMSN_DT, so this pair simply no-ops for those two files
    # (neither column check nor malformed-date check fires there).
    ("CLM_ADMSN_DT", "NCH_BENE_DSCHRG_DT"),
]
AMOUNT_FIELDS = ["CLM_PMT_AMT", "CLM_TOT_CHRG_AMT", "NCH_CLM_BENE_PMT_AMT",
                  "LINE_NCH_PMT_AMT", "REV_CNTR_PMT_AMT_AMT", "REV_CNTR_TOT_CHRG_AMT"]
UNIT_FIELDS = ["LINE_SRVC_CNT", "REV_CNTR_UNIT_CNT"]

def check_plausibility(df, file):
    # date order: thru/discharge must not precede from/admission
    for f_col, t_col in DATE_PAIRS:
        if f_col in df.columns and t_col in df.columns:
            fdt, tdt = to_date(df[f_col]), to_date(df[t_col])
            bad = df[fdt.notna() & tdt.notna() & (tdt < fdt)]
            SINK.add(file, "Plausibility", f"{t_col}_before_{f_col}", "quarantine",
                      bad, ["BENE_ID", "CLM_ID"], [f_col, t_col])
        elif f_col in df.columns:
            malformed = df[~is_blank(df[f_col]) & to_date(df[f_col]).isna()]
            SINK.add(file, "Plausibility", f"malformed_date_{f_col}", "quarantine",
                      malformed, ["BENE_ID", "CLM_ID"], [f_col])

    # negative amounts (payments/charges should not be negative)
    for col in existing(df, AMOUNT_FIELDS):
        vals = pd.to_numeric(df[col], errors="coerce")
        bad = df[vals.notna() & (vals < 0)]
        SINK.add(file, "Plausibility", f"negative_amount_{col}", "flag_for_review",
                  bad, ["BENE_ID", "CLM_ID"], [col])

    # non-positive service units
    for col in existing(df, UNIT_FIELDS):
        vals = pd.to_numeric(df[col], errors="coerce")
        bad = df[vals.notna() & (vals <= 0)]
        SINK.add(file, "Plausibility", f"non_positive_units_{col}", "quarantine",
                  bad, ["BENE_ID", "CLM_ID"], [col])

    # utilization/length-of-stay sanity (inpatient/snf)
    if "CLM_UTLZTN_DAY_CNT" in df.columns:
        vals = pd.to_numeric(df["CLM_UTLZTN_DAY_CNT"], errors="coerce")
        bad = df[vals.notna() & ((vals < 0) | (vals > 365))]
        SINK.add(file, "Plausibility", "implausible_utilization_days", "flag_for_review",
                  bad, ["BENE_ID", "CLM_ID"], ["CLM_UTLZTN_DAY_CNT"])

def check_plausibility_bene(df):
    if "AGE_AT_END_REF_YR" in df.columns:
        vals = pd.to_numeric(df["AGE_AT_END_REF_YR"], errors="coerce")
        bad = df[vals.notna() & ((vals < 0) | (vals > 115))]
        SINK.add("beneficiary_2025.csv", "Plausibility", "implausible_age",
                  "quarantine", bad, ["BENE_ID"], ["AGE_AT_END_REF_YR"])
    if "BENE_BIRTH_DT" in df.columns:
        bd = to_date(df["BENE_BIRTH_DT"])
        malformed = df[~is_blank(df["BENE_BIRTH_DT"]) & bd.isna()]
        SINK.add("beneficiary_2025.csv", "Plausibility", "malformed_birth_date",
                  "quarantine", malformed, ["BENE_ID"], ["BENE_BIRTH_DT"])
        future = df[bd.notna() & (bd > TODAY)]
        SINK.add("beneficiary_2025.csv", "Plausibility", "birth_date_in_future",
                  "quarantine", future, ["BENE_ID"], ["BENE_BIRTH_DT"])
    if "BENE_DEATH_DT" in df.columns and "BENE_BIRTH_DT" in df.columns:
        dd = to_date(df["BENE_DEATH_DT"])
        bd = to_date(df["BENE_BIRTH_DT"])
        bad = df[dd.notna() & bd.notna() & (dd < bd)]
        SINK.add("beneficiary_2025.csv", "Plausibility", "death_before_birth",
                  "quarantine", bad, ["BENE_ID"], ["BENE_BIRTH_DT", "BENE_DEATH_DT"])

# ==========================================================================
# 6. INTERNAL CONSISTENCY  — a claim must balance against its own line items
# ==========================================================================
# For a claim-line file, the header amount (e.g. CLM_PMT_AMT) is repeated on
# every line belonging to that claim. The true "lines total" is the SUM of
# the per-line payment field across all lines of that CLM_ID.
LINE_TO_HEADER = {  # (line-level $ field, header $ field, tolerance $)
    "LINE_NCH_PMT_AMT": ("CLM_PMT_AMT", 1.00),          # carrier / dme
    "REV_CNTR_PMT_AMT_AMT": ("CLM_PMT_AMT", 1.00),       # hha/hospice/outpatient/snf-style
}

_carry = {}  # per-file leftover rows for claims split across chunk boundaries

def check_internal_consistency(df, file):
    line_col, header_col, tol = None, None, None
    for lc, (hc, t) in LINE_TO_HEADER.items():
        if lc in df.columns and hc in df.columns:
            line_col, header_col, tol = lc, hc, t
            break
    if line_col is None or "CLM_ID" not in df.columns:
        return

    work = df
    if file in _carry:
        work = pd.concat([_carry[file], df], ignore_index=True)

    # keep the last CLM_ID's rows back (its lines may continue in next chunk)
    last_id = work["CLM_ID"].iloc[-1]
    _carry[file] = work[work["CLM_ID"] == last_id]
    work = work[work["CLM_ID"] != last_id]
    if work.empty:
        return

    work = work.copy()
    work["_line_amt"] = pd.to_numeric(work[line_col], errors="coerce").fillna(0)
    work["_hdr_amt"] = pd.to_numeric(work[header_col], errors="coerce")
    agg = work.groupby("CLM_ID").agg(line_sum=("_line_amt", "sum"),
                                       hdr_amt=("_hdr_amt", "first"),
                                       bene_id=("BENE_ID", "first")).reset_index()
    bad = agg[agg["hdr_amt"].notna() & ((agg["line_sum"] - agg["hdr_amt"]).abs() > tol)]
    SINK.add(file, "Internal Consistency", f"header_{header_col}_ne_sum_{line_col}",
              "pend_before_payment", bad, ["bene_id", "CLM_ID"], ["hdr_amt", "line_sum"])

    # claim cannot pay out more than it charged
    if "CLM_TOT_CHRG_AMT" in df.columns and "CLM_PMT_AMT" in df.columns:
        chg = pd.to_numeric(df["CLM_TOT_CHRG_AMT"], errors="coerce")
        pmt = pd.to_numeric(df["CLM_PMT_AMT"], errors="coerce")
        bad2 = df[chg.notna() & pmt.notna() & (pmt > chg + tol)]
        SINK.add(file, "Internal Consistency", "payment_exceeds_total_charge",
                  "flag_for_review", bad2, ["BENE_ID", "CLM_ID"],
                  ["CLM_TOT_CHRG_AMT", "CLM_PMT_AMT"])

    # admission <= from <= thru <= discharge, when all four present
    if all(c in df.columns for c in ["CLM_ADMSN_DT", "CLM_FROM_DT", "CLM_THRU_DT", "NCH_BENE_DSCHRG_DT"]):
        adm = to_date(df["CLM_ADMSN_DT"]); frm = to_date(df["CLM_FROM_DT"])
        thr = to_date(df["CLM_THRU_DT"]); dis = to_date(df["NCH_BENE_DSCHRG_DT"])
        ok_mask = adm.notna() & frm.notna() & thr.notna() & dis.notna()
        bad3 = df[ok_mask & ~((adm <= frm) & (frm <= thr) & (thr <= dis))]
        SINK.add(file, "Internal Consistency", "date_sequence_violation",
                  "quarantine", bad3, ["BENE_ID", "CLM_ID"],
                  ["CLM_ADMSN_DT", "CLM_FROM_DT", "CLM_THRU_DT", "NCH_BENE_DSCHRG_DT"])

def flush_internal_consistency_carry():
    """Process whatever is left in _carry after the last chunk of each file."""
    for file, work in list(_carry.items()):
        if work.empty:
            continue
        line_col, header_col = None, None
        for lc, (hc, t) in LINE_TO_HEADER.items():
            if lc in work.columns and hc in work.columns:
                line_col, header_col, tol = lc, hc, t
                break
        if line_col is None:
            continue
        w = work.copy()
        w["_line_amt"] = pd.to_numeric(w[line_col], errors="coerce").fillna(0)
        w["_hdr_amt"] = pd.to_numeric(w[header_col], errors="coerce")
        agg = w.groupby("CLM_ID").agg(line_sum=("_line_amt", "sum"),
                                        hdr_amt=("_hdr_amt", "first"),
                                        bene_id=("BENE_ID", "first")).reset_index()
        bad = agg[agg["hdr_amt"].notna() & ((agg["line_sum"] - agg["hdr_amt"]).abs() > tol)]
        SINK.add(file, "Internal Consistency", f"header_{header_col}_ne_sum_{line_col}",
                  "pend_before_payment", bad, ["bene_id", "CLM_ID"], ["hdr_amt", "line_sum"])
    _carry.clear()

# ==========================================================================
# 7. CONFORMANCE / STANDARDIZATION  — approved code sets & formats
# ==========================================================================
VALID_DIAG_VERSIONS = {"0", "9", ""}

def check_conformance(df, file):
    for i in list(range(1, 26)) + [""]:
        suf = "" if i == "" else str(i)
        ver_col = "PRNCPAL_DGNS_VRSN_CD" if suf == "" else f"ICD_DGNS_VRSN_CD{suf}"
        if ver_col in df.columns:
            bad = df[~df[ver_col].astype(str).str.strip().isin(VALID_DIAG_VERSIONS)]
            SINK.add(file, "Conformance", f"invalid_diag_version_{ver_col}", "quarantine",
                      bad, ["BENE_ID", "CLM_ID"], [ver_col])

    # date fields must conform to CMS DD-Mon-YYYY standard when populated
    date_like = [c for c in df.columns if c.endswith("_DT") or c.endswith("_DT_ID")]
    for col in date_like:
        present = ~is_blank(df[col])
        bad = present & to_date(df[col]).isna()
        SINK.add(file, "Conformance", f"nonstandard_date_format_{col}", "quarantine",
                  df[bad], ["BENE_ID", "CLM_ID"], [col])

    if "PRVDR_STATE_CD" in df.columns:
        present = ~is_blank(df["PRVDR_STATE_CD"])
        bad = present & ~df["PRVDR_STATE_CD"].astype(str).str.strip().str.upper().str.match(USPS_STATE_RE)
        SINK.add(file, "Conformance", "nonstandard_state_code", "quarantine",
                  df[bad], ["BENE_ID", "CLM_ID"], ["PRVDR_STATE_CD"])



# ==========================================================================
# ORCHESTRATOR
# ==========================================================================
def run_on_dataframe(df, file):
    check_completeness(df, file)
    check_correctness(df, file)
    check_concordance(df, file)
    check_referential_integrity(df, file)
    check_plausibility(df, file)
    check_internal_consistency(df, file)
    check_conformance(df, file)
    

def run_claims(zip_path, files=CLAIM_FILES, chunksize=CHUNKSIZE):
    with zipfile.ZipFile(zip_path) as z:
        for file in files:
            print(f"Processing {file} ...")
            with z.open(file) as fh:
                reader = pd.read_csv(fh, sep=DELIM, chunksize=chunksize, dtype=str,
                                      keep_default_na=False, low_memory=False)
                for i, chunk in enumerate(reader):
                    run_on_dataframe(chunk, file)
                    print(f"  chunk {i+1} ({len(chunk):,} rows) done")
    flush_internal_consistency_carry()

def run_beneficiary(path):
    print("Processing beneficiary_2025.csv ...")
    df = pd.read_csv(path, sep=DELIM, dtype=str, keep_default_na=False, low_memory=False)
    check_completeness_bene(df)
    check_correctness_bene(df)
    check_plausibility_bene(df)
   
    dup = df[df.duplicated(subset=["BENE_ID"], keep=False)]
    SINK.add("beneficiary_2025.csv", "Referential Integrity", "duplicate_bene_id",
              "quarantine", dup, ["BENE_ID"])

if __name__ == "__main__":
    run_beneficiary(BENE_FILE)
    run_claims(CLAIMS_ZIP)
    summary = SINK.flush(OUT_DIR)
    print("\n=== DATA QUALITY SUMMARY ===")
    if not summary.empty:
        print(summary.to_string(index=False))
        summary.to_csv(os.path.join(OUT_DIR, "dq_summary.csv"), index=False)
    else:
        print("No violations found.")
    print(f"\nDetailed rule outputs written to: {OUT_DIR}")