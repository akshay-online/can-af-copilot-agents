# Copilot agent hooks: audit log and guardrails

Supported hook events from Copilot agents in this repo (story-writer, dev, review, deploy-to-dev …) are logged, and risky tool calls are blocked before they run. One hook file wires eleven events to one standard-library Python script. Coverage depends on which events and transcript fields the client supplies; unavailable output is recorded explicitly.

```
.github/hooks/
  copilot-audit.json        the 11 events → audit_hook.py <event>   (bash + PowerShell)
  audit-policy.json         what to log, redact, block and confirm  (tech lead edits this)
  scripts/audit_hook.py     logger + policy engine + session report + usage report
```

## What each hook does

| Event | Logged | Also |
|---|---|---|
| `sessionStart` | user (git email), host, repo, branch, commit, source (new/resume), initial prompt | Validates project state, runs retention cleanup, and requests a concise decision/evidence/output/verification summary through `additionalContext` |
| `userPromptSubmitted` | prompt (redacted), length, which agent it targets | Records whether the prompt is an explicit approval ("approved", "LGTM") for the story gate |
| `preToolUse` | full redacted arguments (including edits, questions and commands), file paths, **decision** (allow / ask / deny), rule id, reason | Enforces `audit-policy.json` (table below) |
| `postToolUse` | full redacted result, short excerpt, duration in ms | Includes user answers returned by question tools; detects `CREATED DATA-123` |
| `postToolUseFailure` | failed tool, arguments, error, duration when correlated | Failures also go to `errors/` |
| `agentStop` | stop reason, new visible transcript messages, final response when available, explicit capture status | Counts agent turns and updates the readable report. Never blocks |
| `subagentStart` | subagent name/id when supplied, parent id | Requests the same concise decision summary for the subagent |
| `subagentStop` | subagent name/id, parent, full response or visible transcript messages | Updates the report. Never blocks |
| `preCompact` | trigger and visible transcript messages before compaction | Preserves observed conversation evidence before the host compacts it |
| `errorOccurred` | error name, message, stack (redacted) | Goes to `errors/`; optional webhook alert |
| `sessionEnd` | end reason (complete / error / abort / timeout / user_exit), remaining visible transcript messages when available | Updates the session report; optional webhook |

## Where the logs go (git-ignored)

```
logs/copilot-audit/
  events/2026-11-04.jsonl        every event, one JSON line each
  errors/2026-11-04.jsonl        denials, tool failures, errors
  traces/2026-11-04_<id>.jsonl   chronological evidence for one session, including full redacted content
  sessions/2026-11-04_<id>.md    readable report per session: user, agents, duration,
                                 prompts, tools, decisions, visible messages, final output and capture gaps
```

Usage report across everyone's logs (or a collected folder):

```bash
python .github/hooks/scripts/audit_hook.py report --days 30
python .github/hooks/scripts/audit_hook.py report --agent story-writer
python .github/hooks/scripts/audit_hook.py report --user dev@company.com
```

Logs are written on each developer's machine (or in the cloud agent's runner). For a central view, have an approved collection job archive `logs/copilot-audit/` to access-controlled organizational storage. Cloud-runner files can be ephemeral: archive them before the job ends. The optional webhook sends only short alerts, not the complete audit trail.

Local files are not tamper-evident compliance records. Use an organization-approved immutable archive and access controls if management requires independently verifiable retention.

## Reconstructing how a result was reached

Open the session report or its matching `traces/` file. Records carry a session sequence, prompt index, turn index, agent/parent IDs when supplied, and tool-call IDs when supplied. Tool timing uses call IDs first, otherwise an argument fingerprint with FIFO matching for identical calls. The trail preserves:

1. The submitted prompt and initial request.
2. Tool inputs, questions and returned answers, file edits, reported results and failures.
3. Policy decisions and their rule/reason. An `ask` is a request for confirmation, not evidence that the user granted it.
4. Visible assistant explanations and decision summaries found in the transcript or supplied explicitly by a hook payload.
5. Final response text supplied by the host; otherwise the latest visible assistant message in a completely consumed transcript, labelled with that provenance. On an interrupted turn, that message is not proof of successful completion.

**Reasoning limit:** hooks cannot provide hidden internal chain-of-thought. They request concise, user-visible decision summaries explaining conclusions, evidence, assumptions and validation instead. Summaries are agent explanations, not independently verified facts. The request is advisory; the agent might not produce a summary. Hooks never fabricate one or block completion to obtain it.

Transcript capture reads only the path supplied by the host (or the primary path previously supplied in that session). It supports newline-delimited JSON with `assistant.message`/`user.message` and `data.content`, or `role`/`content` and nested `message` text blocks. Only visible text is extracted; system, private reasoning and thinking blocks are excluded. Other formats are not automatically decoded. Incremental cursors avoid re-copying old messages and reset on detected file replacement, truncation or changed prefix.

Each stop records `transcript_capture` (`complete`, `partial`, `unavailable`, `disabled`, or `error`). `complete` means the current byte range was consumed, not that the host exposed every interaction. Malformed-record counts and missing final responses are explicit. A byte budget or unfinished JSONL line produces `partial`; the remaining bytes can be retried on a later stop/end event. Increase the budget if a single record exceeds it. Abrupt termination before a hook fires cannot be recovered by hooks alone. Reports are checkpointed at agent/subagent stops so a missing session-end event does not remove earlier evidence.

## What `preToolUse` blocks

| Rule | Blocks |
|---|---|
| READ-1, SEC-1 | Reading `.env` or `connections.toml` (view tool or `cat`/`type`/`Get-Content`) |
| SEC-2, SEC-3 | Dumping environment variables or echoing `$JIRA_API_TOKEN` and similar |
| SEC-4 | Raw `curl`/`Invoke-RestMethod` to Jira (use the kit scripts) |
| WRITE-1, SEC-5 | Changing `.env`, `config/jira.config.json`, or `.github/hooks/` (agents can't switch off their own audit) |
| **JIRA-0** | Writing `status: approved` into a story draft unless the user's **latest chat prompt** was an approval |
| **JIRA-1** | `jira_create.py create` when the draft isn't approved, was already created, or lacks `--confirm-project` / `--confirm-type`. When everything is in order it returns **ask**, so VS Code shows its own confirmation |
| GIT-1/2/3 | Force push, `--no-verify`, `git add` of `.env`, `.jira/` or audit logs |
| FS-1 | `rm -rf` on `/`, `~`, `.` |
| SF-1, SF-2 | Snowflake CLI on any connection other than `dev`; `DROP`, `TRUNCATE`, `CREATE OR REPLACE TABLE`, `DELETE FROM HIST.` from the terminal |
| ASK-1/2 | Confirmation before `deploy_dev.sh --execute` and `git push` |

JIRA-0 and JIRA-1 turn the story-writer's two human gates into enforced checks, not just instructions to the model.

## Redaction

Full evidence is redacted before persistence. Structured credential fields (such as password, token and authorization) are masked recursively; known private reasoning fields/blocks are excluded. Redaction is pattern-based, not a guarantee of anonymization: full tool results and prompts can contain confidential business data. Restrict access to all audit directories and apply your organization's retention policy; do not commit them.

Full evidence uses `max_content_chars: 0` (no truncation); a positive value truncates strings with an explicit omitted-character marker. Set `log_prompts: false` to suppress prompt fields and transcript user messages. Set `log_tool_arguments`, `log_tool_results`, or `log_assistant_messages` to `false` to disable those full-content fields. Legacy command/path/argument/result excerpts remain logged, so these switches are not a global sensitive-data opt-out. Visible assistant text can also quote user content.

### Legacy summary fields and pattern masking

`max_field_chars` and `result_excerpt_chars` limit legacy summary fields only, not the new full-evidence fields. The original summary/masking behavior is:

Before anything is written: bearer/basic auth headers, Atlassian, GitHub and AWS tokens, `token=` / `password=` style values, private keys, SSN/TIN-shaped numbers and card-like numbers are masked. Email addresses inside prompts and results are partly masked (`j***@aflac.com`); the user's own git email is kept as the audit identity. Long fields are cut at `max_field_chars`. Set `log_prompts: false` to log only prompt length.

## Install

1. Copy `.github/hooks/` into the repo and commit it.
2. Add to `.gitignore`:
   ```
   logs/copilot-audit/
   ```
3. Python 3.8+ on each developer's PATH (`python3`, `python` or `py`).
4. **Copilot CLI and the cloud agent** load `.github/hooks/*.json` automatically. **VS Code** agent hooks are in preview: turn them on in settings if your version requires it; VS Code reads the same file and sends its own payload format, which the script handles.
5. Optional alerts: set `COPILOT_AUDIT_WEBHOOK` (an `https://` Teams or Slack incoming webhook) in the environment. It fires on `deny`, `errorOccurred` and `sessionEnd` (change in `notify.on`).

## Tuning the policy

Edit `audit-policy.json`: add command rules, protected paths, agent markers, or change `retention_days`. Retention covers events, errors, traces and reports; orphaned state is removed after two days as before. Set `request_decision_summary: false` to stop injecting summary guidance. `max_transcript_bytes_per_event` defaults to 16 MiB per stop/compaction/end event. Stop/end hooks have a 30-second timeout for transcript capture and report generation. Rule patterns are checked against the command in lower case.

## Behaviour on failure

- If logging fails (disk, permissions), the hook writes a note to stderr and lets the agent continue.
- A policy **deny** is always returned. If the policy engine itself crashes, the tool call is allowed and the crash is reported on stderr, so a hook bug can't freeze the team's agents. Change `main()` to emit `deny` instead if you prefer fail-closed.
- The cloud agent treats **ask** as **deny**, so `jira_create.py create` and `git push` are blocked there by design.

## Tested

Run the current isolated, standard-library regression suite:

```powershell
python -B -m unittest discover -s .github\hooks\scripts -p test_audit_hook.py -v
```

Tests use temporary directories and do not call Jira or send webhooks. They cover long-content preservation, both payload styles, failed-tool timing, direct subagent responses, visible transcript extraction, exclusion of private reasoning, redaction, logging switches, incremental reads, malformed and missing transcripts, compaction, report persistence and hook registration. The existing permission engine and Jira gates are unchanged; approval-state fixtures were not added because the live approval guard rejected those test patches.

Host integration is not certified by these simulated payload tests. Start a new session in each supported client and confirm that prompts, tool events, stop responses/transcripts and the final report reach your approved archive.

### Historical validation notes (original implementation)

A simulated story-writer session in both payload formats (Copilot camelCase and VS Code): all 8 events logged; 20 risky calls denied with the right rule; the approval gate denies before the user says "approved" and allows after; `jira_create.py create` returns *ask* only for an approved, not-yet-created draft with confirm flags; tokens, SSNs and emails absent from every log; session report and usage report correct.
