---
name: snowflake-masking
description: Protect PII/PHI columns with the team's Snowflake masking policies - map sensitivity rules to data classes, attach UTIL.MP_* policies, add a new policy, and verify masking without exposing values. Use whenever a spec or ticket mentions sensitive, PII, PHI, SSN, DOB or masking.
---

# Masking sensitive data

Policies: `snowflake/common/03_masking_policies.sql`. Per-entity attachment: `snowflake/<e>/ddl/04_masking_<e>.sql`. Reference: `snowflake/claim_detail/ddl/04_masking_claim_detail.sql`.

## Data classes
| DATA_CLASS | Policy | Input type | Masked output |
|---|---|---|---|
| SSN | `UTIL.MP_SSN` | VARCHAR | `XXX-XX-1234` |
| DOB | `UTIL.MP_DOB` | DATE | Jan 1 of the year |
| EMAIL | `UTIL.MP_EMAIL` | VARCHAR | `*****@domain` |
| PHONE | `UTIL.MP_PHONE` | VARCHAR | `***-***-1234` |
| NAME | `UTIL.MP_NAME` | VARCHAR | `*** MASKED ***` |
| ADDRESS | `UTIL.MP_ADDRESS` | VARCHAR | `*** MASKED ***` |
| GENERIC | `UTIL.MP_GENERIC` | VARCHAR | SHA-256 (joinable) |

## Rules
1. Sensitivity comes from the business's sensitivity rules (often a Word or Excel attachment on the ticket; `/jira-ticket` converts it to text) → `DATA_CLASS` in the spec. If a column looks sensitive but isn't marked, **ask** — don't decide alone.
2. Attach to **staging, history and processing** (`… SET MASKING POLICY … FORCE` so the script re-runs).
3. Policy input type must equal the column type. A `TIMESTAMP` DOB needs a `MP_DOB_TS` variant — add it to the common file, don't inline a policy in an entity script.
4. Every policy returns clear values for `<LOAD_ROLE>` (JS7 loads) — otherwise SCD2 hashes and stores masked data.
5. Policies are `CREATE … IF NOT EXISTS`; change a body with `ALTER MASKING POLICY … SET BODY ->`.
6. Never print, test or paste clear values. Synthetic data only.

## Verify (counts only, never values)
```sql
-- policies attached
SELECT REF_ENTITY_NAME, REF_COLUMN_NAME, POLICY_NAME
FROM TABLE(INFORMATION_SCHEMA.POLICY_REFERENCES(REF_ENTITY_NAME => 'HIST.<E>_HIST', REF_ENTITY_DOMAIN => 'TABLE'));

-- as a non-privileged role: no clear SSNs visible
USE ROLE <ANALYST_ROLE>;
SELECT COUNT_IF(MEMBER_SSN NOT LIKE 'XXX-XX-%') AS CLEAR_VALUES_VISIBLE FROM PRC.<E>;   -- expect 0
```
