---
applyTo: "**/*.sql"
excludeAgent: "coding-agent"
description: "Review rules used by Copilot code review on pull requests"
---

# Copilot code review — Snowflake team rules

Review every changed SQL file against these rules. Label each comment **[BLOCKER]**, **[MAJOR]** or **[MINOR]**, cite the rule, and suggest the fix as a code suggestion where possible.

## BLOCKER
- `CREATE OR REPLACE TABLE` on any table that holds data (especially `HIST.*`).
- A value concatenated into a SQL string inside a JavaScript procedure (`"… WHERE x = '" + P_X + "'"`). Must use `binds`.
- `DROP TABLE`, `TRUNCATE` or `DELETE` without a `WHERE` on `HIST.*` tables.
- Hard-coded database names (`POLICY_PRD.`, `*_PRD`, `*_PROD`) or `USE ROLE ACCOUNTADMIN`.
- Real-looking PII/PHI in code, tests or comments (SSN patterns `\d{3}-\d{2}-\d{4}`, emails, full names with dates of birth).
- A column marked sensitive in the spec with no masking policy attached in history/processing DDL.
- Procedure with no `ROLLBACK` in its `catch`, or that swallows the error instead of re-throwing.

## MAJOR
- History table missing any of the five tracking columns, or in the wrong order/type.
- Processing table missing `VALUATION_DATE`, `LAST_UPDATE_USER`, `LAST_UPDATE_DATE`.
- SCD2 logic that can leave more than one `CURRENT_RECORD_IND = 'Y'` row per business key (e.g. INSERT before UPDATE outside a transaction, or a join that duplicates keys).
- Change detection that ignores NULL-to-value changes (comparing columns with `=` without `COALESCE`/`IS DISTINCT FROM` or hashing).
- DELTA entity whose history load expires keys missing from staging (deletes history it shouldn't).
- No `AUDIT.LOAD_LOG` writes; no row counts in the return object.
- `SELECT *` in procedures or DDL views.
- `FLOAT`/`DOUBLE` for amounts; `TIMESTAMP_LTZ`/`TZ` where the standard is `TIMESTAMP_NTZ`.
- Script not re-runnable (fails or duplicates data on a second run).
- Acceptance criteria in the linked ticket with no matching test in `tests/ut_<entity>.sql`.
- Missing header (Jira key, author, description) on a new file.

## MINOR
- Formatting: lowercase keywords, one-line column lists, leading commas, missing column comments.
- Naming not matching `docs/STANDARDS.md` §2.
- Long procedures (> ~300 lines) that should be split per layer.

## Performance notes (comment, don't block)
- `MERGE`/`UPDATE` joins on non-key columns; functions on join keys that prevent pruning.
- `COPY INTO` without `PATTERN` against a busy stage; `ON_ERROR = CONTINUE` without a rejected-rows check.
- `ORDER BY` in an `INSERT … SELECT`.

## Don't comment on
- Style choices already allowed by `docs/STANDARDS.md`.
- Files under `docs/` or `.github/` unless they contain secrets.
