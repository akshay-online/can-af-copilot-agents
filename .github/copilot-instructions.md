# Copilot guidance

## Route Jira story and feature requests

When the user asks the default agent to draft, split, plan, create, or analyze Snowflake Jira stories, features, or specifications, do not perform that workflow in the default agent. Use the native `#askQuestion` single-select UI (or equivalent question tool) with the prompt **“Which agent would you like to proceed with?”**. Tailor the explanation and recommendation to the user's task:

- **Story-writer** — explain that it is for turning requirements into Jira story drafts, agreeing the story map, reviewing and approving each draft, and optionally creating approved stories in Jira. Recommend it when the user asks to draft, split, or create Jira stories.
- **Feature-writer** — explain that it is for analyzing specifications and deriving capabilities, implementation tasks, acceptance criteria, dependencies, risks, traceability, or gaps. Recommend it when the user asks for feature work or specification analysis/breakdown, including a proposed breakdown without Jira creation.

In the question prompt, briefly connect the recommendation to what the user actually asked for; do not show generic descriptions without applying them to the task. Also make clear that the default agent is only routing the user: after choosing, they must select the matching agent in the agent picker for it to do the work. Do not claim to have switched agents or completed the work. If the question UI is unavailable, provide the two choices as links with the same concise, task-specific explanation and tell the user to select the matching agent in the picker. This routing guidance does not apply to general questions about stories or features that do not ask for analysis, drafting, breakdown, or creation.

## Specification analysis and breakdown

For specification analysis or breakdown requests, use the routing guidance above and recommend **Feature-writer**, even when the user only wants a proposed breakdown and does not want Jira issues created yet. Mention that **Story-writer** is the better fit if they want Jira story drafts and the subsequent review/approval workflow.

## General guidance

For any other requests related to Snowflake stories or features that do not fall under the above categories, provide guidance or explanations without attempting to draft or create Jira issues. Always ensure the user is aware of the dedicated agents for story and feature creation when relevant.