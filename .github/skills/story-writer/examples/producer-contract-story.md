---
status: draft
summary: PRODUCER_CONTRACT: monthly Type 2 load (stage → history → processing)
project:
issue_type: Story
parent:
labels: [snowflake, type2, file-ingestion]
components: [Data Engineering]
priority: Medium
story_points:
attachments: [inputs/PRODUCER_CONTRACT_spec_v1.0.xlsx]
sources: [PRODUCER_CONTRACT_requirements.docx, PRODUCER_CONTRACT_spec_v1.0.xlsx, PRODUCER_CONTRACT_20261031.csv]
jira_key:
jira_url:
---

# PRODUCER_CONTRACT: monthly Type 2 load (stage → history → processing)

## Context / Why

The Distribution team sends a monthly file of producer (agent) contracts. Commission reporting needs the current contract for each producer, and Finance needs to see how commission rates and statuses changed over time [requirements.docx › 1 Background]. Build the standard three-layer load so that history keeps every version (Type 2) and processing holds the latest version only.

## Source

| Item | Value |
|---|---|
| Approach | 1, file-based ingestion |
| Source object(s) | `PRODUCER_CONTRACT_YYYYMMDD.csv`, `YYYYMMDD` = valuation date (last day of the month) [spec.xlsx › Source] |
| Arrives / available | Calendar Day 1 of the next month, by 09:00 [requirements.docx › 2] |
| Format | CSV, comma separated, header row, `"` quoting, UTF-8 [spec.xlsx › Source] |
| Load type | Full extract every month; history built by comparing with current history rows (delta into history) |
| Business key | `PRODUCER_ID` + `CONTRACT_CODE` [spec.xlsx › Column Spec] |
| Stage / file format | `UTIL.STG_PRODUCER_CONTRACT` (internal), `UTIL.FF_CSV_STANDARD` (existing) |

## Scope

| # | Layer | Object type | Name | Repo file | Purpose |
|---|---|---|---|---|---|
| 1 | Setup | Schemas | `PRC`, `RPT` (if not present) | `ddl/00_setup_producer_contract.sql` | Processing and reporting schemas |
| 2 | Setup | Internal stage | `UTIL.STG_PRODUCER_CONTRACT` | `ddl/00_setup_producer_contract.sql` | Landing area for the monthly file |
| 3 | Staging | Table | `STG.PRODUCER_CONTRACT_STG` | `ddl/01_stg_producer_contract.sql` | Raw copy of the current file. Business columns only |
| 4 | History | Table | `HIST.PRODUCER_CONTRACT_HIST` | `ddl/02_hist_producer_contract.sql` | Every version. Business columns + 5 tracking columns |
| 5 | Processing | Table | `PRC.PRODUCER_CONTRACT` | `ddl/03_prc_producer_contract.sql` | Latest version only |
| 6 | Security | Masking | `TAX_ID`, `EMAIL_ADDRESS` on tables 3, 4, 5 | `ddl/04_masking_producer_contract.sql` | Mask sensitive columns |
| 7 | Load | JavaScript procedure | `UTIL.SP_LOAD_STG_PRODUCER_CONTRACT(P_FILE_NAME VARCHAR)` | `procs/sp_load_stg_producer_contract.sql` | Delete staging, load the named file, apply format rules |
| 8 | Validate | JavaScript procedure | `UTIL.SP_DVF_PRODUCER_CONTRACT(P_VALUATION_DATE VARCHAR)` | `procs/sp_dvf_producer_contract.sql` | Run DVF-1 to DVF-6; fail with the list of violations |
| 9 | History | JavaScript procedure | `UTIL.SP_LOAD_HIST_PRODUCER_CONTRACT(P_VALUATION_DATE VARCHAR)` | `procs/sp_load_hist_producer_contract.sql` | Type 2 merge, rerun safe |
| 10 | Processing | JavaScript procedure | `UTIL.SP_LOAD_PRC_PRODUCER_CONTRACT(P_VALUATION_DATE VARCHAR)` | `procs/sp_load_prc_producer_contract.sql` | Delete processing, insert current history rows |
| 11 | Orchestration | JavaScript procedure | `UTIL.SP_RUN_PRODUCER_CONTRACT(P_VALUATION_DATE VARCHAR, P_FILE_NAME VARCHAR)` | `procs/sp_run_producer_contract.sql` | Runs 7 → 8 → 9 → 10, post-load checks, completion message. Called by JS7 |
| 12 | Reporting | View | `RPT.V_PRODUCER_CONTRACT_CURRENT` | `views/v_producer_contract_current.sql` | Consumer view of processing |
| 13 | Reporting | View | `RPT.V_PRODUCER_CONTRACT_CHANGES` | `views/v_producer_contract_changes.sql` | One row per version, with previous commission and status |

All procedures are `LANGUAGE JAVASCRIPT`, `EXECUTE AS CALLER`, bind every value, run their writes in one transaction, log to `AUDIT.LOAD_LOG` and re-throw errors so JS7 sees the failure. Tables use `CREATE TABLE IF NOT EXISTS`, never `CREATE OR REPLACE TABLE`.

## Out of scope

- The JS7 job definition (owned by Operations), PROD deployment, file archiving after load.
- Any change to other entities or to `snowflake/common/`.

## Column specification

Full detail in the attached workbook, tab **Column Spec**.

| # | Column | Type | Null? | Key | Compare for change | Mask | Source format / rule |
|---|---|---|---|---|---|---|---|
| 1 | `PRODUCER_ID` | VARCHAR(10) | N | Y | – | – | Trim |
| 2 | `CONTRACT_CODE` | VARCHAR(8) | N | Y | – | – | Trim, upper case |
| 3 | `PRODUCER_NAME` | VARCHAR(100) | Y | | Y | – | Trim |
| 4 | `TAX_ID` | VARCHAR(11) | Y | | Y | TIN | `999-99-9999` |
| 5 | `EMAIL_ADDRESS` | VARCHAR(255) | Y | | Y | EMAIL | Trim, lower case |
| 6 | `RESIDENT_STATE_CODE` | VARCHAR(2) | Y | | Y | – | 2-letter state |
| 7 | `AGENCY_CODE` | VARCHAR(10) | Y | | Y | – | Trim |
| 8 | `COMMISSION_PCT` | NUMBER(5,2) | Y | | Y | – | 0 to 100 |
| 9 | `CONTRACT_STATUS` | VARCHAR(10) | N | | Y | – | `ACTIVE`, `SUSPENDED`, `TERMINATED` |
| 10 | `CONTRACT_EFFECTIVE_DATE` | DATE | N | | Y | – | `MM/DD/YYYY` |
| 11 | `CONTRACT_END_DATE` | DATE | Y | | Y | – | `MM/DD/YYYY`, blank = NULL |
| 12 | `SOURCE_UPDATE_TS` | TIMESTAMP_NTZ(9) | Y | | **N** | – | `YYYY-MM-DD HH24:MI:SS` |

**History tracking columns, after the business columns:** `BEGIN_EFFECTIVE_DATE DATE`, `END_EFFECTIVE_DATE DATE`, `CURRENT_RECORD_IND VARCHAR(1)`, `LAST_UPDATE_USER VARCHAR(100)`, `LAST_UPDATE_DATE TIMESTAMP_NTZ(9)`.

**Processing columns, after the business columns:** `VALUATION_DATE DATE`, `LAST_UPDATE_USER VARCHAR(100)`, `LAST_UPDATE_DATE TIMESTAMP_NTZ(9)`.

## Load rules

Let `VD` be the valuation date passed to the run.

1. **LR-1 Staging:** delete all rows, then load the file. Empty strings become NULL.
2. **LR-2 Changed key:** a current history row whose compare columns differ from staging (null-safe). Expire it with `END_EFFECTIVE_DATE = VD - 1`, `CURRENT_RECORD_IND = 'N'`, then insert the new version with `BEGIN_EFFECTIVE_DATE = VD`, `END_EFFECTIVE_DATE = '9999-12-31'`, `CURRENT_RECORD_IND = 'Y'`.
3. **LR-3 New key:** insert as the current version (same values as LR-2).
4. **LR-4 Key missing from source:** treat as deleted at source. Expire the current version, no new version [decision 2026-10-20].
5. **LR-5 Unchanged key:** no change. A change in `SOURCE_UPDATE_TS` alone does not create a version.
6. **LR-6 Rerun of the same VD:** first delete history rows with `BEGIN_EFFECTIVE_DATE = VD` and reopen rows with `END_EFFECTIVE_DATE = VD - 1`, then merge again. A VD earlier than the latest loaded `BEGIN_EFFECTIVE_DATE` is rejected (DVF-6).
7. **LR-7 Processing:** delete all rows, insert every current history row with `VALUATION_DATE = VD`.
8. **LR-8 Audit columns:** `LAST_UPDATE_USER = CURRENT_USER()`, `LAST_UPDATE_DATE = CURRENT_TIMESTAMP()` on every row written.

## Data validation (DVF)

Run after staging, before history. Any failure stops the run; history and processing are untouched.

| ID | Rule | Fails when |
|---|---|---|
| DVF-1 | Staging has rows | `COUNT(*) = 0` |
| DVF-2 | No duplicate business keys | `GROUP BY PRODUCER_ID, CONTRACT_CODE HAVING COUNT(*) > 1` returns rows |
| DVF-3 | Required columns present | NULL in `PRODUCER_ID`, `CONTRACT_CODE`, `CONTRACT_STATUS` or `CONTRACT_EFFECTIVE_DATE` |
| DVF-4 | Commission in range | `COMMISSION_PCT` < 0 or > 100 |
| DVF-5 | Valid status | `CONTRACT_STATUS` not in (`ACTIVE`, `SUSPENDED`, `TERMINATED`) |
| DVF-6 | Not loading an older month | `VD` < `MAX(BEGIN_EFFECTIVE_DATE)` in history |

Post-load checks in procedure 11 fail the run if any key has more than one current row, or if processing count ≠ staging count.

## Masking

Attach the existing policies from `snowflake/common/03_masking_policies.sql`: `TAX_ID` → TIN, `EMAIL_ADDRESS` → EMAIL, on staging, history and processing. Views inherit the masking. The load role stays unmasked so history compares real values [requirements.docx › 4 Sensitive data].

## Scheduling and completion message

JS7 job `PRODUCER_CONTRACT_MONTHLY`, Calendar Day 1 at 10:00, calls `CALL UTIL.SP_RUN_PRODUCER_CONTRACT('<last day of previous month>', NULL);`. NULL file name means `PRODUCER_CONTRACT_<VD as YYYYMMDD>.csv`.

Completion message (one line):

```
PRODUCER_CONTRACT load complete | valuation_date=2026-11-30 | file=PRODUCER_CONTRACT_20261130.csv | stg=12 | new=1 | changed=3 | expired_missing=1 | unchanged=8 | prc=12
```

## Acceptance criteria

Test data: `PRODUCER_CONTRACT_20261031.csv`, `PRODUCER_CONTRACT_20261130.csv`, `PRODUCER_CONTRACT_20261130_BAD.csv`.

- [ ] **AC-1 Objects:** Given the folder is deployed to DEV, when the objects are listed, then all 13 objects in Scope exist with the listed names and signatures.
- [ ] **AC-2 First load:** Given an empty history, when the October run completes, then staging, history and processing each hold 12 rows and every history row has `BEGIN_EFFECTIVE_DATE = 2026-10-31`, `END_EFFECTIVE_DATE = 9999-12-31`, `CURRENT_RECORD_IND = 'Y'`.
- [ ] **AC-3 Changed rows:** Given the November file, when the run completes, then `PR00001002/GRP-LTD`, `PR00001004/IND-ACC` and `PR00001006/IND-HOS` each have 2 versions, the old one ending `2026-11-29` with `'N'`.
- [ ] **AC-4 Missing key:** Given `PR00001007/GRP-STD` is not in the November file, when the run completes, then it has no current row and its only version ends `2026-11-29`.
- [ ] **AC-5 New key:** Given `PR00001011/GRP-STD` first appears in November, when the run completes, then it has one current version beginning `2026-11-30`.
- [ ] **AC-6 No false changes:** Given only `SOURCE_UPDATE_TS` changed for `PR00001009/GRP-LTD`, when the run completes, then it still has one version.
- [ ] **AC-7 Totals:** Given both months are loaded, when history and processing are counted, then history = 16 (12 current, 4 expired) and processing = 12 with `VALUATION_DATE = 2026-11-30`.
- [ ] **AC-8 DVF:** Given the BAD file for 2026-11-30, when the run executes, then it fails naming DVF-2 (1) and DVF-4 (1) and history and processing are unchanged.
- [ ] **AC-9 Rerun:** Given November is already loaded, when the November run executes again, then totals are still 16 / 12 / 12 and no key has two current rows.
- [ ] **AC-10 Message:** Given the November run completes, when its result is read, then it matches the completion message format with `new=1 | changed=3 | expired_missing=1 | unchanged=8`.
- [ ] **AC-11 Masking:** Given a role without PII access, when it queries the three tables and both views, then `TAX_ID` and `EMAIL_ADDRESS` are masked (verified with counts, not values).
- [ ] **AC-12 Audit:** Given any procedure call, when it finishes or fails, then `AUDIT.LOAD_LOG` holds a start row and an end or failure row for it.

## Dependencies / links

- `snowflake/common/` deployed in DEV (schemas, `UTIL.FF_CSV_STANDARD`, `AUDIT.LOAD_LOG`, masking policies)
- Source spec `PRODUCER_CONTRACT_spec_v1.0.xlsx` (attached)
- JS7 job definition: Operations

## Decision log

| Date | Decision | By | Source |
|---|---|---|---|
| 2026-10-20 | Keys missing from the file are expired (deleted at source) | PO | requirements.docx › 5 |
| 2026-10-20 | `SOURCE_UPDATE_TS` is not a compare column | PO | spec.xlsx › Column Spec |

## Open questions

| # | Question | Owner | Blocks |
|---|---|---|---|
| 1 | None open | | |

## Definition of Ready

- [x] Context, scope and out of scope are clear
- [x] Source, business key and load type (snapshot / delta) are known
- [x] Column spec is complete (types, nullability, compare columns, masking)
- [x] Acceptance criteria are specific and testable
- [x] Test data is identified
- [x] Open questions are resolved or assigned
- [ ] Estimate and priority are recorded ✘ story points not set; estimate in refinement

## Definition of Done

- [ ] AC-1 to AC-12 verified in DEV, with evidence attached to the story
- [ ] Code in `snowflake/producer_contract/` on a `feature/<KEY>-producer-contract` branch, PR reviewed by Copilot code review and a human, and merged
- [ ] Commits reference the Jira key
- [ ] README in the folder lists the objects, the run command and the rerun steps
