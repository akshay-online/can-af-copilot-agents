# Guardrail reference

## Scope and implementation

The [hook registration](../.github/hooks/copilot-audit.json) invokes the [policy engine](../.github/hooks/scripts/audit_hook.py) using the [policy](../.github/hooks/audit-policy.json). These are shared guardrails, not a separate agent. A maintainer owns policy changes; agents must not edit the hooks to unblock themselves.

| Event | Behavior |
|---|---|
| `userPromptSubmitted` | Records whether the latest literal user chat message contains an approval |
| `preToolUse` | Evaluates supported tool payloads and returns allow, ask, or deny |

## What is and is not stored

The hook does not persist prompts, tool arguments, tool results, or transcripts. It stores a per-session boolean approval flag under `logs/copilot-audit/.state/<session>.json`, an ignored working directory, and prunes state older than 48 hours. This is a statement about this repository's hook only, not the host application's telemetry or chat history.

## Checks and boundaries

| Area | Policy or workflow |
|---|---|
| Credentials | Blocks supported reads of `.env`/`connections.toml`, credential printing and environment dumps |
| Protected writes | Blocks supported changes to credentials, live Jira configuration, and hooks |
| Jira approval | JIRA-0 blocks marking a draft approved unless the latest literal chat prompt approved it |
| Jira creation | JIRA-1 checks approval, duplicate key, and explicit project/type arguments, then asks for tool confirmation |
| Jira client | Independently validates configured/live targets, draft lint, and duplicate creation |
| Existing Story parents | Requires exact confirmed keys; client validates Feature/Story types, project and parent conflicts; hook asks before update |
| Attachments | Agent must confirm exact issue key/files; client validates confirmation arguments, type/size, created status, and recorded uploads |
| Git/filesystem | Blocks configured force-push, no-verify, protected staging and broad recursive-delete patterns; asks for push |
| Snowflake | Blocks configured non-dev connection and destructive SQL command patterns; developer agent forbids all SQL execution |

Pattern checks apply to recognized tool names, arguments, and command forms. They are not a comprehensive sandbox or a guarantee against every possible operation.

## Harness verification and failure behavior

- Both SOP harness labels refer to VS Code Chat runtimes. Support for hook registration, tool names, payloads, and confirmation varies by installed host/version. Confirm hooks are actually loaded in each harness.
- Running tests verifies engine behavior against fixtures, not that VS Code invokes it for every tool.
- The engine is intentionally **fail-open** on internal exceptions and reports them on stderr. Policy load failures can yield an empty policy. Do not describe the hook as an absolute guarantee.
- The engine accepts Copilot camelCase and VS Code-style payloads. Hosted/cloud runtimes may reject `ask` rather than offer a confirmation; Jira creation/push may therefore be unavailable there.
- If required gates cannot be enforced or observed, stop the write workflow. Do not disable hooks, use raw Jira HTTP, change tools to evade a deny, or manually mark a draft approved.

## Offline verification

From the repository root:

```powershell
python -B -m unittest discover -s .github\hooks\scripts -p test_audit_hook.py -v
```

Tests cover supported approval/creation cases, protected paths, command rules, payload styles, failure behavior, and minimal state persistence. They do not contact Jira.

## Troubleshooting

| Symptom | Action |
|---|---|
| Approval not recognized | Send `approved` as a new literal chat message for the current draft; a form answer or typo does not satisfy the gate |
| Config or credentials inaccessible to agent | Expected; the user/maintainer configures them outside chat |
| Tool returns deny | Read the reason and resolve the prerequisite; never bypass it |
| Hooks not visible in selected runtime | Check host support and customization loading; do not infer availability from files alone |
| Hook exception or missing/bad policy | Report it to the maintainer; do not continue a sensitive write assuming protection |

See the [README](../README.md) and [Story SOP](story-writer.md) for the corresponding human workflow.
