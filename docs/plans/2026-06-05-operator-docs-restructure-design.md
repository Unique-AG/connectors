# Design: Operator Docs Restructure

**Ticket:** UN-21063

## Problem

The current operator docs (`services/outlook-semantic-mcp/docs/operator/`) have three overlapping issues:

1. **README.md is unfocused** — it mixes overview content, a mode comparison table, a documentation index, two separate Quick Start flows (one per mode), an infrastructure requirements blurb (just a pointer), and two standalone checklists. An operator landing on the page doesn't know where to start.

2. **Self-Hosted Quick Start is split by mode** — Mode A and Mode B have nearly identical setup steps but are listed as two separate numbered lists, duplicating steps 1–3. The mode choice only affects step 4 onward, so it should be one unified flow with a single decision point at the Helm values step.

3. **authentication.md conflates two audiences** — Unique SaaS operators (who only need to paste an admin consent URL) must read through the entire Entra app registration guide before finding their section. The file should open with `## Unique SaaS` and `## Self-Hosted` as peer top-level sections.

## Solution

### Overview

Three files change; one file stays the same:

- **README.md** — full restructure: Overview → Architecture → Quick Start → Scaling Considerations → Documentation index. The Quick Start is the centrepiece — Unique SaaS is a short checklist, Self-Hosted is a single unified numbered flow for both modes.
- **authentication.md** — split into `## Unique SaaS` (admin consent only) and `## Self-Hosted` (full Entra provisioning); Required Permissions stays as a shared section above both.
- **deployment.md** — receives the Deployment Modes comparison table moved from README; no other changes.
- **configuration.md** — no structural changes; already well-organised by sections.

### Architecture

#### README.md — New Structure

```
# Outlook Semantic MCP — Operator Manual

## Overview
(current content, trimmed to 2–3 sentences)

## Architecture
(current Mermaid diagram)
(note: Unique Knowledge Base is required in BOTH modes — Mode B just doesn't write to it via ingestion, but it is still needed for scope management and search)

## Quick Start

### Unique SaaS
- One-decision checklist: Backend mode + Delegated access scan
- Admin consent URL
- "Contact Unique Support/SE with your choices"
- Callout: "For full capabilities, see Configuration Guide"

### Self-Hosted
1. Register Entra app → authentication.md
2. Create Zitadel service account → configuration.md#Zitadel (required for BOTH modes)
3. Provision infrastructure → deployment.md#Prerequisites
4. Create Kubernetes secrets → deployment.md#Required-Secrets
5. Configure Helm values → configuration.md
   ↳ callout box: key decisions here — MCP_BACKEND and DELEGATED_ACCESS_SCAN
6. Deploy with Helm → deployment.md#Install
7. Security Checklist (inline — currently a standalone H2 at the bottom of README)
8. Verify deployment
   a. curl /.well-known/oauth-authorization-server
   b. Connect MCP client + complete OAuth flow
   c. Call verify_inbox_connection → confirm webhook active
   d. Send test email → search_emails confirms it appears
   e. (Mode B only: search_emails with a KQL query, no webhook step)
9. (Optional) Enable delegated access → configuration.md#DELEGATED_ACCESS_SCAN

## Scaling Considerations
(current content, unchanged)

## Documentation
(current table, unchanged)
```

Removed from README:
- "Deployment Modes" section (table moves to deployment.md)
- "Infrastructure Requirements" section (one-sentence pointer — redundant with Documentation table)
- Standalone "Deployment Checklist" section (absorbed into the numbered Self-Hosted flow)
- Standalone "Security Checklist" section (moved inline as step 7)

#### authentication.md — New Structure

```
# Authentication

## Required Permissions
(keep the permissions table — shared between both paths)
(link: for justifications see technical/permissions.md)

## Unique SaaS
- Unique provisions and manages the Entra registration
- You only need to grant admin consent:
  (consent URL)
- Note about multiple tenants
- Note about user vs. admin consent (optional but skips per-user prompt)

## Self-Hosted
### App Registration
  #### Option 1: Terraform (Recommended)
  #### Option 2: Azure Portal (Manual)
### Redirect URI Configuration
### Tenant Configuration
  #### Single Tenant
  #### Multi-Tenant
### Secret Management
  (MICROSOFT_CLIENT_SECRET, WEBHOOK_SECRET, ENCRYPTION_KEY, AUTH_HMAC_SECRET)
### Understanding Consent Flows

## Microsoft Documentation
(unchanged)
```

The current intro paragraph ("How the app registration is provisioned depends on your deployment model") becomes a one-sentence opener before `## Required Permissions`.

#### deployment.md — Addition

The Deployment Modes comparison table currently in README moves to the top of deployment.md, before `## Prerequisites`:

```
## Deployment Modes
| | MicrosoftGraphAndUniqueApi | MicrosoftGraph |
...
(link to configuration.md#MCP_BACKEND for details)
```

### Error Handling

No runtime behaviour changes — this is a docs-only restructure. Cross-link correctness is the main risk: anchor IDs must be verified after each file is rewritten (Confluence page IDs are preserved, anchor hrefs within operator docs must be updated to match new section headings).

### Testing Strategy

Manual verification: after changes, walk through both Quick Start paths (SaaS and Self-Hosted) in the README and confirm every link resolves. Check that no section referenced from external docs (technical/, faq.md) is renamed without updating those files.

## Out of Scope

- Changes to `configuration.md` content or structure
- Changes to `local-development.md` or `disaster-recovery.md`
- Changes to `technical/` or `faq.md` docs
- Adding new content (e.g. new diagrams, new sections)
- Any changes to source code

## Tasks

1. **Restructure README.md** — Rewrite to the new structure: Overview → Architecture → Quick Start (Unique SaaS checklist + unified Self-Hosted numbered flow with Security Checklist inline as step 7) → Scaling Considerations → Documentation table. Remove Deployment Modes table, Infrastructure Requirements section, standalone Deployment Checklist, and standalone Security Checklist.

2. **Move Deployment Modes table to deployment.md** — Add the mode comparison table as a new `## Deployment Modes` section near the top of deployment.md (before Prerequisites). Update the README cross-link that currently points to `./configuration.md#MCP_BACKEND` to point to `./deployment.md#Deployment-Modes`.

3. **Restructure authentication.md** — Promote `Unique SaaS` and `Self-Hosted` to top-level H2 sections. Move Required Permissions above both as a shared section. Trim the intro to one sentence.

4. **Verify cross-links** — After the above changes, walk every cross-link from README.md and authentication.md to confirm anchors resolve correctly. Update any broken links in faq.md or technical/ docs that reference renamed sections.
