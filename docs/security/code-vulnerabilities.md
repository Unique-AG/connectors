<!-- confluence-page-id: <NO CONFLUENCE ID REQUEST> -->
<!-- confluence-space-key: <NO CONFLUENCE ID REQUEST> -->

# Code vulnerabilities

CodeQL scans the code that we write. It finds flaws in our own code, for example an array access out of bounds. It does not scan dependencies or images. For those, read [Dependencies](./dependencies.md) and [Image vulnerabilities](./image-vulnerabilities.md).

For the whole process, read [SECURITY-PROCESS.md](../../SECURITY-PROCESS.md).

## What runs

CodeQL scans our workflow files, our JavaScript and TypeScript, and our Python. It runs on every PR and on every push to `main`. A repository ruleset requires the CodeQL result. A PR that adds an alert cannot merge. As a result, unsafe code does not reach `main`.

```mermaid
flowchart LR
  pr[Pull request] --> codeql[CodeQL scan]
  codeql -->|no new alert| merge[PR can merge]
  codeql -->|new alert| fix[Fix the code or dismiss with a reason]
  fix --> codeql
```

## If CodeQL blocks your PR

1. Read the alert in the Security tab, under code scanning.
2. If the alert is real, fix the code and push.
3. If the alert is a false positive, dismiss it and give a reason.

Do not dismiss an alert without a reason. The next scan of `main` closes a fixed alert.

## Where to look

| What | Where |
|---|---|
| Alerts | Security tab, code scanning, one category for each language |
| The ruleset | Repository settings, Rules. An admin changes it. See [The ruleset](#the-ruleset). |

## The ruleset

An admin sets one branch ruleset on the default branch. It makes the checks of this process required.

1. Open Settings, Rules, Rulesets, and add a branch ruleset for the default branch.
2. Add the rule "Require status checks to pass". Add the checks `gatekeeper` and `release-gate`.
3. Add the rule "Require code scanning results". Add the tool CodeQL. Set the security alerts to "High or higher" and the alerts to "Errors".

The check `release-gate` is skipped on a PR that is not a release PR. A skipped check counts as passing. The check is required so that a release PR cannot merge before the gate has run.
