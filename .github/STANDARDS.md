# Snowflake Development Standards

> **Single source of truth.** Every Copilot instruction file, agent and skill in this kit points back here.
> Change a rule here first, then update the instruction file that encodes it.
>
> Items marked **⚠ CONFIRM** are working assumptions taken from the Understanding Document (8 Oct 2026).
> The working group must confirm or replace them before the pilot (Phase 3).

---

## 1. The load pattern

Every entity has **three tables**, and data always moves in one direction:

```
SOURCE ──► STAGING ──► HISTORY (SCD Type 2) ──► PROCESSING (current month)
           truncate    merge: expire + insert   delete + insert for valuation date
           + load
```

| Source type                                                        | How it reaches staging                                             |
| ------------------------------------------------------------------ | ------------------------------------------------------------------ |
| **Approach 1 – File-based**                                 | Business CSV → Snowflake stage → `COPY INTO` staging           |
| **Approach 2 – Direct Data Share (Snowflake-to-Snowflake)** | Direct data share / source DB → `INSERT … SELECT` into staging |

Extraction mode per entity (from the Excel spec):

| Mode         | Meaning                               | History behaviour                                                                                                      |
| ------------ | ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `SNAPSHOT` | Pull the whole source table each run  | Compare full set; expire changed rows; **⚠ CONFIRM** whether rows missing from source are expired (soft delete) |
| `DELTA`    | Pull only the current month's records | Compare only the delta rows; never expire rows that are absent from the delta                                          |

Orchestration: **JS7 jobs** call the stored procedures. Procedures never schedule themselves (no Snowflake Tasks unless agreed).

---

## 2. Naming conventions ⚠ CONFIRM

| Object                 | Pattern                                            | Example                                                                                                  |
| ---------------------- | -------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| Database (per env)     | `<DOMAIN>_<ENV>`                                 | `POLICY_DEV`, `POLICY_TST`, `POLICY_PRD`                                                           |
| Schemas                | `STG`, `HIST`, `PRC`, `UTIL`, `AUDIT`    | `POLICY_DEV.HIST`                                                                                      |
| Staging table          | `STG.<ENTITY>`                                   | `STG.CLAIM_DETAIL`                                                                                     |
| History table          | `HIST.<ENTITY>_HIST`                             | `HIST.CLAIM_DETAIL_HIST`                                                                               |
| Processing table       | `PRC.<ENTITY>`                                   | `PRC.CLAIM_DETAIL`                                                                                     |
| Load procedures        | `UTIL.SP_LOAD_<LAYER>_<ENTITY>`                  | `UTIL.SP_LOAD_STG_CLAIM_DETAIL`, `UTIL.SP_LOAD_HIST_CLAIM_DETAIL`, `UTIL.SP_LOAD_PRC_CLAIM_DETAIL` |
| Orchestrator procedure | `UTIL.SP_RUN_<ENTITY>`                           | `UTIL.SP_RUN_CLAIM_DETAIL`                                                                             |
| Stage                  | `UTIL.STG_<SOURCE>_<ENTITY>`                     | `UTIL.STG_FINANCE_CLAIM_DETAIL`                                                                        |
| File format            | `UTIL.FF_CSV_<VARIANT>`                          | `UTIL.FF_CSV_STANDARD`                                                                                 |
| Masking policy         | `UTIL.MP_<DATA_CLASS>`                           | `UTIL.MP_SSN`, `UTIL.MP_DOB`, `UTIL.MP_EMAIL`                                                      |
| Columns                | `UPPER_SNAKE_CASE`, exactly as in the Excel spec | `POLICY_NUMBER`                                                                                        |

- All identifiers are **UPPER_SNAKE_CASE**, unquoted. Never use quoted, mixed-case identifiers.
- Scripts never hard-code the environment database. Use `USE DATABASE IDENTIFIER($DB_NAME);` or a `&{db}` Snowflake CLI variable set by deployment.

---

## 3. Table standards

### 3.1 Staging — `STG.<ENTITY>`

- Business columns only, in Excel-spec order, with spec types and lengths.
- `COMMENT` on the table and on every column (from the spec "Description").
- Transient table (`CREATE TRANSIENT TABLE`) — no Fail-safe cost for data reloaded every run. ⚠ CONFIRM
- No primary key enforcement (Snowflake doesn't enforce), but declare `PRIMARY KEY (<business key>)` as metadata.

### 3.2 History — `HIST.<ENTITY>_HIST`

Business columns **plus five tracking columns**, always in this order at the end:

| Column                   | Type                 | Rule                                                                                                                                                                 |
| ------------------------ | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BEGIN_EFFECTIVE_DATE` | `TIMESTAMP_NTZ(9)` | When this version became valid. ⚠ CONFIRM: load timestamp vs business date                                                                                          |
| `END_EFFECTIVE_DATE`   | `TIMESTAMP_NTZ(9)` | `'9999-12-31 00:00:00'` for the current version; when expired, set to the new version's `BEGIN_EFFECTIVE_DATE` (half-open interval `[begin, end)`). ⚠ CONFIRM |
| `CURRENT_RECORD_IND`   | `CHAR(1)`          | `'Y'` current, `'N'` expired. Exactly one `'Y'` per business key                                                                                               |
| `LAST_UPDATE_USER`     | `VARCHAR(100)`     | `CURRENT_USER()` at load                                                                                                                                           |
| `LAST_UPDATE_DATE`     | `TIMESTAMP_NTZ(9)` | `CURRENT_TIMESTAMP()::TIMESTAMP_NTZ` at load                                                                                                                       |

- Change detection uses a hash of all non-key business columns:
  `SHA2(CONCAT_WS('||', COALESCE(col1::VARCHAR,'~'), …), 256)`. Compute it inline; do not store unless agreed. ⚠ CONFIRM
- Permanent table. Clustering on `(<business key>, CURRENT_RECORD_IND)` only when the table exceeds ~1 TB.

### 3.3 Processing — `PRC.<ENTITY>`

Business columns **plus three columns**:

| Column               | Type                 | Rule                                                                         |
| -------------------- | -------------------- | ---------------------------------------------------------------------------- |
| `VALUATION_DATE`   | `DATE`             | Month the data represents — last day of the month (`LAST_DAY(:run_date)`) |
| `LAST_UPDATE_USER` | `VARCHAR(100)`     | `CURRENT_USER()`                                                           |
| `LAST_UPDATE_DATE` | `TIMESTAMP_NTZ(9)` | `CURRENT_TIMESTAMP()::TIMESTAMP_NTZ`                                       |

- Load = `DELETE WHERE VALUATION_DATE = :valuation_date` then `INSERT … SELECT` the current-month rows from history, inside one transaction. Re-running a month must be idempotent.

### 3.4 Data types

| Spec says                  | Use                                            |
| -------------------------- | ---------------------------------------------- |
| String / Char / Varchar(n) | `VARCHAR(n)` (keep the spec length)          |
| Integer / Number(p)        | `NUMBER(p,0)` (default `NUMBER(38,0)`)     |
| Decimal / Amount (p,s)     | `NUMBER(p,s)` — never `FLOAT` for money   |
| Date                       | `DATE`                                       |
| Datetime / Timestamp       | `TIMESTAMP_NTZ(9)`                           |
| Flag / Boolean             | `BOOLEAN` or `CHAR(1)` per spec ⚠ CONFIRM |

---

## 4. Stored procedure standards (Snowflake JavaScript)

- `LANGUAGE JAVASCRIPT`, `EXECUTE AS CALLER` ⚠ CONFIRM (vs OWNER), `RETURNS VARIANT`.
- **Parameters are UPPERCASE inside the JS body** (Snowflake rule): a parameter `P_RUN_DATE` is read as `P_RUN_DATE`.
- **Always bind values** with `binds: [...]` — never concatenate user input or parameter values into SQL text. Object names that must be dynamic go through `IDENTIFIER(?)`.
- Every procedure:
  1. Wraps the work in `BEGIN TRANSACTION` / `COMMIT`, with `ROLLBACK` in `catch`.
  2. Writes one row to `AUDIT.LOAD_LOG` at start and one at end (status, row counts, error). ⚠ CONFIRM table
  3. Returns a JSON object: `{ status, procedure, entity, rows_inserted, rows_updated, rows_deleted, query_ids, error }`.
  4. On error: logs, rolls back, then **re-throws** so JS7 sees the failure (non-zero exit).
- No `SELECT *` in procedures; list columns explicitly.
- Header comment block in every procedure: purpose, Jira key, author, parameters, change log.
- Start from the matching procedure in the reference implementation `snowflake/claim_detail/procs/`.

### 1. Signature

- Name: `ETL.SP_LOAD_<LAYER>_<ENTITY>`, file `procs/<entity>/sp_load_<layer>_<entity>.sql`.
- `RETURNS VARCHAR` (no length), `LANGUAGE JAVASCRIPT`, `EXECUTE AS CALLER`.
- Reference arguments in UPPERCASE in the body (`P_LOAD_DATE`), whatever case they were declared in.

### 2. Header

Immediately after `AS $$`. Every field is mandatory; write `N/A` rather than leaving one blank.

```javascript
//------------------------------------------------------------------------------
// PROCEDURE     : <SCHEMA>.<PROCEDURE_NAME>
// TYPE          : LOAD | SUPER | UTILITY | RECON
// DESCRIPTION   : <1-3 lines: what it populates and why>
// AUTHOR        : <Full name>
// CREATION DATE : YYYY-MM-DD
// VERSION       : <major.minor>
//------------------------------------------------------------------------------
// INPUTS
//    TABLES     : <every table/view read, SCHEMA.TABLE>
//    PARAMETERS : <P_NAME> - <meaning, format, allowed values>   or  none
// OUTPUTS
//    TABLES     : <every table written, SCHEMA.TABLE>
//    RETURNS    : <return message format, e.g. SUCCESS: inserted=<n> closed=<n>>
// CALLS         : <child procedures called, or none>
// RUN ORDER     : <JS7 job name and step number>
//------------------------------------------------------------------------------
// CHANGE LOG
// YYYY-MM-DD -- <Author> -- <JIRA-KEY> -- <what changed>
//------------------------------------------------------------------------------
```

---

## 5. Sensitive data (PII/PHI)

- Sensitivity comes from the business's sensitivity rules (Word/Excel). Each sensitive column gets a `DATA_CLASS` in the column spec (e.g. `SSN`, `DOB`, `EMAIL`, `PHONE`, `NAME`, `ADDRESS`).
- Masking is applied with **Snowflake masking policies** (`snowflake/common/03_masking_policies.sql`) attached to columns in staging, history **and** processing tables. ⚠ CONFIRM (vs masking in procedures)
- Every policy returns clear values for the JS7 **load role**. Procedures run `EXECUTE AS CALLER`; a masked load role would hash and store masked values in history.
- Never put real PII/PHI in code, comments, tests, commit messages, PR descriptions or Copilot chat. Use synthetic values only.
- Test and QA queries must **not** `SELECT` raw sensitive columns; check masking via `POLICY_REFERENCES` and a role-based sample.

---

## 6. SQL style

- Keywords UPPERCASE; identifiers UPPER_SNAKE_CASE; 4-space indent; one column per line in `SELECT`, `INSERT` and DDL.
- Leading commas are **not** used — trailing commas. ⚠ CONFIRM
- Explicit `JOIN … ON`; no implicit joins in `WHERE`.
- `CREATE OR REPLACE` only for procedures, views, file formats and masking policies. **Tables use `CREATE TABLE IF NOT EXISTS`** — never `CREATE OR REPLACE TABLE` on history (it destroys history).
- Every script is re-runnable (idempotent).
- Every script starts with a header: Jira key, object, author, date, description.

---

## 7. Repository layout

```
snowflake/
  <entity>/
    ddl/       01_stg_<entity>.sql  02_hist_<entity>.sql  03_prc_<entity>.sql
    procs/     sp_load_stg_<entity>.sql  sp_load_hist_<entity>.sql  sp_load_prc_<entity>.sql  sp_run_<entity>.sql
    tests/     ut_<entity>.sql    qa_<entity>.sql
    spec/      <entity>_column_spec.xlsx  (no data)
    README.md  entity notes, business key, extraction mode, JS7 job name
  common/      file formats, stages, masking policies, audit tables
```

---

## 8. Git and Jira

- Branch: `feature/<JIRA-KEY>-<short-desc>` (e.g. `feature/DATA-123-claim-detail-load`)
- Commit message: `<JIRA-KEY>: <imperative summary>` — enforced by `scripts/hooks/commit-msg`
- PR title starts with the Jira key; PR uses `.github/pull_request_template.md`.
- One Jira story ↔ one branch ↔ one PR.

---

## 9. Environments and deployment

| Env         | Who deploys                        | How                               |
| ----------- | ---------------------------------- | --------------------------------- |
| DEV         | Developer (via `/deploy-to-dev`) | Snowflake CLI, connection `dev` |
| TEST / PROD | Release pipeline only              | Never from an IDE or Copilot      |

Copilot agents may **read** metadata in any environment the developer's role can see, but may only **execute DDL/DML in DEV**.

---

## 10. Open questions (from the Understanding Document)

| # | Question                                                          | Owner | Decision |
| - | ----------------------------------------------------------------- | ----- | -------- |
| 1 | Begin/end dates: business validity or load timestamp?             |       |          |
| 2 | Business key per table                                            |       |          |
| 3 | Full vs delta; how are deletes handled?                           |       |          |
| 4 | Masking: policies or in procedures?                               |       |          |
| 5 | Internal or external stage; file naming and archiving             |       |          |
| 6 | Approach 2 sync mechanism (share, replication, cross-DB, streams) |       |          |
| 7 | Scheduling: JS7 confirmed — job naming and parameters?           |       |          |
| 8 | Error handling and audit table design                             |       |          |
| 9 | Naming conventions across dev/test/prod                           |       |          |
