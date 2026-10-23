# Unplanned work

Use this when the work already happened and was not on the board. A client deploy, a vulnerability fix, a hotfix.

Copy this template. Every line is required. Ask for a blank line. Do not invent the person, the reason, the duration, or the check.

```markdown
# Unplanned work

**Work:**
**Who needed it:**
**Why it was urgent:**
**Time:**
**Confirm:**
```

The filled template is the description. The Work line is also the summary. Rewrite "about two hours" as `2h` and say so. Time here is time already spent, not a time box.

On top of the `mcp-server` label, add `mcp-server/unplanned`.

Assignee is the authenticated user (`atlassianUserInfo`).

After create:

1. `addOrEditJiraIssueWorklog`. `timeSpent` is the Time line. Leave the start unset. The comment is the Work line.
2. `listJiraIssueTransitions`. Pick the transition whose destination status is Done. If it requires a resolution, set Done. `transitionJiraIssue`. Match the destination status, not the transition's name.
3. `getJiraIssue` must show status Done, labels `mcp-server` and `mcp-server/unplanned`, and a worklog equal to Time.

Filter later:

```
project = UN AND labels = "mcp-server" AND labels = "mcp-server/unplanned" ORDER BY created DESC
```

Example. "Acme's admin asked us to deploy teams-mcp this afternoon because their pilot starts tomorrow. It took three hours. Confirm with the Acme health URL."

Summary: `Deploy teams-mcp to Acme`

```markdown
# Unplanned work

**Work:** Deployed teams-mcp to Acme.
**Who needed it:** Acme's admin
**Why it was urgent:** Their pilot starts tomorrow.
**Time:** 3h
**Confirm:** `curl -fsS https://acme.example/teams-mcp/health`
```
