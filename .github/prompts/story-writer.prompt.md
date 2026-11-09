---
name: story-writer-prompt
agent: story-writer
description: Split spec documents and Excel sheets into one or more concise Jira stories, get each approved, then create them in Jira
argument-hint: <spec files or folder> [epic key]
---

Write Jira stories from these inputs: ${input:sources:spec files or folder, e.g. docs/producer_contract/}

What I want, how many stories (or "recommend"), and any context the documents do not say: ${input:brief:e.g. 2 stories, one for staging+history, one for reporting views; or leave blank}

Follow the story-writer agent workflow. Read the documents, then ask me how many stories are needed, the context of each, any missing details and the shared folder path, asking follow-ups as you go through the documents. Propose a story map and wait for my confirmation before drafting. Each story uses only Description, Acceptance criteria and Dependencies / links, does not list every column, and names only the original documents I shared. Stop for my review of each draft. Do not create anything in Jira until I have approved that draft and confirmed the project and issue type. After each issue is created, propose only the relevant original documents as attachments and wait for my confirmation of the issue key and exact filenames before uploading.