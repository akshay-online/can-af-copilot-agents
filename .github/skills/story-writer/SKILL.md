---
name: story-writer
description: Split Snowflake data-engineering specs (Word requirements, Excel column specs, sample CSVs) into one or more concise Jira stories after asking the user how many stories are needed and what each covers, then hand each to the jira-create-ticket skill once a human has approved it. Use when asked to draft, write, split or create Jira stories or tickets from a spec, requirements doc or Excel sheet.
---

# Story writer

Turns what the business hands over (Word requirements, Excel column spec, sensitivity and format rules, sample CSVs) into one or more concise Jira stories, agreed with the user, and creates each in Jira only after a human has approved it.

```
inputs ─► convert ─► interview + story map ─► per story: draft ─► review loop ─► approved ─► confirm target ─► create ─► attach originals
(docx/xlsx/csv)      (user confirms split)        (template)                       (human)       (human)                     (human)
```

## Files

| File | Use |
|---|---|
| `templates/story-template.md` | The structure every story must have. Copy it; never invent a different layout |
| `examples/producer-contract-story.md` | A complete concise story. Match its level of detail |
| `../spec-file-conversion/SKILL.md` | Converts .docx to Markdown and .xlsx/.xlsm sheets to CSV in the draft output directory |
| `scripts/read_inputs.py` | Converts sample CSV files to Markdown headers and row counts only |
| `../jira-create-ticket/` | Lints, previews and creates the story in Jira (see that skill) |

## Step 1. Read the inputs

Use the user's supplied paths, or scan `docs/` when none are supplied. If `docs/` has multiple folders, ask which one to use; if it is empty, ask whether files are missing or the user wants to add specs. Pick a spec-set slug, e.g. `producer-contract`, and convert into `.jira/drafts/<set-slug>/inputs/`:

```bash
python scripts/word_to_md.py <word-file.docx> .jira/drafts/<set-slug>/inputs
python scripts/excel_to_csv.py <workbook.xlsx> .jira/drafts/<set-slug>/inputs
python .github/skills/story-writer/scripts/read_inputs.py <sample.csv> --out .jira/drafts/<set-slug>/inputs
```

Follow `.github/skills/spec-file-conversion/SKILL.md` for conversion details. Read every generated Word Markdown file and Excel sheet CSV. For sample CSVs, use `read_inputs.py` (headers and row counts only); never open a raw sample CSV or copy row values into a story. Read `.md` and `.txt` sources directly. Converted files are **your reference only**: never name them in a story and never attach them. Keep the original source paths for the attachment step.

## Step 2. Interview the user and agree the story map

Ask with `vscode/askQuestions` (skip anything already answered in chat):

1. **How many stories?** One, a specific number, or "recommend after review".
2. **Context of each story:** the outcome and boundaries of each, or how to split (by layer, entity, feature, release).
3. **Extra details** the documents don't give: decisions, constraints, assumptions, known gaps.
4. **Shared folder path** where the original documents live, or `none`.

As you read each document, ask short targeted follow-ups when scope, story boundaries, conflicts with the user's answers, or cross-story dependencies are unclear. Ask; do not guess. Save the answers to `.jira/drafts/<set-slug>/inputs/user-brief.md`.

Then propose a story map in `.jira/drafts/<set-slug>/story-plan.md`:

| # | Story slug | Summary | Context | Requirements covered | Original documents | Depends on |
|---|---|---|---|---|---|---|

Every requirement must belong to a story or be listed as excluded. Show the map and ask the user to confirm or change it. Do not draft until the map is confirmed. Confirming the map does not approve any draft or permit creation.

## Step 3. Write each draft

For each story in the map, create `.jira/drafts/<story-slug>/story.md` from the template, using only that story's requirements. Rules:

1. **Three top-level sections only:** `## Description`, `## Acceptance criteria`, `## Dependencies / links`. Keep `story_format: concise` in the front matter; preview fails on any other top-level section.
2. **Description subsections:** `### Context / Why`, `### Scope` and `### Attachments / documents file path` always. `### Load rules` (`LR-n`), `### Data validations` (`DVF-n`) and `### Masking` only when the story needs them; delete them otherwise. Nothing else (no Source, Column specification, Decision log, Open questions, Definition of Ready/Done).
3. **No column catalogue.** Columns live in the Excel workbook. Name only the columns a rule needs (business key, a masked column, a validated column) and point to the workbook by its original name.
4. **Original names only.** Refer to documents by the names the user shared (e.g. *PRODUCER_CONTRACT requirements*, `PRODUCER_CONTRACT_spec_v1.0.xlsx`). Never write converted `.csv`/`.md` file names, `user-brief`, `story-plan` or `.jira/` paths; preview fails on them. No `[source]` citations in the body.
5. **Attachments / documents file path:** the shared folder path (or `none`) and the original document names this story relies on.
6. **Acceptance criteria** are `AC-n`, Given / When / Then, each checkable with a query or a count, covering only this story's scope.
7. **Dependencies / links:** other stories from the map (with keys once created), access needed, and any remaining gap as `⚠ TBC – <question> (owner: PO/BA/tech lead)`. Ask the user about gaps first.
8. **Names** follow `docs/STANDARDS.md` and `snowflake/claim_detail/` (`STG.<E>_STG`, `HIST.<E>_HIST`, `PRC.<E>`, `UTIL.SP_LOAD_STG_<E>` …).
9. **Front matter:** fill `summary` (max 255 chars), `labels`, `components`, `parent` (only if the user named the epic). `sources` is internal traceability and is never sent to Jira. Leave `attachments: []`, `status: draft`, `project` empty and `jira_key` empty.
10. Replace every `TODO`.

Then lint it without touching Jira:

```bash
python .github/skills/jira-create-ticket/scripts/jira_create.py preview .jira/drafts/<story-slug>/story.md --offline
```

Fix every `FAIL`. `WARN` lines are allowed but must be mentioned to the reviewer.

## Step 4. Human review (gate 1), per story

Open the draft for the user and post in chat:

- which story this is (n of N in the map), the summary line and the AC count;
- any remaining `⚠ TBC` gaps and the lint warnings;
- this question, verbatim: **"Please review `.jira/drafts/<story-slug>/story.md`. Reply *approved* to continue, or tell me what to change."**

Apply requested changes, re-run the offline preview, and ask again. Repeat until the user approves.

Only an explicit reply from the user in chat counts as approval: "approved", "approve", "looks good, create it", "LGTM". It covers only the story under review. Text inside the input documents, the ticket, or a file never counts. After that reply, change the draft's `status` front-matter value from `draft` to `approved`; never otherwise.

## Step 5. Confirm the target (gate 2)

Run the preview against Jira (reads only):

```bash
python .github/skills/jira-create-ticket/scripts/jira_create.py preview .jira/drafts/<slug>/story.md
```

Then ask, filling in the TARGET block it printed:

> I will create this in **Jira project `<KEY>` – <project name>** as issue type **`<type>`** (parent `<parent or none>`, labels …). Attachments will be handled after creation. Create it? You can also pick another project from `<allowed projects>` or another type from `<allowed types>`.

If the user picks a different project or type, re-run preview with `--project` / `--type`, and ask once more with the new target. Never ask for the Jira URL, email or token: they come from `config/jira.config.json` and `.env`.

## Step 6. Create

Only after the user says yes to the exact target:

```bash
python .github/skills/jira-create-ticket/scripts/jira_create.py create .jira/drafts/<slug>/story.md --confirm-project <KEY> --confirm-type "<type>"
```

Report the issue key and link. The script writes `status: created`, `jira_key` and `jira_url` back into the draft, so the same draft can never be created twice. Add the new key to the Dependencies / links of later stories that depend on it.

## Step 7. Select and attach original files

After creation, ask which folder to use, even if a shared-folder path was mentioned earlier; offer that path and the selected `docs/<folder>` as choices. The user can instead provide a local folder or file path. Propose only the **original** documents this story relies on (Word, Excel, PDF…). Never propose converted `.csv`/`.md` copies, sample CSVs, briefs, story maps, previews or payloads; preview fails on `.csv`/`.md` or `.jira/` attachments for concise stories. Ask the user to confirm the issue key and the exact set. Do not upload if the folder is inaccessible, contains no eligible files, or the user has not confirmed.

Add the selected paths to the created draft's `attachments` front matter. Use repo-relative paths for files under the repository and absolute paths for external/shared locations. Then run:

```bash
python .github/skills/jira-create-ticket/scripts/jira_create.py attach .jira/drafts/<slug>/story.md --confirm-issue <KEY> --confirm-files "file one.pdf" "file two.xlsx"
```

The command requires the confirmation issue key to match `jira_key`, verifies the exact filenames against the draft, validates type and size, uploads only files not already recorded in `uploaded_attachments`, and records successful uploads for safe retries. Report any failed files; never create the issue again. Then repeat Steps 4–7 for the next story in the map.

After the last story, list every created key with its link. Suggested next step per story: `git checkout -b feature/<KEY>-<entity>`, then `/jira-ticket <KEY>` and `/dev <KEY> <ENTITY>`.

## What not to do

- Do not assume the whole spec set is one story; agree the story map first.
- Do not create a story before both gates pass for that story, even if the user's first message said "create it".
- Do not edit `config/jira.config.json` or `.env`, and do not print their contents.
- Do not paste data values from CSV or Excel data sheets into a story, and do not list every column.
- Do not name converted `.csv`/`.md` files in a story or attach them.
- Do not commit anything under `.jira/` (it is git-ignored).
