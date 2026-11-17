---
name: file-ingestion
description: Load a staging table - business CSV files from a Snowflake stage with COPY INTO (Approach 1), or a Snowflake source table with INSERT...SELECT (Approach 2). Covers file formats, date/time format rules, file patterns, error handling and re-runs. Use when writing or fixing a SP_LOAD_STG procedure or when a COPY INTO fails.
---

# File ingestion (staging load)

**Reference implementation:** `snowflake/claim_detail/procs/sp_load_stg_claim_detail.sql`. Copy its structure (header, standard helpers block, audit, transaction, return object) for every new staging procedure.
Common objects: `snowflake/common/02_file_formats_and_stages.sql`.

## Approach 1: CSV via stage

### Pattern
```
DELETE FROM STG.<E>                       -- staging holds one run only
COPY INTO STG.<E> (col1, …, colN)
FROM (SELECT $1, TO_DATE($2,'MM/DD/YYYY'), … FROM @UTIL.STG_<E>)
FILE_FORMAT = (FORMAT_NAME = 'UTIL.FF_CSV_STANDARD')
PATTERN = '.*<E>_20261031.*[.]csv'        -- built from the validated run date
ON_ERROR = ABORT_STATEMENT
FORCE = TRUE                              -- retry must reload the same file
```

### Rules
- **Column mapping is positional** (`$1..$n`) in spec order. If the file's column order differs from the spec, map explicitly and say so in the header.
- Apply each field's **format rule** in the `SELECT`: `TO_DATE($n,'fmt')`, `TO_TIMESTAMP_NTZ($n,'fmt')`, `TO_NUMBER($n, 18, 2)` for amounts with thousand separators (`REPLACE($n, ',', '')` first).
- `ON_ERROR = ABORT_STATEMENT` is the default. Using `CONTINUE` requires a check of rejected rows (`VALIDATE(STG.<E>, JOB_ID => '_last')`) and a ticket decision.
- `FORCE = TRUE` + a date-specific `PATTERN` keeps re-runs idempotent. Never `FORCE = TRUE` without a pattern (would reload every file in the stage).
- COPY options don't accept binds, so the pattern is concatenated — **only** from the regex-validated run date. Never from free-text input.
- Zero rows loaded fails the run unless the ticket says empty files are valid (`ALLOW_EMPTY`).
- Archiving/purging files after load: open question 5 — don't add `PURGE = TRUE` until confirmed.

### Checking before you build (DEV, read-only)
```sql
LIST @UTIL.STG_<E> PATTERN = '.*<E>_.*[.]csv';
SELECT $1, $2, $3 FROM @UTIL.STG_<E> (FILE_FORMAT => 'UTIL.FF_CSV_STANDARD', PATTERN => '.*<E>_20261031.*[.]csv') LIMIT 5;  -- synthetic files only
COPY INTO STG.<E> FROM @UTIL.STG_<E> PATTERN = '…' VALIDATION_MODE = RETURN_ERRORS;   -- dry run, loads nothing
```

### Troubleshooting
| Error | Likely cause |
|---|---|
| `Number of columns in file does not match` | file has extra/fewer columns than the spec; check delimiter and quotes |
| `Can't parse '…' as date` | wrong format string; check the spec's format rule |
| `0 files processed` | pattern doesn't match the file name, or wrong stage path |
| loads 0 rows on retry | `FORCE = TRUE` missing (load metadata skips files already loaded) |

## Approach 2: Snowflake source (short version)
Same procedure shape; replace the COPY with an `INSERT … SELECT` from the source table.
```sql
DELETE FROM STG.<E>;
INSERT INTO STG.<E> (col1, …, colN)
SELECT SRC.col1, …, SRC.colN                      -- explicit list, never SELECT *
FROM <SOURCE_DB>.<SCHEMA>.<TABLE> SRC
[WHERE SRC.<delta_date> BETWEEN DATE_TRUNC('MONTH', ?::DATE) AND LAST_DAY(?::DATE)]   -- DELTA only, bound
```
- Keep the source object name in one constant at the top of the procedure (names differ per environment).
- Compare the source definition with the spec first (`DESC TABLE …`) and report type or length differences before writing code.
- The sync mechanism for Approach 2 is still an open question. If it turns out to be streams, ask before building.

