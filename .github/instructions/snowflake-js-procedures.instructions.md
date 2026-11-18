---
applyTo: "snowflake/**/procs/**/*.sql"
description: "Rules for Snowflake JavaScript stored procedures (load, history, processing, orchestrator)"
---

# Snowflake JavaScript stored procedure rules

Follow [the technical standards](../STANDARDS.md) and start every procedure from the matching procedure in `snowflake/claim_detail/procs/` when present. Copy the **standard helpers block** (`RESULT`, `exec`, `scalar`, `audit`, `validateRunDate`, `fail`) unchanged when available; do not introduce a second SQL-execution or audit pattern. If the reference is absent, follow the available rules and ask for any missing source/audit contracts before coding.

## File header

Every procedure file starts with the repository's SQL comment header, following the reference procedure. Include the Jira key, object name, layer, author, creation date, description, parameters, and a change log. Keep the Jira key in the procedure's Snowflake `COMMENT` as well. Do not substitute a different header template or add environment database names.

## Signature
```sql
CREATE OR REPLACE PROCEDURE UTIL.SP_LOAD_<LAYER>_<ENTITY>(
    P_RUN_DATE   VARCHAR,     -- 'YYYY-MM-DD'; drives VALUATION_DATE = LAST_DAY(P_RUN_DATE)
    P_RUN_ID     VARCHAR      -- JS7 order id, for audit correlation
)
RETURNS VARIANT
LANGUAGE JAVASCRIPT
EXECUTE AS CALLER
COMMENT = '<JIRA-KEY>: <purpose>'
AS
$$
    // JavaScript body
$$;
```

## Body rules
1. Read procedure parameters in **UPPERCASE** (`P_RUN_DATE`), regardless of how they were declared.
2. Use the shared `exec(sqlText, binds)` helper for SQL statements in procedure logic. It records query IDs and returns the statement/result set. Use `scalar` for single-value queries. Do not scatter direct `snowflake.execute` calls through the body.
3. **Bind every data value** with `binds: [...]`; never concatenate parameter or row values into SQL. Dynamic object names, if genuinely needed, use `IDENTIFIER(?)`. Static procedure names in the orchestrator may come from a hard-coded constant list only.
4. Validate run-date parameters before deriving file paths or using them in SQL. Keep the business work inside `BEGIN TRANSACTION` / `COMMIT`; on failure, use the shared `fail(err)` helper to roll back, write the `FAILED` audit row, and re-throw so JS7 sees the failure.
5. Write `STARTED` and terminal `SUCCEEDED` / `FAILED` rows to `AUDIT.LOAD_LOG` **outside** the business transaction, so rollback does not erase audit records. Use the shared `audit` helper and do not log sensitive values.
6. Track DML row counts using statement methods (`getNumRowsInserted()`, `getNumRowsUpdated()`, `getNumRowsDeleted()`) or the reference pattern for `MERGE`. Record query IDs through `exec`.
7. Return the standard result object: `{status, procedure, entity, run_id, valuation_date, rows_inserted, rows_updated, rows_deleted, query_ids, error}`. Keep field names and meaning consistent with the reference.
8. Use explicit column lists in production SQL and match the DDL order. Never use `SELECT *`.
9. No `console.log`, `eval`, or network calls.

## Layer-specific logic
- **Staging (Approach 1 — files):** `DELETE FROM STG.<ENTITY>` → `COPY INTO STG.<ENTITY> (cols) FROM (SELECT $1, $2 … FROM @UTIL.STG_<…>) FILE_FORMAT = (FORMAT_NAME = UTIL.FF_CSV_…) PATTERN = '<validated pattern>' ON_ERROR = ABORT_STATEMENT`. Apply the spec's date/time and null/normalization rules in the `SELECT`. `COPY INTO` options such as `PATTERN` do not accept bind placeholders: validate the run date against the expected format, then construct the pattern only from that validated date. Use `FORCE = TRUE` when staging is emptied before each run so retries reload the file. After `COPY INTO`, count staging rows with `SELECT COUNT(*)`; do not rely on a `rows_loaded` result column. See skill `file-ingestion`.
- **Staging (Approach 2 — Snowflake source):** `DELETE FROM STG.<ENTITY>` → `INSERT INTO STG.<ENTITY> (cols) SELECT cols FROM <SHARE_DB>.<SCHEMA>.<TABLE> [WHERE <delta filter>]`. See skill `file-ingestion` (Approach 2 section).
- **History:** follow skill `scd2-history-load`. In one transaction, expire changed current versions using a hash of all non-key business columns, expire missing keys only when the ticket's SNAPSHOT/DELTA rules require it, then insert current versions for new and changed keys. Validate staging business keys as in the reference so duplicates or NULL keys cannot create invalid current versions. Keep effective dates and tracking columns consistent with [the technical standards](../STANDARDS.md).
- **Processing:** `DELETE FROM PRC.<ENTITY> WHERE VALUATION_DATE = ?` → `INSERT … SELECT … FROM HIST.<ENTITY>_HIST WHERE CURRENT_RECORD_IND = 'Y'` (plus the month filter the ticket defines).
- **Orchestrator `SP_RUN_<ENTITY>`:** call staging, history, then processing in that order. Bind procedure arguments, stop on the first failure, and return the result from each layer. Do not add scheduling logic; JS7 calls the orchestrator.
