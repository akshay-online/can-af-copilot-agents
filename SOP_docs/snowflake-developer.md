# Snowflake developer SOP

## Purpose and scope

Generate Snowflake DDL, JavaScript load procedures, and validation SQL for one agreed Jira Story. The pattern is source to staging, SCD2 history, then processing, orchestrated externally by JS7. The agent does not connect to Snowflake, execute SQL, or deploy.

## Prerequisites and inputs

- Complete [local setup](../README.md#clone-and-configure-locally); Jira credentials are not required when inputs are supplied locally.
- Supply the Jira key, `.jira/<KEY>/brief.md` when available, acceptance criteria, column specifications, and relevant attachments.
- Confirm business key, source approach, extraction mode, missing-key behavior, formats/patterns, sensitivity policies, source/stage/file-format contracts, audit interface, and load role.
- Read [technical standards](../.github/STANDARDS.md), [DDL rules](../.github/instructions/snowflake-ddl.instructions.md), [procedure rules](../.github/instructions/snowflake-js-procedures.instructions.md), and [review rules](../.github/instructions/code-review.instructions.md).

## Copilot harness

1. Select **snowflake-developer** in Chat; its definition filename is `snow-dev.agent.md`.
2. No dedicated developer prompt file is provided. Paste the request below with real inputs.
3. The agent loads [file-ingestion](../.github/skills/file-ingestion/SKILL.md), [scd2-history-load](../.github/skills/scd2-history-load/SKILL.md), and [snowflake-masking](../.github/skills/snowflake-masking/SKILL.md) as relevant. For Word/Excel inputs, it uses [spec-file-conversion](../.github/skills/spec-file-conversion/SKILL.md). If discovery is unavailable, explicitly request these files be read.
4. Resolve missing decisions and approve the proposed file/code plan before project changes.
5. Review generated files and local validation results. Continue only within the approved Story; database execution remains out of scope.

Example request:

```text
Use snowflake-developer for <JIRA-KEY>, entity <entity>.
Read .jira\<JIRA-KEY>\brief.md and the supplied column specifications.
Load the applicable standards and ingestion/history/masking skills.
Identify missing contracts and show a plan for approval before changing files.
Do not connect to Snowflake, execute SQL, or deploy.
```

## Local agent harness

1. Select VS Code Chat's **Local** harness, then **snowflake-developer**.
2. Paste the example below; there is no `/dev` prompt supplied by this repository.
3. Confirm local file/edit/question/terminal access. Load the same applicable skills and standards; local tools do not authorize database access.
4. Check the proposed target files and explicitly approve changes. Existing files must be preserved; ask before replacing or changing them.
5. Inspect local review results, gaps, and manual checks before handing code to the team's release process.

Example request:

```text
Work on one Story only: <JIRA-KEY>. My brief is .jira\<JIRA-KEY>\brief.md.
Use repository standards and the relevant Snowflake skills. Ask about any
conflicting return signatures, audit schemas, source contracts, or delete rules.
Show the plan first. Generate only approved files and safe validation SQL.
No Snowflake connection or execution.
```

## Outputs and completion checks

Only scoped files are created under the future `snowflake/<entity>/` layout:

| Area | Expected result |
|---|---|
| `ddl/` | Staging/history/processing DDL, plus approved masking attachments where needed |
| `procs/` | Relevant staging/history/processing procedures and orchestrator |
| `tests/` | Safe validation SQL mapped to Story acceptance criteria |
| Entity `README.md` | Key, source approach, extraction mode, dependencies, run notes |

Verify column names/types/order against the specification; tracking columns, transactions and failure propagation against confirmed contracts; idempotency and SNAPSHOT/DELTA rules against requirements; and sensitivity checks without exposing values. Report local checks actually run and any checks unavailable. A generated SQL file is not proof of Snowflake runtime correctness.

## Troubleshooting and limitations

| Situation | Required action |
|---|---|
| Brief absent | Supply it and the specifications; no `jira-ticket` fetch skill is provided |
| `snowflake/claim_detail/` or common definitions absent | Use available standards only where unambiguous; ask for missing implementation contracts |
| Standards disagree on `UTIL` versus `ETL`, return type, or audit contract | Stop and obtain the owner's decision; do not silently choose |
| SNAPSHOT missing-key behavior not confirmed | Ask; DELTA must not expire keys absent from the delta |
| No local SQL validator | Report static review only; do not connect to Snowflake as a substitute |
| Deployment requested | Explain this agent's no-execution boundary; use the team's separately approved release process |

The kit has no bundled deployment, unit-test agent, or ticket-fetch command. [Guardrails](guardrails.md) are an additional runtime-dependent layer, not permission to execute SQL.

## References

- [Snowflake developer definition](../.github/agents/snow-dev.agent.md)
- [Technical standards](../.github/STANDARDS.md)
- [Story-writer SOP](story-writer.md)
- [Repository overview](../README.md)
