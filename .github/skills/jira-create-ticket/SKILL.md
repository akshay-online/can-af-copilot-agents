---
name: jira-create-ticket
description: Create a Jira issue through the Jira REST API (no MCP) from an approved Markdown draft, with host, project and issue types taken from config and credentials from .env. Use to check the Jira connection, preview the target project and issue type, or create a story after a human has approved it and confirmed the target.
---

# Jira: create a ticket (REST API, no MCP)

`scripts/jira_create.py` is standard-library Python. It reads:

| From | What |
|---|---|
| `config/jira.config.json` (committed) | `base_url`, `deployment` (cloud / server), `default_project`, `allowed_projects`, `default_issue_type`, `allowed_issue_types`, labels, components, parent / epic link field, custom field ids, required sections, attachment rules |
| `.env` (git-ignored) | Cloud: `JIRA_EMAIL` + `JIRA_API_TOKEN`. Server/DC: `JIRA_PAT`. Optional `JIRA_BASE_URL` overrides the config |

Never ask the user for any of these in chat, never print them, never edit them. If one is missing the script says which file to fill; tell the user that and stop.

## Commands

```bash
S=.github/skills/jira-create-ticket/scripts/jira_create.py

python $S check
#   who am I, each allowed project, its issue types

python $S preview <draft.md> [--project KEY] [--type "Story"] [--offline]
#   lint + render, no write to Jira. Prints TARGET / CONTENT / LINT / STATUS.
#   Writes preview.jira.txt (rendered description) and payload.json next to the draft.
#   Exit 3 if any FAIL.

python $S create <draft.md> --confirm-project KEY --confirm-type "Story"
#   POST /rest/api/2/issue; the story-writer flow selects attachments afterward.
#   Refuses unless: status: approved, no FAIL, project and type allowed by config and by Jira,
#   and jira_key is empty (no duplicates). On success writes status: created, jira_key, jira_url.

python $S attach <draft.md> --confirm-issue KEY --confirm-files "file one.pdf" "file two.xlsx"
#   uploads the exact confirmed files in the draft's attachments list to an existing issue.
#   Requires status: created, a matching jira_key, and an exact match between confirmed filenames
#   and validated attachment filenames. Successful paths are recorded in uploaded_attachments.
```

## Rules for the agent

1. **Two human gates, in this order.** (a) The user approves the draft content in chat → set `status: approved`. (b) The user confirms the exact project and issue type shown by `preview` → pass the same values to `--confirm-project` / `--confirm-type`. One "yes" never covers both.
2. The values passed to `--confirm-*` must be the ones the user just confirmed, not defaults filled in silently.
3. If `create` fails with exit 1, show the error line; don't retry with different fields or another project without asking. If it fails after `CREATED`, the issue exists: report the key and never run `create` again for that draft.
4. Exit 3 means the draft is not ready; fix the draft (or get approval) and preview again.
5. **Attachment gate.** After issue creation, ask which folder to use (offer the shared-folder path and selected `docs/<folder>`; accept a local folder/file path). List the files and ask the user to confirm the issue key and exact filenames before adding their paths to `attachments` and running `attach`. The command's `--confirm-issue` and `--confirm-files` must match that confirmation. Never attach to a different issue or upload an unconfirmed file.

## What the script does with the draft

- Front matter: `summary`, `project`, `issue_type`, `parent`, `labels`, `components`, `priority`, `story_points`, `attachments`, and script-managed `uploaded_attachments`.
- Body: HTML comments and the H1 title are removed; Markdown is converted to Jira wiki markup (headings, tables, lists, task boxes as ☐/☑, code blocks, bold, links). The v2 API accepts wiki markup on both Jira Cloud and Data Center.
- If `fields.acceptance_criteria` is set in config, the *Acceptance criteria* section goes to that custom field instead of the description.
- `parent`: sent as `parent` (Cloud, and DC sub-tasks) or into `epic_link_field` when that is set (DC Epic Link).
- `default_fields` in config are added to every issue (for example a team field).

## Troubleshooting

| Message | Meaning |
|---|---|
| `HTTP 401` | Credentials in `.env` are wrong or expired |
| `HTTP 403` | No *Create issues* permission in that project |
| `HTTP 400 … customfield_…` | A required field in that project is not set: add it to `default_fields` in config |
| `HTTP 400 … parent` | The parent key does not exist or is not an epic in that project |
| `Cannot reach …` | VPN / proxy / corporate certificate: set `ca_bundle` in config |
| `description is N chars` | Over Jira's 32,767 limit: shorten the column spec and attach the workbook |
