# Copilot instructions — Snowflake Data Engineering team

You are helping a data-engineering team build Snowflake tables and Snowflake JavaScript stored procedures that load business data through a **staging → history (SCD Type 2) → processing** model. The full rules live in `docs/STANDARDS.md`; read it when a task touches DDL, procedures, masking, tests or deployment.

## What this repo contains
- `snowflake/<entity>/ddl/` — SQL DDL for the three tables of each entity
- `snowflake/<entity>/procs/` — Snowflake JavaScript stored procedures (one per layer + one orchestrator)
- `snowflake/<entity>/tests/` — unit-test (`ut_`) and QA (`qa_`) SQL scripts
- `snowflake/<entity>/spec/` — the business's Excel column spec for the entity
- `snowflake/common/` — file formats, stages, masking policies, audit tables
- JS7 jobs call the `SP_RUN_<ENTITY>` orchestrator; procedures never schedule themselves.

## Always
- Work from a **Jira ticket**. If the user has not given a Jira key, ask for it. Put the key in file headers, commit messages and PR titles.
- Get ticket details from `.jira/<KEY>/brief.md`. If it doesn't exist, use the `jira-ticket` skill (Jira REST API). There is no Jira or Snowflake MCP server in this setup.
- Follow the reference implementation in `snowflake/claim_detail/` for file layout, headers and procedure structure.
- Treat the **Excel column spec** as the source of truth for column names, types, lengths, order and descriptions. Do not invent columns.
- Use UPPER_SNAKE_CASE unquoted identifiers. Never hard-code an environment database name.
- History tables carry, in order: `BEGIN_EFFECTIVE_DATE`, `END_EFFECTIVE_DATE`, `CURRENT_RECORD_IND`, `LAST_UPDATE_USER`, `LAST_UPDATE_DATE`.
- Processing tables carry: `VALUATION_DATE`, `LAST_UPDATE_USER`, `LAST_UPDATE_DATE`.
- Open-ended end date is `'9999-12-31 00:00:00'`. Exactly one `CURRENT_RECORD_IND = 'Y'` per business key.
- In JavaScript procedures: bind every value (`binds: [...]`), wrap work in a transaction, log to `AUDIT.LOAD_LOG`, return a JSON status object, re-throw on error.
- Make every script re-runnable.
- When something in the ticket or spec is ambiguous (business key, extraction mode, sensitive columns), **stop and ask** rather than guess. Say which assumption you would make.

## Never
- Never use `CREATE OR REPLACE TABLE` on a history table or any table holding data.
- Never concatenate parameter values into SQL strings.
- Never use `SELECT *` in procedures or production SQL.
- Never ask for, print or store a Jira API token or Snowflake password in chat or in files other than the developer's own `.env` / `~/.snowflake/connections.toml`.
- Never put real PII/PHI (names, SSNs, dates of birth, addresses, policy holders' details) in code, tests, comments, commits or chat. Use synthetic values.
- Never run DDL or DML against any environment except DEV. TEST and PROD are deployed by the release pipeline only.
- Never use `FLOAT`/`DOUBLE` for money.

## Team agents, prompts and skills
- Prompt: `/jira-ticket <KEY>` pulls and summarises a ticket (skill `jira-ticket`).
- Agents: `/dev` build · `/unit-test` validation from AC · `/QA` data checks · `/review` pre-PR standards check · `/deploy-to-dev` · `/dependency-analysis` · `/impact-analysis`. They live in `.github/agents/`, each with a matching prompt in `.github/prompts/`.
- Skills (`.github/skills/`): `jira-ticket`, `file-ingestion`, `scd2-history-load`, `snowflake-masking`, `snowflake-deploy`.

## Response style
- Show the plan first for any change that touches more than one file.
- Produce complete files, not fragments, when creating DDL or procedures.
- End with a short checklist of what the developer must verify by hand.
