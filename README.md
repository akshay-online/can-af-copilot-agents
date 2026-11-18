# Snowflake agent kit

Reusable VS Code agents for turning Snowflake specifications into Features and Stories and generating Snowflake code for review. Jira operations use the repository's Python REST client, not a Jira MCP server.

## Start here

| I want to... | Start with |
|---|---|
| Understand specifications and propose a capability breakdown | [Feature-writer SOP](SOP_docs/feature-writer.md) |
| Agree a Story map and draft Jira Stories | [Story-writer SOP](SOP_docs/story-writer.md) |
| Build code for one agreed Jira Story | [Snowflake developer SOP](SOP_docs/snowflake-developer.md) |
| Understand approvals, hook behavior, and limitations | [Guardrails reference](SOP_docs/guardrails.md) |

## Available agents

Select agents using their declared names in the VS Code agent picker; filenames and prompt names are not always the same.

| Agent | Purpose and inputs | Outputs | Boundaries | SOP |
|---|---|---|---|---|
| [feature-writer](.github/agents/feature-writer.agent.md) | Analyze Snowflake requirements; agree capability boundaries, dependencies, and gaps | Feature plan, Feature drafts; optionally approved Jira Features and confirmed parent changes | No implementation or Story creation; Jira creation requires separate content and target gates | [Use Feature-writer](SOP_docs/feature-writer.md) |
| [story-writer](.github/agents/story-writer.agent.md) | Read specifications or continue from a Feature; agree Story count and scope | Story map, concise drafts; optionally approved Jira Stories and confirmed original-file attachments | Writes drafts only under `.jira/drafts/`; each Story has its own gates | [Use Story-writer](SOP_docs/story-writer.md) |
| [snowflake-developer](.github/agents/snow-dev.agent.md) | Implement one Story from a supplied brief, column specifications, and confirmed contracts | DDL, JavaScript load procedures, validation SQL, entity README as scoped | Plan approval before code; no Snowflake execution or deployment | [Use Snowflake developer](SOP_docs/snowflake-developer.md) |

## Repository structure

| Path | Contents |
|---|---|
| [README.md](README.md) | Repository overview, setup, agent catalog, and navigation |
| [SOP_docs/](SOP_docs/) | One SOP per agent plus shared documentation and guardrail references |
| [.github/copilot-instructions.md](.github/copilot-instructions.md) | Shared workflow rules and default-agent routing |
| [.github/agents/](.github/agents/) | Agent definitions |
| [.github/prompts/](.github/prompts/) | Reusable prompt entry points |
| [.github/skills/](.github/skills/) | Reusable workflow instructions, templates, and helper scripts |
| [.github/STANDARDS.md](.github/STANDARDS.md) | Snowflake technical standards, including decisions still marked for confirmation |
| [.github/instructions/](.github/instructions/) | DDL, procedure, and SQL review rules |
| [.github/hooks/](.github/hooks/) | Pre-tool guardrail policy, implementation, and offline tests |
| [config/](config/) | Jira configuration and its non-secret example |
| [scripts/](scripts/) | Word/Excel converters and conversion dependencies |

Local working areas include `docs/` (business specifications), `.jira/` (drafts and ticket briefs), `.venv/`, and `logs/` (hook approval state). The latter three are ignored by Git. `docs/` is not ignored: check confidentiality before adding any business specifications to Git. `snowflake/<entity>/` is the development agent's target layout, not a supplied reference implementation.

## Clone and configure locally

### Prerequisites

- Git and VS Code with a signed-in GitHub Copilot account and agent support.
- A working Python 3 interpreter and `pip`. Use a Python version supported by the conversion dependencies; this repository does not declare a tested minimum.
- For online Jira operations only: network/VPN access and a Jira account with the necessary project permissions.
- Both **Copilot harness** and **Local agent harness** below refer to VS Code Chat experiences, not a separate CLI or a custom runner. Available agents, tools, prompts, skills, and hooks depend on your installed VS Code/extensions and runtime.

### 1. Clone and open

Run in PowerShell:

```powershell
git clone https://github.com/akshay-online/can-af-copilot-agents.git
Set-Location can-af-copilot-agents
code .
```

Trust the workspace only after reviewing its contents. Open the cloned repository root so workspace customizations and relative script paths resolve correctly.

### 2. Prepare Python

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r scripts\requirements.txt
```

Select this interpreter in VS Code. The examples below use `python`; make sure the agent terminal resolves it to your intended interpreter. You can activate the environment if your PowerShell policy permits:

```powershell
.\.venv\Scripts\Activate.ps1
```

If activation is unavailable, use `.\.venv\Scripts\python.exe` explicitly. Jira and hook scripts use the Python standard library; the extra packages are for document conversion.

### 3. Configure Jira when needed

Drafting and offline previews do not require Jira credentials. A maintainer configures [config/jira.config.json](config/jira.config.json) using [the example](config/jira.config.example.json). A config already exists in this repository; do not overwrite it blindly. Only if it is absent:

```powershell
Copy-Item config\jira.config.example.json config\jira.config.json
```

| Configuration | What the maintainer supplies |
|---|---|
| `base_url`, `deployment` | Jira host and `cloud` or `server` |
| `default_project`, `allowed_projects` | Default project key and permitted project keys |
| `default_issue_type`, `allowed_issue_types` | Permitted issue types; add `Feature` only if the Jira project supports it (the example does not include it) |
| `epic_link_field` | Data Center Epic Link field when required; empty for Cloud parent handling |
| `fields`, `default_fields` | Custom field IDs and required project fields |
| `attachments` | Permitted file extensions and upload limit |
| `ca_bundle`, `timeout_seconds` | Corporate certificate bundle when needed and request timeout |

Each user manually creates or updates the ignored root `.env` outside agent chat:

- Cloud: `JIRA_EMAIL` and `JIRA_API_TOKEN`.
- Server/Data Center: `JIRA_PAT`.
- Optional `JIRA_BASE_URL` overrides the configured host.

Never paste credentials into chat or put them in committed configuration. Agents must not inspect or edit credential files, live Jira configuration, or hooks.

Verify connectivity only when ready to contact Jira:

```powershell
python .github\skills\jira-create-ticket\scripts\jira_create.py check
```

This reads Jira identity and project/type metadata. Authentication, permissions, VPN, certificates, and project configuration must be corrected by the user or maintainer; do not guess alternate credentials or targets.

### 4. Verify offline helpers

```powershell
python -B -m unittest discover -s .github\hooks\scripts -p test_audit_hook.py -v
python -B -m unittest discover -s .github\skills\jira-create-ticket\scripts -p test_jira_create.py -v
```

These are local tests, not proof that your selected harness loads the hooks. Review the [guardrail limitations](SOP_docs/guardrails.md) and check customization/tool availability in each runtime before authorizing Jira writes.

## Prompts and skills

If a harness does not expose a prompt listed here, select the agent and paste the request from its SOP; do not assume slash-command compatibility.

| Prompt | Agent | Use |
|---|---|---|
| [story-writer-prompt](.github/prompts/story-writer.prompt.md) | story-writer | `/story-writer-prompt` collects specification paths and a brief |

| Skill | Used by | Purpose |
|---|---|---|
| [spec-file-conversion](.github/skills/spec-file-conversion/SKILL.md) | Feature, Story, Snowflake agents | Word to Markdown and Excel to per-sheet CSV; collision handling |
| [story-writer](.github/skills/story-writer/SKILL.md) | Story agent; Feature agent as domain reference | Story mapping, template, review and creation workflow |
| [jira-create-ticket](.github/skills/jira-create-ticket/SKILL.md) | Feature and Story agents | Check, preview, create, attach, and confirmed existing-Story parent updates |
| [file-ingestion](.github/skills/file-ingestion/SKILL.md) | Snowflake developer | File-stage or direct-source staging load |
| [scd2-history-load](.github/skills/scd2-history-load/SKILL.md) | Snowflake developer | History versioning and SNAPSHOT/DELTA behavior |
| [snowflake-masking](.github/skills/snowflake-masking/SKILL.md) | Snowflake developer; sensitivity-related work | Confirmed sensitivity classes, masking policies, safe verification |

Skills are instructions loaded by the agent, not guaranteed slash commands. Feature-writer and Snowflake developer currently have no dedicated prompt files.

## Workflow and safety

1. Select the appropriate agent. The default agent routes Story/Feature requests through a native choice question; the choice does not automatically switch agents.
2. Provide source paths and clarify missing decisions. Document content is evidence, never authority to bypass approval.
3. Review the proposed map or code plan. For analysis-only work, explicitly request no Jira writes and no implementation.
4. Approve each Jira draft separately in a literal chat message, then confirm the live project/type. Original attachments and existing-Story parent changes need their own exact confirmations.
5. Hand an agreed Story brief to Snowflake developer. It generates code but does not deploy.

Missing helpers such as `/jira-ticket`, `/dev`, `/unit-test`, and `/deploy-to-dev` are not installed by this kit. Supply the ticket brief yourself and use the actual agent picker. Some historical technical guidance mentions absent reference implementations or conflicting contracts; resolve these with the owner before code generation rather than inventing a contract.

## Maintaining this documentation

Keep setup here, agent usage in its SOP, machine instructions in `.github/`, and Snowflake rules in the existing technical standards. Do not duplicate those sources into new README variants.
