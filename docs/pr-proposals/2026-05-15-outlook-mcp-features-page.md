# PR Proposal

## Title

docs(outlook-semantic-mcp): add features page and delegated access setup guide

## Description

- Add a new `technical/features.md` page that catalogs user-facing features
  (Email Search, Draft Creation, Contact Resolution, Mailbox & Folder
  Listing, Delegated Access) with *what's supported* / *what's not
  supported* / *setup* sections.
- Document the three supported delegated-access configurations and how to
  set each up in Microsoft 365 — Exchange admin Full Access (GUI +
  PowerShell), user folder sharing via Outlook desktop, and shared inbox
  configured as a normal mailbox.
- Call out the Outlook root-mailbox visibility gotcha that makes the Graph
  `/users/{email}/mailFolders` endpoint work for folder-level shares — and
  why Outlook desktop hides the problem.
- Add an "How do I set up delegated access?" FAQ entry and wire cross-links
  from `README.md`, `technical/README.md`, and (optionally)
  `operator/configuration.md`.
