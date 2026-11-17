---
name: scd2-history-load
description: How the team loads history tables as SCD Type 2 (expire changed versions, insert new versions, SNAPSHOT vs DELTA deletes, idempotent re-runs). Use when writing, changing, reviewing or debugging a SP_LOAD_HIST procedure or a history table.
---

# SCD Type 2 history load

**Reference implementation:** `snowflake/claim_detail/procs/sp_load_hist_claim_detail.sql` (SNAPSHOT). Copy its structure for every new history procedure. For DELTA, drop step 1b.
Table DDL: `snowflake/claim_detail/ddl/02_hist_claim_detail.sql`.

## The five tracking columns
`BEGIN_EFFECTIVE_DATE`, `END_EFFECTIVE_DATE` (`9999-12-31 00:00:00` while current), `CURRENT_RECORD_IND` (`Y`/`N`), `LAST_UPDATE_USER`, `LAST_UPDATE_DATE`. Intervals are half-open: an expired row's END equals the next version's BEGIN.

## Algorithm (one transaction)
```
EFFECTIVE_TS := CURRENT_TIMESTAMP (captured once)
guard: no duplicate keys in STG, no NULL keys          -> else throw
1.  UPDATE HIST set END=EFFECTIVE_TS, IND='N'
      where IND='Y' and key matches STG and HASH(non-key cols) differs
1b. SNAPSHOT only: UPDATE HIST set END=EFFECTIVE_TS, IND='N'
      where IND='Y' and key NOT in STG               (source delete)
2.  INSERT into HIST from STG with BEGIN=EFFECTIVE_TS, END=9999-12-31, IND='Y'
      where key has no IND='Y' row                   (new keys + keys expired in 1)
```
Why this order: after step 1 a changed key has no current row, so step 2's single `NOT EXISTS` covers both new and changed keys. Unchanged keys are never touched, so a retry of the same run changes nothing (idempotent).

## Change detection
- NULL-safe hash: `SHA2(CONCAT_WS('|~|', COALESCE(TO_VARCHAR(col), '~N~'), …), 256)` over **non-key** columns, identical column order on both sides.
- Never compare with plain `=` column by column — `NULL = NULL` is not true and changes to/from NULL are missed.
- Exclude columns the ticket says should not create a new version (e.g. technical load timestamps from the source) — note it in the procedure header.

## SNAPSHOT vs DELTA
| | SNAPSHOT | DELTA |
|---|---|---|
| Staging holds | the whole source table | only this month's records |
| Key missing from staging | expire it (step 1b) — CONFIRM | **do nothing** |
| Processing filter | all current rows | current rows whose delta date is in the valuation month |

## Masking gotcha
Load procedures run `EXECUTE AS CALLER`. If the load role is masked by a policy, the hash and the inserted values are the **masked** ones — silent data corruption. Every `UTIL.MP_*` policy must return clear values for the load role.

## Common review findings
- `CREATE OR REPLACE TABLE` on history → BLOCKER.
- INSERT before UPDATE → new versions get expired in the same run.
- Join in step 1 that duplicates rows (non-unique staging key) → guard exists for this; don't remove it.
- Using `CURRENT_TIMESTAMP()` separately in each statement → END and BEGIN don't line up.
- Using `MERGE` with both `WHEN MATCHED THEN UPDATE` and an insert of the new version: one MERGE cannot both expire and insert for the same key — keep the two-statement pattern.

## Diagnosing a bad history table
```sql
-- keys with more than one current row
SELECT <key>, COUNT(*) FROM HIST.<E>_HIST WHERE CURRENT_RECORD_IND = 'Y' GROUP BY <key> HAVING COUNT(*) > 1;
-- version timeline for one key (synthetic/test key only)
SELECT <key>, BEGIN_EFFECTIVE_DATE, END_EFFECTIVE_DATE, CURRENT_RECORD_IND, LAST_UPDATE_DATE
FROM HIST.<E>_HIST WHERE <key> = '<test key>' ORDER BY BEGIN_EFFECTIVE_DATE;
```
