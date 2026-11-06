---
status: draft
story_format: concise
summary: PRODUCER_CONTRACT: monthly Type 2 load (stage → history → processing)
project:
issue_type: Story
parent:
labels: [snowflake, type2, file-ingestion]
components: [Data Engineering]
priority: Medium
story_points:
attachments: []
sources: [PRODUCER_CONTRACT_requirements.docx, PRODUCER_CONTRACT_spec_v1.0.xlsx]
jira_key:
jira_url:
---

# PRODUCER_CONTRACT: monthly Type 2 load (stage → history → processing)

## Description

### Context / Why

The Distribution team sends a monthly file of producer (agent) contracts. Commission reporting needs the current contract for each producer, and Finance needs to see how commission rates and statuses changed over time. This story builds the standard three-layer load so history keeps every version (Type 2) and processing holds the latest version only.

### Scope

- Monthly file `PRODUCER_CONTRACT_YYYYMMDD.csv` (valuation date = last day of the month), arriving Calendar Day 1 by 09:00; full extract each month.
- Business key `PRODUCER_ID` + `CONTRACT_CODE`; column types, nullability, compare-for-change and masking flags as defined in the **Column Spec** tab of *PRODUCER_CONTRACT_spec_v1.0.xlsx*.
- Objects: stage `UTIL.STG_PRODUCER_CONTRACT`; tables `STG.PRODUCER_CONTRACT_STG`, `HIST.PRODUCER_CONTRACT_HIST`, `PRC.PRODUCER_CONTRACT`; JavaScript procedures `UTIL.SP_LOAD_STG_`, `SP_DVF_`, `SP_LOAD_HIST_`, `SP_LOAD_PRC_` and orchestrator `UTIL.SP_RUN_PRODUCER_CONTRACT(P_VALUATION_DATE, P_FILE_NAME)`; reporting views `RPT.V_PRODUCER_CONTRACT_CURRENT` and `RPT.V_PRODUCER_CONTRACT_CHANGES`.
- Not in this story: JS7 job definition (Operations), PROD deployment, file archiving.

### Load rules

Let `VD` be the valuation date passed to the run.

1. **LR-1 Staging:** delete all rows, then load the file. Empty strings become NULL.
2. **LR-2 Changed key:** expire the current history row (`END_EFFECTIVE_DATE = VD - 1`, `CURRENT_RECORD_IND = 'N'`) and insert the new version from `VD`. `SOURCE_UPDATE_TS` alone is not a change.
3. **LR-3 New key:** insert as the current version.
4. **LR-4 Key missing from source:** expire the current version; no new version.
5. **LR-5 Rerun of the same VD:** undo that VD's history changes first, then merge again.
6. **LR-6 Processing:** delete all rows, insert every current history row with `VALUATION_DATE = VD`.

### Data validations

Run after staging, before history; any failure stops the run with history and processing untouched.

- **DVF-1** staging has rows; **DVF-2** no duplicate business keys; **DVF-3** required columns not NULL; **DVF-4** `COMMISSION_PCT` between 0 and 100; **DVF-5** `CONTRACT_STATUS` in (`ACTIVE`, `SUSPENDED`, `TERMINATED`); **DVF-6** `VD` not earlier than the latest loaded month.

### Masking

Apply the existing TIN and EMAIL policies to `TAX_ID` and `EMAIL_ADDRESS` on staging, history and processing, as flagged in the workbook. The load role stays unmasked.

### Attachments / documents file path

- Shared folder: `\\fileserver\DataEngineering\Specs\PRODUCER_CONTRACT`
- Documents: *PRODUCER_CONTRACT requirements* (Word), *PRODUCER_CONTRACT_spec_v1.0.xlsx*

## Acceptance criteria

- [ ] **AC-1 Objects:** Given the folder is deployed to DEV, when the objects are listed, then every object in Scope exists with the listed names.
- [ ] **AC-2 First load:** Given an empty history, when the October run completes, then staging, history and processing hold the same row count and every history row is current from `2026-10-31`.
- [ ] **AC-3 Changes:** Given the November file, when the run completes, then changed keys have two versions, new keys one current version, missing keys none, and keys with only a `SOURCE_UPDATE_TS` change one version.
- [ ] **AC-4 DVF:** Given a file breaking DVF-2 and DVF-4, when the run executes, then it fails naming both rules and history and processing are unchanged.
- [ ] **AC-5 Rerun:** Given November is loaded, when the November run executes again, then all counts are unchanged and no key has two current rows.
- [ ] **AC-6 Masking:** Given a role without PII access, when it queries the tables and views, then `TAX_ID` and `EMAIL_ADDRESS` are masked (verified with counts).

## Dependencies / links

- `snowflake/common/` deployed in DEV (schemas, `UTIL.FF_CSV_STANDARD`, `AUDIT.LOAD_LOG`, masking policies).
- JS7 job `PRODUCER_CONTRACT_MONTHLY`: Operations.
- ⚠ TBC – completion message format for JS7 (owner: tech lead).









