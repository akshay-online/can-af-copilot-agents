---
agent: story-writer
description: Draft a Jira story from spec documents and Excel sheets, get it approved, then create it in Jira
argument-hint: <spec files or folder> [epic key]
---

Write a Jira story from these inputs: ${input:sources:spec files or folder, e.g. specs/producer_contract/}

What I want the agent to do, plus any extra details, assumptions or context I have: ${input:brief:describe the story to write and anything the documents do not say, or leave blank}

Save my brief as `.jira/drafts/<slug>/inputs/user-brief.md` and treat it as my instructions. If the brief is blank or unclear, ask me for it before drafting.

Follow the story-writer and spec-file-conversion skills. If no input paths are given, inspect `docs/`; ask which folder to use if it has multiple folders, and ask whether specs are missing or should be added if it is empty. Ask for the shared-folder path to reference in the story, or accept `none`. Convert the inputs and draft `.jira/drafts/<slug>/story.md` from the team template, then stop for my review. Do not create anything in Jira until I have approved the draft and confirmed the project and issue type. After the issue is created, ask which folder to use for attachments, list candidate filenames, and wait for confirmation of the issue key and exact filenames before uploading.