# Copilot agent hooks: guardrails (no logging)

A lightweight guard for Copilot agents in this repo (story-writer and friends): it blocks or asks
for confirmation on risky tool calls **before they run**. It does not log prompts, tool
arguments, tool results, or transcripts anywhere - nothing about your conversation is written to
disk.

```
.github/hooks/
  copilot-audit.json        2 events → audit_hook.py <event>   (bash + PowerShell)
  audit-policy.json         what to block and confirm           (tech lead edits this)
  scripts/audit_hook.py     the policy engine
```

## What each hook does

| Event | Purpose |
|---|---|
| `userPromptSubmitted` | Checks whether the user's latest chat message is an explicit approval ("approved", "LGTM", ...). Keeps a single boolean per session in memory - no prompt text is stored. |
| `preToolUse` | Applies `audit-policy.json` and returns **allow / ask / deny** before the tool runs (table below) |

Nothing else runs: no session start/end hooks, no post-tool-use logging, no transcripts, no
session reports, no usage reports, no webhook notifications.

## Where state is kept

One tiny file per active session, holding only a single `true`/`false` flag (was the last
message an approval?):

```
logs/copilot-audit/.state/<session>.json
```

This folder is git-ignored (`/logs`), self-prunes files older than 48 hours, and contains no
prompts, no tool arguments, no tool results and no conversation content.

## What `preToolUse` blocks

| Rule | Blocks |
|---|---|
| READ-1, SEC-1 | Reading `.env` or `connections.toml` (view tool or `cat`/`type`/`Get-Content`) |
| SEC-2, SEC-3 | Dumping environment variables or echoing `$JIRA_API_TOKEN` and similar |
| SEC-4 | Raw `curl`/`Invoke-RestMethod` to Jira (use the kit scripts) |
| WRITE-1, SEC-5 | Changing `.env`, `config/jira.config.json`, or `.github/hooks/` (agents can't switch off their own guard) |
| **JIRA-0** | Writing `status: approved` into a story draft unless the user's **latest chat prompt** was an approval |
| **JIRA-1** | `jira_create.py create` when the draft isn't approved, was already created, or lacks `--confirm-project` / `--confirm-type`. When everything is in order it returns **ask**, so VS Code shows its own confirmation |
| GIT-1/2/3 | Force push, `--no-verify`, `git add` of `.env`, `.jira/` or the hook's state folder |
| FS-1 | `rm -rf` on `/`, `~`, `.` |
| SF-1, SF-2 | Snowflake CLI on any connection other than `dev`; `DROP`, `TRUNCATE`, `CREATE OR REPLACE TABLE`, `DELETE FROM HIST.` from the terminal |
| ASK-1/2 | Confirmation before `deploy_dev.sh --execute` and `git push` |

JIRA-0 and JIRA-1 turn the story-writer's two human gates into enforced checks, not just
instructions to the model.

## Install

1. Copy `.github/hooks/` into the repo and commit it.
2. Python 3.8+ on each developer's PATH (`python3`, `python` or `py`).
3. **Copilot CLI and the cloud agent** load `.github/hooks/*.json` automatically. **VS Code**
   agent hooks are in preview: turn them on in settings if your version requires it; VS Code
   reads the same file and sends its own payload format, which the script handles.

## Tuning the policy

Edit `audit-policy.json`: add/remove command rules (`deny_commands`, `ask_commands`), protected
paths (`protected_read`/`protected_write` and their `_exceptions`), or change the Jira approval
gate (`jira_create_gate`). Rule patterns are checked against the command in lower case.

## Behaviour on failure

- A policy **deny** is always returned. If the policy engine itself crashes, the tool call is
  **allowed** and the crash is reported on stderr, so a hook bug can't freeze the team's agents.
- The cloud agent treats **ask** as **deny**, so `jira_create.py create` and `git push` are
  blocked there by design.

## Tested

```powershell
python -B -m unittest discover -s .github\hooks\scripts -p test_audit_hook.py -v
```

Tests use temporary directories and don't touch Jira. They cover the approval gate (JIRA-0),
the Jira create gate (JIRA-1), protected read/write paths, deny/ask commands, both payload
styles (Copilot and VS Code), fail-open behavior on a broken policy, that no files are written
to disk beyond the one approval-state flag, and that `copilot-audit.json` only registers the two
events this hook needs.

