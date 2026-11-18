# Story-writer SOP

## Purpose and scope

Turn Snowflake requirements into independently reviewable Jira Stories. Agree the Story map before drafting; optionally create each approved Story through the repository REST client. Existing Stories can also be linked to a confirmed Feature without drafting new ones.

## Prerequisites and inputs

- Complete [local setup](../README.md#clone-and-configure-locally); configure Jira only for online operations.
- Supply original Word/Excel requirement paths, Markdown/text requirements, or a specification directory. Sample CSVs expose only headers and row counts through the helper, never raw values.
- Provide desired outcomes, Story count or permission to recommend a split, boundaries, shared document path, and optional Feature/Epic key.
- No PDF conversion helper is supplied; provide an accessible supported requirements copy when needed. Original PDFs may be eligible attachments.

## Copilot harness

1. Open Chat in the repository and select **story-writer** in the agent picker. If the default agent presents routing choices, choose Story-writer, then select it in the picker yourself.
2. If available, invoke `/story-writer-prompt` and fill the source and brief inputs. Otherwise paste the example below. Prompt availability depends on the runtime.
3. The agent follows [spec-file-conversion](../.github/skills/spec-file-conversion/SKILL.md), [story-writer](../.github/skills/story-writer/SKILL.md), and [jira-create-ticket](../.github/skills/jira-create-ticket/SKILL.md). Ask it to read those files if automatic skill discovery is unavailable.
4. Answer scope/gap questions and confirm the Story map. Review each subsequent draft separately.
5. To continue to Jira, approve the current draft with a literal chat message `approved`, then confirm the project, issue type, and parent from the online preview. A map confirmation or question-form answer is not draft approval.
6. After creation, confirm the issue key and exact original filenames before attachments. Repeat per Story. Do not proceed if required tools/hooks are unavailable.

Example request:

```text
Read the specifications in docs\<spec-set>. Recommend a Story split and explain
the outcome, boundaries, acceptance criteria, traceability, and dependencies.
Ask about gaps. Confirm the Story map before drafting.
Draft only: do not create or update Jira issues or upload attachments.
```

Replace `<spec-set>` with a real directory. Later continuation must identify the draft to review; it does not waive either Jira gate.

## Local agent harness

1. In VS Code Chat, select the **Local** agent harness and then **story-writer**. This is not a standalone service or CLI.
2. Use `/story-writer-prompt` if exposed there, or paste the example below.
3. Confirm local file, edit, question, and terminal tools are available. Load the same three skills listed above; local execution does not remove any gate.
4. Allow the agent to read the requirements, ask its interview questions, and propose the map. Confirm collisions before reusing or overwriting converted inputs.
5. Review each draft and use a separate literal `approved` chat message only when satisfied. Then confirm the online target, tool confirmation, and any attachments.

Example request:

```text
Continue as story-writer for Feature <FEATURE-KEY>, using docs\<spec-set>.
Ask me to agree the Story count and scope. Load the conversion, story-writer,
and Jira skills. Propose the map first; do not create anything in Jira yet.
```

If the selected harness cannot load the agent or scripts, stop and resolve discovery/tools rather than executing an improvised Jira request.

## Outputs and completion checks

| Output | Check |
|---|---|
| `.jira/drafts/<set-slug>/inputs/<spec-folder-name>/` | Converted reference files; source files unchanged; overwrite decisions explicit |
| `.jira/drafts/<set-slug>/story-plan.md` | Every requirement mapped or explicitly excluded; user confirms split |
| `.jira/drafts/<story-slug>/story.md` | Only Description, Acceptance criteria, Dependencies / links as top-level sections; original document names, no column dumps |
| Preview files beside the draft | Offline preview has no FAIL; warnings and gaps surfaced |
| Optional Jira key/URL and attachment results | Per-Story approval and exact target confirmed; no duplicate creation |

Offline preview from the repository root:

```powershell
python .github\skills\jira-create-ticket\scripts\jira_create.py preview .jira\drafts\<story-slug>\story.md --offline
```

For existing-Story linking, confirm exact Feature/Story keys first. The client refuses cross-project links, wrong issue types, and replacing another parent. Report conflicts instead of retrying automatically.

## Troubleshooting and limitations

| Symptom | Action |
|---|---|
| Sources missing or multiple `docs/` folders | Supply/select the intended source directory |
| Conversion output already exists | Choose reuse or explicitly approve reconversion; do not silently overwrite |
| Approval denied | Send `approved` as a new literal chat message for that draft, not through a question form |
| Jira 401/403/404 | Stop; user/maintainer corrects credentials, access, or project configuration |
| Creation failed after reporting `CREATED` | Preserve/report the key; never run create again for that draft |
| Agent suggests `/jira-ticket` or `/dev` | Those helpers are absent; supply a brief and select snowflake-developer instead |

The [hook reference](guardrails.md) describes enforcement limits; hooks are not an unconditional security guarantee.

## References

- [Story-writer definition](../.github/agents/story-writer.agent.md)
- [Story prompt](../.github/prompts/story-writer.prompt.md)
- [Story template](../.github/skills/story-writer/templates/story-template.md)
- [Example Story](../.github/skills/story-writer/examples/producer-contract-story.md)
- [Snowflake developer SOP](snowflake-developer.md)
- [Repository overview](../README.md)
