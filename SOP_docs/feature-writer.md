# Feature-writer SOP

## Purpose and scope

Analyze Snowflake specifications and group requirements into coherent business capabilities. Propose a traceable breakdown for review, or continue to substantial Feature drafts and optionally Jira creation. Implementation tasks in an analysis are not permission to implement. New Story creation belongs to Story-writer.

## Prerequisites and inputs

- Complete [local setup](../README.md#clone-and-configure-locally).
- Supply a specification directory or explicit original file paths, desired business outcome, boundaries, constraints, and optional parent Epic.
- Choose analysis-only versus Feature drafting/creation. For Jira creation, the configured allow-list and the project must support `Feature`; the example configuration does not include it.
- If the Feature already exists, supply its key to avoid creating a duplicate.

## Copilot harness

1. Select **feature-writer** in the Chat agent picker. A default-agent routing question recommends it for specification analysis but does not switch agents.
2. There is no dedicated Feature prompt file; paste the example below.
3. The agent loads [spec-file-conversion](../.github/skills/spec-file-conversion/SKILL.md) and [jira-create-ticket](../.github/skills/jira-create-ticket/SKILL.md), using the [Story skill](../.github/skills/story-writer/SKILL.md) only for domain context, not its template. If skill discovery is absent, ask it to read those files explicitly.
4. Review the requirements, clarification questions, capability grouping, traceability, and proposed Feature boundaries.
5. For analysis-only work, stop at the reviewed proposal. To continue, explicitly request Feature drafts.
6. For each Jira-bound draft, review the offline preview, send `approved` as a separate literal chat message, and confirm the exact project/type after online preview. Never substitute another type if Feature is unavailable.

Example request:

```text
Analyze docs\<spec-set> as feature-writer. Present capabilities followed by
independently implementable tasks. For each task include objective, business
context, behavior, testable acceptance criteria, dependencies, source references,
edge cases, risks, and open questions. Flag gaps rather than assuming answers.
Proposal only: do not implement, create Jira issues, or change existing issues.
```

## Local agent harness

1. Choose VS Code Chat's **Local** harness and select **feature-writer**.
2. There is no Feature slash prompt; paste the example below. Confirm local read/edit/question/terminal tools and required hook support.
3. Load the same conversion and Jira skills; use Story-writer only as a domain reference.
4. Provide/select the source folder. The agent converts supported documents under the draft area, asks about existing outputs, and clarifies scope before proposing the Feature plan.
5. Review the plan and drafts. Plan agreement is not approval of any Feature. For Jira, follow separate content, target, tool, parent-change, and attachment confirmations.

Example request:

```text
Use feature-writer with docs\<spec-set>. Read and explain the requirements first,
then recommend how many Features are appropriate and why. Ask about missing
decisions. Use the repository conversion and Jira skills.
Prepare a proposal for review only; no implementation or Jira writes.
```

To continue to Stories, use **Create Stories for Feature** when that handoff is exposed. Otherwise manually select Story-writer and supply the Feature key, scope, and original source paths. Do not assume handoffs are supported in every runtime.

## Outputs and completion checks

| Output | Check |
|---|---|
| Analysis-only proposal | Capability/task hierarchy, measurable acceptance criteria, dependencies, gaps, and original-source traceability; no implementation/Jira changes |
| `.jira/drafts/<set-slug>/feature-plan.md` when drafting | Requirements mapped to Features or exclusions, boundaries and rationale recorded |
| `.jira/drafts/<feature-slug>/feature.md` | Context / Why, Scope, Out of scope, Acceptance criteria, Dependencies / links, Definition of Ready, Definition of Done |
| Optional created Features | Each has its own explicit approval, confirmed target, key and URL |

Offline check when a Feature draft exists:

```powershell
python .github\skills\jira-create-ticket\scripts\jira_create.py preview .jira\drafts\<feature-slug>\feature.md --type "Feature" --offline
```

Confirmed existing Stories may be made children of a created/existing Feature using the Jira skill's `set-parent` command. Confirm exact keys first. Do not replace a different parent or invent a Jira hierarchy. Original attachments are optional and require explicit filename/key confirmation after creation.

## Troubleshooting and limitations

| Situation | Action |
|---|---|
| Feature type unavailable | Stop; maintainer must verify project support and allow-list; do not substitute Story or Epic |
| Existing Feature supplied | Continue with that Feature or offer Story workflow; do not draft a duplicate |
| Standards/reference objects absent or conflicting | Ask the owner; do not invent schema names or contracts |
| Question-form approval rejected | Use a separate literal `approved` chat message for the current draft |
| Unsupported source format | Request a supported accessible copy; do not install an arbitrary converter |

Review [guardrail limitations](guardrails.md) before Jira operations. Analysis-only requests never authorize issue creation.

## References

- [Feature-writer definition](../.github/agents/feature-writer.agent.md)
- [Jira skill](../.github/skills/jira-create-ticket/SKILL.md)
- [Story-writer SOP](story-writer.md)
- [Repository overview](../README.md)
