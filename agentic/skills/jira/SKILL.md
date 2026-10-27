---
name: jira
description: >-
  Writes and files Jira issues for the connectors on the mcp-servers component
  in project UN.
  Each issue has one focus and one ask that can be called done; otherwise it
  is split into sub-tasks, given a time box, or both. Descriptions stay short
  and end with a command, URL, or check that shows the work is finished. Use
  whenever someone asks for a Jira issue, ticket, task, bug, story, sub-task,
  or to log work, including a client deploy, a vulnerability fix, a hotfix, or
  other unexpected unplanned work. For work that already happened outside the
  plan, follow references/unplanned-work.md.
metadata:
  internal: true
compatibility: Requires the Jira MCP on https://unique-ch.atlassian.net.
---

# Jira issues

File issues through the Jira MCP. Do not use the REST API, `acli`, or a browser. If the Jira MCP is not connected, stop and say so.

Read a tool's schema before calling it. `createJiraIssue`, `transitionJiraIssue`, `getJiraIssue`, `getAccessibleAtlassianResources`, and `atlassianUserInfo` are primary tools. `listJiraIssueTransitions`, `addOrEditJiraIssueWorklog`, and `listJiraProjectIssueTypesMetadata` are deferred: `discover` them, then `executeRead` or `executeWrite`.

## One ask

Write the ask in one sentence that someone can mark done or not done. One focus, one ask, one issue.

Two asks in that sentence means the issue is not scoped. File one parent for the shared focus and a sub-task for each ask. Each sub-task has its own summary, its own ask, and its own `**Confirm:**`. Do not leave the pieces only in the parent description.

When the ask cannot be written yet, do not file an open-ended issue. It needs a time box, well-defined sub-tasks, or both.

- A time box is how long we will spend, then stop and re-scope. Put `**Time box:** 4h` on that issue. Set the original estimate to the same value when the create schema has that field.
- Sub-tasks count only when each one has an ask that can be finished.
- A time box is a cap on work still to do. It is not a worklog.

## Write it

- Summary: one line, verb plus object. Name the service, client, or CVE when you know it.
- Description: the ask, then the detail someone needs to do it. Keep it short. No filler: scalable, robust, seamless, leverage, going forward, as discussed, circle back, "we should look into".
- End every description with `**Confirm:**` and a command, URL, test name, or query that shows the work is finished. If you don't know the check, ask.

Every issue this skill creates is connectors work. What each label is for is in [references/label-explanation.md](references/label-explanation.md). Read that before setting any label.

Site `https://unique-ch.atlassian.net`, project `UN`, component `mcp-servers`, type `Task` for the parent. A sub-task's type is `Sub-task`. Set the component on the parent and on every sub-task. Leave the assignee unset unless the user names one or the reference says who.

## Example

One ask, one issue. Summary: `Pin the teams-mcp image on the Acme deploy`

```markdown
Set the Acme Helm release to image tag `sha-4f2c1a`.

**Confirm:** `kubectl -n acme get deploy teams-mcp -o jsonpath='{.spec.template.spec.containers[0].image}'`
```

Not one ask yet. Parent summary: `Fix teams-mcp reconnect failures on Acme`

```markdown
Reconnects on Acme fail and the failing hop is not known.

**Time box:** 4h
```

Sub-tasks:

1. `Capture one failed reconnect trace from Acme` — **Confirm:** the trace file is on the sub-task.
2. `Name the component that drops the reconnect` — **Confirm:** the sub-task names the component.

## Pick the ticket

Work that already happened and was not planned (a client deploy, a vulnerability fix, a hotfix): read [references/unplanned-work.md](references/unplanned-work.md). That reference adds a label, a worklog, and the move to Done. Several finished jobs are several issues. Sub-tasks when they share one focus, and each one follows that reference through to Done.

Anything else: the rules above. Do not add `mcp-server/unplanned`. Do not transition it. Do not log time.

## File it

1. `getAccessibleAtlassianResources`. Use the `cloudId` for `unique-ch.atlassian.net`. If that site is missing, stop.
2. `createJiraIssue` for the parent. Project `UN`, component `mcp-servers`, type `Task`, the summary, the description in markdown, label `mcp-server`, plus anything the reference adds. Component and labels go in the additional-fields parameter when the schema has no parameter for them: `{"components": [{"name": "mcp-servers"}]}`.
3. For each sub-task, `createJiraIssue` with type `Sub-task`, `parent` set to the parent key, the same component, the same label, and that sub-task's summary and description. If `Sub-task` is rejected, `listJiraProjectIssueTypesMetadata` and use the sub-task type in project `UN`.
4. Do the reference steps after create, on the parent and on each sub-task: worklog, then the transition to Done.
5. `getJiraIssue` for each key. Check the component is `mcp-servers` and the label is set, and check the status and worklog when the reference required them. Give the user every issue key and URL.

If create or a later step fails, report the keys that exist and the error. Do not claim a status you did not read back.
