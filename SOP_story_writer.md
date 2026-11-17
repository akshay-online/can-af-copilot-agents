# SOP: Story Writer Copilot Agent

Standard Operating Procedure for setting up and using the `/story-writer` agent to turn
requirement documents (Word, Excel, CSV) into Jira stories, with a human approval gate before
anything is created in Jira.

Audience: this SOP has two parts — **Setup** (one-time, done by a tech lead) and **Usage**
(every time, done by anyone drafting stories).

---

## 1. What this kit does

```
/story-writer-prompt <spec files or folder> narrate the context what the stories should cover and how they should be structured.
   │
  1. Reads your specs (Word/Excel/CSV), converts them to plain text/CSV
  2. Asks how many stories you need and what each should cover
  3. Drafts each story (Description, Acceptance criteria, Dependencies)
  4. GATE 1 — you review in chat and reply "approved"
  5. Confirms the Jira project and issue type with you
  6. GATE 2 — you confirm "yes"
  7. Creates the issue in Jira and writes the key back into the draft
  8. GATE 3 — you confirm which original files to attach
```

No Jira MCP server is required — it talks to Jira directly over its REST API using a script in
this repo. A guard hook (`.github/hooks/`) enforces Gates 1 and 2 at the tool level, so the
agent physically cannot create an issue without your explicit approval, even if it misreads its
own instructions. **The guard hook does not log your prompts, chat content, or tool results
anywhere** — see [HOOKS-README.md](HOOKS-README.md).

---

## 2. Setup (one-time, tech lead)

### 2.1 Prerequisites

- Python 3.8+ available on PATH as `python3`, `python`, or `py`.
- A Jira account (Cloud or Server/Data Center) with permission to create issues in the target
  project(s).
- VS Code with GitHub Copilot Chat (Agent mode), or Copilot CLI / the cloud coding agent.

### 2.2 Configure the Jira connection

1. Copy the example config and edit it:
   ```powershell
   Copy-Item config\jira.config.example.json config\jira.config.json
   ```
2. Open `config/jira.config.json` and set:

   | Field | What to put |
   |---|---|
   | `base_url` | Your Jira URL, e.g. `https://your-company.atlassian.net` |
   | `deployment` | `"cloud"` or `"server"` (Data Center) |
   | `default_project` / `allowed_projects` | The Jira project **key** (not the display name), e.g. `"DATA"`. The agent can only create issues in projects listed here. |
   | `default_issue_type` / `allowed_issue_types` | e.g. `"Story"`, and the full allow-list `["Story", "Task", "Bug"]` |
   | `epic_link_field` | Leave empty on Jira **Cloud** (the parent is sent as `parent`). On Data Center, set it to your Epic Link custom field id, e.g. `"customfield_10014"`. |
   | `fields.acceptance_criteria` | The custom field id if your project has a dedicated *Acceptance Criteria* field (e.g. `"customfield_10071"`); leave empty to keep AC in the description. |
   | `default_fields` | Any field your project requires on create, e.g. `{"customfield_10300": {"value": "Data"}}` |

   **This file is safe to commit** — the script refuses to run if it finds a token or password
   in it. Never put credentials here.

### 2.3 Configure credentials (each developer, not committed)

1. Copy `.env.example` to `.env` in the repo root.
2. Fill in the lines that match your Jira deployment:

   | Deployment | Variables |
   |---|---|
   | Jira **Cloud** | `JIRA_EMAIL` (your Atlassian account email) and `JIRA_API_TOKEN` (create one at `id.atlassian.com` → Security → API tokens) |
   | Jira **Server / Data Center** | `JIRA_PAT` (a Personal Access Token from your Jira profile) |

3. `.env` is already in `.gitignore` — it must never be committed or pasted into chat.

### 2.4 Verify the connection

```powershell
python .github/skills/jira-create-ticket/scripts/jira_create.py check
```

This prints your Jira user, each allowed project, and its available issue types. Fix any error
here before using the agent (common causes: wrong `base_url`, expired token, or a project key
that doesn't exist).

### 2.5 Confirm the guard hook is active

The kit ships `.github/hooks/` with the policy already configured — no setup needed beyond
Python being on PATH. To confirm it works:

```powershell
python -B -m unittest discover -s .github\hooks\scripts -p test_audit_hook.py -v
```

All tests should pass. In VS Code, agent hooks may be a preview feature — enable it in settings
if prompted. Copilot CLI and the cloud agent load `.github/hooks/*.json` automatically.

See [HOOKS-README.md](HOOKS-README.md) for exactly what the hook blocks and why.

---

## 3. Usage (every time)

### 3.1 Start the agent

In Copilot Chat, switch to **Agent mode** in **Local** harness and run:

```
/story-writer-prompt specs/producer_contract/ <context about the stories>
```

(or attach the files, or just describe/name them in chat). If you don't name anything, the
agent scans the `docs/` folder.

### 3.2 Answer its questions

The agent will ask:
- How many stories you want, and what each should cover (its proposed split is a
  **story map** you must confirm before drafting starts).
- Clarifying questions as it reads the specs — answer these in chat; the agent will not guess.

### 3.3 Review and approve each draft (Gate 1)

For each story, the agent writes `.jira/drafts/<story-slug>/story.md` with **Description**,
**Acceptance criteria**, and **Dependencies / links** only (no raw data, no column dumps).

- Read it. Ask for changes in chat as many times as needed.
- When it's right, reply with the literal word **"approved"** (or "LGTM", "looks good", "ship
  it") as your next chat message. This exact phrase is what unlocks the story — the agent
  cannot mark it approved on your behalf, and a typo like "aprroved" will not work.

### 3.4 Confirm the Jira target (Gate 2)

The agent shows the target project and issue type (validated live against Jira) and asks you to
confirm, e.g. *"Create Jira Story in project DATA from this draft?"*. Reply **yes** to proceed.

### 3.5 Issue created

The agent creates the issue via the REST API, prints the new key (e.g. `DATA-301`), and writes
it back into the draft so the same draft can never be created twice.

### 3.6 Attach originals (Gate 3)

The agent proposes the relevant original documents (Word/Excel, not the converted working
files) as attachments and asks you to confirm the exact filenames before uploading.

Steps 3.3–3.6 repeat for every story in the set.

---

## 4. What's enforced vs. what's instructed

| | Mechanism |
|---|---|
| Story can't be created without your "approved" | Enforced by the guard hook (`JIRA-0` rule) — not just the agent's instructions |
| Wrong/unlisted Jira project or issue type | Enforced by `jira_create.py` against `allowed_projects`/`allowed_issue_types` in the config |
| Duplicate creation | Enforced by `jira_create.py` — refuses if the draft already has a `jira_key` |
| `.env` / credentials never read or edited by the agent | Enforced by the guard hook (`READ-1`, `WRITE-1`) |
| Raw CSV data reaching the agent/chat | Enforced by `read_inputs.py`, which only exposes headers + row counts |
| Final `jira_create.py create` confirmation | Enforced by the guard hook (`JIRA-1`) — returns **ask**, so VS Code shows its own confirmation prompt |

---

## 5. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `jira_create.py check` fails with 401/403 | Wrong `JIRA_API_TOKEN`/`JIRA_PAT`, or token expired |
| `check` fails with 404 on a project | Project key in `allowed_projects` doesn't exist, or you used the display name instead of the key |
| Agent says a draft can't be approved | You didn't reply with the literal word "approved" as your very next message |
| `create` is denied even after approving | The draft already has a `jira_key` set (already created), or `--confirm-project`/`--confirm-type` weren't both supplied |
| Agent can't edit `.github/hooks/` or read `.env` | Expected — these are protected by design, even for the agent itself |

For the full list of what the guard hook blocks and why, see
[HOOKS-README.md](HOOKS-README.md). For the agent's full workflow and file layout, see
[STORY-WRITER-README.md](STORY-WRITER-README.md).
