---
status: draft  # draft -> approved (only after a human says so in chat) -> created (set by the script)
summary: TODO <ENTITY>: <what is built, in one line, max 255 chars>
project:  # leave empty to use default_project from config/jira.config.json
issue_type: Story
parent:  # epic / feature key, e.g. DATA-120, or empty
labels: [snowflake]
components: []
priority:
story_points:
attachments: []  # populated after issue creation; repo-relative paths or absolute shared/local paths
sources: []  # every input file the story was written from
jira_key:
jira_url:
---

# TODO <same text as summary>

<!--
How to use this template (comments are stripped before the story goes to Jira):
- Every fact comes from a source file. Cite it in brackets: [spec.xlsx › Column Spec], [requirements.docx › 3.2].
- Never guess. Unknown values are written "⚠ TBC" and listed in Open questions with an owner.
- Delete a conditional section only when it truly does not apply, and say why in Out of scope.
- Replace every TODO. The create script refuses a draft that still has one.
-->

# Description

## Context / Why

<!-- The problem, in business terms: who needs the data, what they cannot do today, what changes when this ships. 2–5 sentences. -->
TODO

## Source

<!-- Pick the approach and fill the rows that apply. Approach 1 = file-based (CSV → stage). Approach 2 = Snowflake-to-Snowflake (direct data share / other database). -->

| Item | Value |
|---|---|
| Approach | TODO 1, file-based ingestion / 2, Snowflake-to-Snowflake |
| Source object(s) | TODO file name pattern, or `<SHARE>.<SCHEMA>.<TABLE>` |
| Arrives / available | TODO e.g. Calendar Day 1 by 09:00 |
| Format | TODO CSV delimiter, header, quoting, encoding (Approach 1 only) |
| Load type | TODO SNAPSHOT (whole table every run) / DELTA (changed rows only) |
| Business key | TODO columns that identify a record |
| Stage / file format | TODO `UTIL.STG_<ENTITY>`, `UTIL.FF_CSV_STANDARD` (Approach 1 only) |

## Scope

<!-- One row per object. Follow the naming of snowflake/claim_detail/ and docs/STANDARDS.md. -->

| # | Layer | Object type | Name | Repo file | Purpose |
|---|---|---|---|---|---|
| 1 | Staging | Table | TODO `STG.<ENTITY>_STG` | `ddl/01_stg_<entity>.sql` | Raw copy of each load. Business columns only |
| 2 | History | Table | TODO `HIST.<ENTITY>_HIST` | `ddl/02_hist_<entity>.sql` | Every version (Type 2). Business columns + 5 tracking columns |
| 3 | Processing | Table | TODO `PRC.<ENTITY>` | `ddl/03_prc_<entity>.sql` | Latest version only, with `VALUATION_DATE` |
| 4 | Security | Masking | TODO | `ddl/04_masking_<entity>.sql` | Mask sensitive columns |
| 5 | Load | JavaScript procedure | TODO `UTIL.SP_LOAD_STG_<ENTITY>(...)` | `procs/...` | TODO |
| 6 | History | JavaScript procedure | TODO `UTIL.SP_LOAD_HIST_<ENTITY>(P_VALUATION_DATE VARCHAR)` | `procs/...` | Type 2 merge, rerun safe |
| 7 | Processing | JavaScript procedure | TODO `UTIL.SP_LOAD_PRC_<ENTITY>(P_VALUATION_DATE VARCHAR)` | `procs/...` | Delete, insert current history rows |
| 8 | Orchestration | JavaScript procedure | TODO `UTIL.SP_RUN_<ENTITY>(...)` | `procs/...` | Single entry point JS7 calls |

## Out of scope

- TODO what this story deliberately does not do (other entities, PROD deployment, JS7 job definition, archiving…)

## Column specification

<!-- From the Excel column spec. Keep every column, in spec order. Over ~40 columns: list the key, compare and masked columns here and attach the workbook. -->

| # | Column | Type | Null? | Key | Compare for change | Mask | Source format / rule |
|---|---|---|---|---|---|---|---|
| 1 | TODO | | | | | | |

**History tracking columns, after the business columns:** `BEGIN_EFFECTIVE_DATE DATE`, `END_EFFECTIVE_DATE DATE`, `CURRENT_RECORD_IND VARCHAR(1)`, `LAST_UPDATE_USER VARCHAR(100)`, `LAST_UPDATE_DATE TIMESTAMP_NTZ(9)`.

**Processing columns, after the business columns:** `VALUATION_DATE DATE`, `LAST_UPDATE_USER VARCHAR(100)`, `LAST_UPDATE_DATE TIMESTAMP_NTZ(9)`.

## Load rules

<!-- Numbered LR-n so tests and code can cite them. Cover: staging, changed key, new key, key missing from source, unchanged key, rerun of the same valuation date, processing, audit columns. -->

Let `VD` be the valuation date passed to the run.

1. **LR-1 Staging:** TODO
2. **LR-2 Changed key:** TODO
3. **LR-3 New key:** TODO
4. **LR-4 Key missing from source:** TODO
5. **LR-5 Unchanged key:** TODO
6. **LR-6 Rerun of the same VD:** TODO
7. **LR-7 Processing:** TODO

## Data validation (DVF)

<!-- Rules that stop the run before history is touched. Each one testable as a query. -->

| ID | Rule | Fails when |
|---|---|---|
| DVF-1 | Source has rows | TODO |
| DVF-2 | No duplicate business keys | TODO |

## Masking

<!-- Sensitive columns from the sensitivity rules, the policy each one uses, and on which tables. Write "None: no sensitive columns in the spec" if so. -->
TODO

## Scheduling and completion message

<!-- JS7 job name, calendar, the CALL it makes, and the exact completion message. -->
TODO

# Acceptance criteria

<!-- Given/When/Then, one per line, numbered AC-n, each checkable with a query or a count. Use concrete keys and numbers from the test data when the sources give them. -->

- [ ] **AC-1 Objects:** Given TODO, when TODO, then TODO.

## Dependencies / links

- Shared folder: TODO shared-folder path to reference, or `none`
- TODO related stories, source documents, access needed (stage, share, roles)

## Decision log

<!-- Decisions already made by the PO/BA, with who and when. Empty is fine for a new story. -->

| Date | Decision | By | Source |
|---|---|---|---|
| | | | |

## Open questions

<!-- Every ⚠ TBC above appears here with an owner. -->

| # | Question | Owner | Blocks |
|---|---|---|---|
| 1 | | | |

## Definition of Ready

<!-- The agent fills ✔ / ✘ and says why for each ✘. -->

- [ ] Context, scope and out of scope are clear
- [ ] Source, business key and load type (snapshot / delta) are known
- [ ] Column spec is complete (types, nullability, compare columns, masking)
- [ ] Acceptance criteria are specific and testable
- [ ] Test data is identified
- [ ] Open questions are resolved or assigned
- [ ] Estimate and priority are recorded

## Definition of Done

- [ ] All acceptance criteria verified in DEV, with evidence attached to the story
- [ ] Code in `snowflake/<entity>/` on a `feature/<KEY>-<entity>` branch, PR reviewed by Copilot code review and a human, and merged
- [ ] Commits reference the Jira key
- [ ] README in the entity folder lists the objects, the run command and the rerun steps

## Attachment file path

- [ ] Path for attachment, points to the local shared drive