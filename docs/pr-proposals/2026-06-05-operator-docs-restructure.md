# PR Proposal

## Ticket
UN-21063

## Title
docs(outlook-semantic-mcp): restructure operator docs for SaaS vs Self-Hosted clarity

## Description
- Rewrite README.md Quick Start as a single unified Self-Hosted numbered flow (replacing the split Mode A / Mode B lists) and a focused Unique SaaS checklist; move Security Checklist inline as step 7 of the Self-Hosted flow
- Split authentication.md into peer `## Unique SaaS` and `## Self-Hosted` top-level sections so SaaS operators find the admin consent URL immediately without reading the full Entra provisioning guide
- Move the Deployment Modes comparison table from README.md to deployment.md where it is contextually appropriate; remove the now-redundant Infrastructure Requirements pointer from README.md
