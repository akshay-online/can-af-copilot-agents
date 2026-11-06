---
status: draft  # draft -> approved (only after a human says so in chat) -> created (set by the script)
story_format: concise
summary: TODO <ENTITY>: <what is built, in one line, max 255 chars>
project:  # leave empty to use default_project from config/jira.config.json
issue_type: Story
parent:  # epic / feature key, e.g. DATA-120, or empty
labels: [snowflake]
components: []
priority:
story_points:
attachments: []  # populated after issue creation; repo-relative paths or absolute shared/local paths
sources: []  # internal traceability only; never sent to Jira
jira_key:
jira_url:
---

# TODO <same text as summary>

<!--
Keep only the three top-level sections below. Reference original document names,
not generated Markdown/CSV files or internal brief/plan filenames. Leave column
definitions in the original Excel workbook. Remove optional subsections unless
this story needs them. Ask about unknowns; put remaining gaps and owners in
Dependencies / links. Replace every TODO before preview.
-->

## Description

### Context / Why

TODO business need and outcome for this story within the agreed story split

### Scope

TODO deliverables and boundaries for this story; reference original document names

### Load rules

<!-- Optional: include only when load behavior is part of this story. -->
TODO necessary load behavior, numbered LR-n

### Data validations

<!-- Optional: include only when validation behavior is part of this story. -->
TODO necessary validation rules, numbered DVF-n

### Masking

<!-- Optional: include only when masking is part of this story. -->
TODO necessary masking behavior; refer to the original workbook for column details

### Attachments / documents file path

- Shared folder: TODO user-provided shared folder path, or none
- Documents: TODO original document names required for this story

## Acceptance criteria

- [ ] **AC-1 Objects:** Given TODO, when TODO, then TODO.

## Dependencies / links

- TODO related stories, access requirements, dependencies, and unresolved gaps with owners