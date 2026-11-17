---
applyTo: "snowflake/**/ddl/**/*.sql,snowflake/common/**/*.sql"
description: "Snowflake DDL rules for staging, history and processing tables"
---

# Snowflake DDL rules

## File header (required)
```sql
/*==============================================================================
  Jira       : <JIRA-KEY>
  Object     : <SCHEMA>.<TABLE>
  Layer      : STAGING | HISTORY | PROCESSING
  Author     : <name>
  Created    : <YYYY-MM-DD>
  Description: <one line from the ticket>
  Change log :
    <YYYY-MM-DD> <JIRA-KEY> <author> <change>
==============================================================================*/
```

## Rules
- Tables: `CREATE TABLE IF NOT EXISTS` (staging may be `CREATE TRANSIENT TABLE IF NOT EXISTS`). **Never `CREATE OR REPLACE TABLE`.**
- Column changes on existing tables: `ALTER TABLE … ADD COLUMN` scripts in a new numbered file — never drop and recreate a history table.
- Columns in the exact order of the Excel spec, one per line, trailing commas, with `COMMENT '<spec description>'`.
- Table `COMMENT` = entity description + Jira key.
- Declare `PRIMARY KEY (<business key>)` on staging and processing; on history the key is `(<business key>, BEGIN_EFFECTIVE_DATE)`.
- History: append the five tracking columns in this order and with these types:
  ```sql
      BEGIN_EFFECTIVE_DATE  TIMESTAMP_NTZ(9) NOT NULL COMMENT 'When this version became valid',
      END_EFFECTIVE_DATE    TIMESTAMP_NTZ(9) NOT NULL DEFAULT '9999-12-31 00:00:00'::TIMESTAMP_NTZ COMMENT 'When this version stopped being valid; 9999-12-31 for current',
      CURRENT_RECORD_IND    CHAR(1)          NOT NULL DEFAULT 'Y' COMMENT 'Y = current version, N = expired',
      LAST_UPDATE_USER      VARCHAR(100)     NOT NULL DEFAULT CURRENT_USER() COMMENT 'User that last wrote this row',
      LAST_UPDATE_DATE      TIMESTAMP_NTZ(9) NOT NULL DEFAULT CURRENT_TIMESTAMP()::TIMESTAMP_NTZ COMMENT 'When this row was last written'
  ```
- Processing: append `VALUATION_DATE DATE NOT NULL`, `LAST_UPDATE_USER`, `LAST_UPDATE_DATE`.
- Money: `NUMBER(p,s)`. Dates: `DATE`. Timestamps: `TIMESTAMP_NTZ(9)`. Strings keep spec length.
- Sensitive columns (spec `DATA_CLASS` not blank): add a `-- MASKING: UTIL.MP_<DATA_CLASS>` comment on the column and an `ALTER TABLE … MODIFY COLUMN … SET MASKING POLICY` statement at the end of the file, for staging, history and processing tables in a separate file `ddl/04_masking_<entity>.sql`.
- Never reference a hard-coded database. Schema-qualify with `STG.`, `HIST.`, `PRC.`, `UTIL.`, `AUDIT.` only.
- Follow the reference implementation `snowflake/claim_detail/ddl/` file for file. Columns come only from the column spec (the `/jira-ticket` skill converts the xlsx attachment to `.jira/<KEY>/attachments/*.md`).
