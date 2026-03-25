<!-- confluence-page-id: -->
<!-- confluence-space-key: PUBDOC -->

# Confluence Connector - Documentation Plan

## Objective

Create public documentation for the Confluence Connector v2 (Jira UN-16966, NFR-6: "Clear, maintainable public documentation").

## Reference Sources

| Source | Purpose |
|--------|---------|
| SharePoint Connector docs (`services/sharepoint-connector/docs/`) | Gold standard template - mirror structure and quality |
| Outlook Semantic MCP PR #396 review comments | Lessons learned - avoid known pitfalls from 50 reviewer comments |
| Confluence Connector v2 codebase (`services/confluence-connector/src/`) | Source of truth - every claim must be verifiable against code |

## Documentation Structure

```
services/confluence-connector/docs/
├── DOCUMENTATION_PLAN.md        (This file)
├── README.md                    (Main overview & quick start)
├── faq.md                       (Frequently asked questions)
├── operator/
│   ├── README.md                (Operator guide home)
│   ├── authentication.md        (Confluence Cloud/DC auth setup)
│   ├── configuration.md         (Tenant config, env vars, YAML)
│   └── deployment.md            (Container, Helm, infrastructure)
└── technical/
    ├── README.md                (Technical reference home)
    ├── architecture.md          (System design & components)
    ├── flows.md                 (Sync flows, file diff, discovery)
    ├── permissions.md           (Confluence API & Unique permissions)
    └── security.md              (Security practices & compliance)
```

## Process Per File

Each documentation file goes through the full pipeline before moving to the next:

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1: WRITE                                              │
│  - One agent writes one doc file                            │
│  - Uses SharePoint equivalent as structural template        │
│  - Verifies all claims against actual codebase              │
│  - Applies PR #396 review lessons                           │
│                                                             │
│  Step 2: REVIEW (3 agents in parallel, reports only)        │
│  - Agent A: Truthfulness audit                              │
│    Cross-checks every claim against code                    │
│  - Agent B: Completeness audit                              │
│    Compares against SharePoint equivalent doc               │
│  - Agent C: Anti-pattern audit                              │
│    Applies PR #396 reviewer feedback checklist              │
│                                                             │
│  Step 3: ORCHESTRATE (Agent D)                              │
│  - Reads all three review reports                           │
│  - Synthesizes findings, resolves conflicts                 │
│  - Applies fixes with truthfulness as gating constraint     │
│  - Verifies each fix against code before applying           │
│                                                             │
│  Step 4: COMMIT & PUSH                                      │
│  - Commit the finalized file                                │
│  - Push to remote branch                                    │
└─────────────────────────────────────────────────────────────┘
```

## File Order

| # | File | Dependencies |
|---|------|-------------|
| 1 | `docs/README.md` | None - establishes overall narrative |
| 2 | `docs/faq.md` | README for context |
| 3 | `docs/operator/README.md` | README for context |
| 4 | `docs/technical/README.md` | README for context |
| 5 | `docs/operator/authentication.md` | Operator README |
| 6 | `docs/operator/configuration.md` | Operator README, authentication |
| 7 | `docs/operator/deployment.md` | Operator README, configuration |
| 8 | `docs/technical/architecture.md` | Technical README |
| 9 | `docs/technical/flows.md` | Architecture |
| 10 | `docs/technical/permissions.md` | Authentication, architecture |
| 11 | `docs/technical/security.md` | Architecture, permissions |

## PR #396 Review Lessons (Anti-Pattern Checklist)

These rules are enforced during every review cycle:

1. **No misleading claims**: Every statement must be literally true. "Full history" is not acceptable if there's a time limit.
2. **Don't duplicate central docs**: Link to central documentation (e.g., service user creation) instead of copying content.
3. **Verify permissions are correct**: Only list permissions that are actually required in the code.
4. **Don't invent terminology**: Use established terms only.
5. **Verify code matches docs**: Tool signatures, env vars, defaults must match actual source code.
6. **Don't include internal-only info**: Client-facing docs should not contain internal deployment specifics.
7. **Don't repeat content across files**: Link to detailed docs instead of duplicating.
8. **Be numerically precise**: Use exact numbers from code, not approximations.
9. **Use tables for structured data**: Permissions, env vars, and config options should be tables.
10. **Don't claim user action when automatic**: If something happens automatically, say so.
11. **Diagrams must be accurate**: Components should be grouped logically, not split unnaturally.
12. **Include Confluence metadata**: Every doc file must have `<!-- confluence-page-id: -->` and `<!-- confluence-space-key: PUBDOC -->` comments at the top.
13. **Cross-reference between sections**: Reference related docs, don't leave the reader guessing.
14. **Explain env vars in context**: Reference detailed explanations where they exist.
