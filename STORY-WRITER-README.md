# Story writer: Copilot agent that drafts Jira stories from specs

Add-on for the Snowflake Copilot kit. It reads the business inputs (Word requirements, Excel column spec, sample CSVs), drafts a Jira story in the team template, waits for a human to approve it, confirms the target project and issue type, and creates the story through the Jira REST API. No Jira MCP needed.

```
/story-writer <spec files or folder> — then describe what you want in the brief field (or in chat)
   │
  ├─ user brief            what to write + extra details, saved to inputs/user-brief.md (asked if missing)
  ├─ spec-file-conversion  docx → Markdown; xlsx/xlsm → one CSV per sheet
  ├─ read_inputs.py        sample CSV → Markdown metadata (headers + row count only)
   ├─ draft story.md        team template, sources cited, unknowns = ⚠ TBC + Open questions
   ├─ preview --offline     lint: required sections, Given/When/Then, no TODOs, size
   │
   ├─ GATE 1  human reviews the draft in chat → "approved"  → status: approved
  ├─ preview               reads Jira: project name, valid issue types and parent
  ├─ GATE 2  human confirms "project DATA as Story?" → yes
  ├─ create                POST /rest/api/2/issue → DATA-301, link written back to the draft
  └─ GATE 3  human selects folder and confirms filenames → attach to DATA-301
```

## What's in it

```
.github/
  agents/story-writer.agent.md            the agent (workflow, two gates, hard rules, handoff to dev)
  prompts/story-writer.prompt.md          /story-writer slash command
  skills/story-writer/
    SKILL.md                              how to read inputs, write the story, review, create
    templates/story-template.md           what every story must contain
    examples/producer-contract-story.md   a complete, Ready story (quality bar)
    scripts/read_inputs.py                sample CSV → Markdown metadata (headers + row count)
  skills/spec-file-conversion/
    SKILL.md                              converts Word and Excel specs into the draft inputs directory
  skills/jira-create-ticket/
    SKILL.md                              how to check, preview, create and attach in Jira
    scripts/jira_create.py                Jira REST API v2, standard-library Python
config/jira.config.example.json           host, projects, issue types, field mapping (no secrets)
.env.example                              JIRA_EMAIL + JIRA_API_TOKEN (Cloud) or JIRA_PAT (Server/DC)
```

## Install (once)

1. Copy these files into the kit repo root. `.jira/` and `.env` are already git-ignored in the kit; drafts live in `.jira/drafts/`, so they are never committed.
2. **Tech lead:** copy `config/jira.config.example.json` to `config/jira.config.json` and set:
   - `base_url`, `deployment` (`cloud` or `server`)
   - `default_project` and `allowed_projects` (the agent can only create in these)
   - `default_issue_type` and `allowed_issue_types`
   - `epic_link_field`: leave empty on Jira Cloud (the parent is sent as `parent`); on Data Center set it to the Epic Link field id (for example `customfield_10014`)
   - `fields.acceptance_criteria`: the custom field id if your project has an *Acceptance Criteria* field, otherwise empty (AC stay in the description)
   - `default_fields`: any field your project makes mandatory, for example `{"customfield_10300": {"value": "Data"}}`

   Commit this file. The script refuses to run if it finds a token or password in it.
3. **Each developer:** add the Jira lines from `.env.example` to `.env` (Cloud: `JIRA_EMAIL` + `JIRA_API_TOKEN`; Server/DC: `JIRA_PAT`). The same `.env` already serves `/jira-ticket`.
4. Test: `python .github/skills/jira-create-ticket/scripts/jira_create.py check`. It prints your Jira user, each allowed project and its issue types.

## Use

In Copilot Chat (Agent mode):

```
/story-writer specs/producer_contract/        (or attach the files, or name them)
```

1. Describe what you want the story to cover in the **brief** field of the prompt, or type it in chat. Add any details the documents do not give (context, assumptions, decisions already made). If you leave it out, the agent asks for it. The brief is saved to `.jira/drafts/<slug>/inputs/user-brief.md`.
2. The agent uses supplied files, or scans `docs/` when none are named; it asks which folder if `docs/` has multiple folders, and asks about missing/new specs if it is empty. It asks for a shared-folder path to reference in the story, or `none`.
3. It writes converted Word Markdown and per-sheet Excel CSVs to `.jira/drafts/<slug>/inputs/`, then drafts `.jira/drafts/<slug>/story.md` following your brief, and shows the Definition of Ready (✔/✘), open questions and lint warnings. Conflicts between your brief and the documents are listed as open questions.
4. Read the draft, ask for changes in chat, repeat. Reply **approved** when it's right.
5. It shows the target and asks you to confirm the project and issue type. Attachments are selected after creation.
6. After creation, choose the shared folder, selected `docs/<folder>`, or another local path. Confirm the exact filenames before they are uploaded to the new issue.


The agent never asks for the Jira URL, email or token.

## Guardrails

| Risk | How it's handled |
|---|---|
| Story created without review | `create` refuses unless the draft says `status: approved`, which the agent sets only after an explicit chat approval |
| Wrong project or issue type | Both must be in the config allow-lists, exist in Jira, and be passed explicitly as `--confirm-project` / `--confirm-type` after the user confirms them |
| Duplicates | After creation the key is written into the draft; a second `create` is refused |
| Secrets leaking | Credentials only in `.env`; script never prints them; config with a token is rejected |
| Data values reaching Copilot | CSVs are reduced to headers and row counts; large Excel data sheets are truncated with a warning |
| Invented requirements | Template and skill require a source citation per fact and `⚠ TBC` + Open question for anything missing |
| Prompt injection from documents | Agent treats document text as data; approval only counts from the user's chat messages |

## Audit and enforced gates

`.github/hooks/` logs every agent interaction (session start/end, prompts, every tool call and its result, stops, subagents, errors) and enforces the two gates at tool level: an agent cannot write `status: approved` unless the user's last message approved the draft, and `jira_create.py create` is denied for unapproved or already-created drafts and needs a final confirmation otherwise. See `HOOKS-README.md`.

## Notes

- The script uses REST API **v2** with Jira wiki markup, which works on both Jira Cloud and Data Center. Tables, lists, task boxes, code blocks and links are converted from Markdown.
- `tools` in the agent file lists both current and older VS Code tool names; unknown names are ignored. If the agent can't run terminal commands, check the tool picker in Copilot Chat.
- Tested against a mock Jira: Cloud basic auth, Data Center PAT, parent and Epic Link, AC custom field, attachments, bad token (401), unknown project (404), bad parent (400), approval gate, duplicate guard.
