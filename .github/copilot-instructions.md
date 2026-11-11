# Copilot guidance

## Route Jira story and feature requests

When the user asks the default agent to draft, split, plan, or create a Snowflake Jira story or feature from requirements or specifications, do not perform that workflow in the default agent. Briefly explain that this workspace has dedicated agents and guide the user to select the matching agent in the agent picker:

- For stories, use [`story-writer`](./agents/story-writer.agent.md).
- For features, use [`feature-writer`](./agents/feature-writer.agent.md).

Do not claim to have switched agents or completed the work. This routing guidance does not apply to general questions about stories or features that do not ask for drafting or creation.

## Specification analysis and breakdown

When the user asks to analyze Snowflake specifications or derive capabilities, implementation tasks, acceptance criteria, dependencies, risks, traceability, or gaps, route to the `feature-writer` agent—even when they ask only for a proposed breakdown and do not want Jira issues created yet. Do not claim to have switched agents; direct the user to select it in the agent picker.

## General guidance

For any other requests related to Snowflake stories or features that do not fall under the above categories, provide guidance or explanations without attempting to draft or create Jira issues. Always ensure the user is aware of the dedicated agents for story and feature creation when relevant.