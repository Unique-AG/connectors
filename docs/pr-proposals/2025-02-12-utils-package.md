# PR Proposal

## Title

feat(utils): create shared @unique-ag/utils package

## Description

- Create `packages/utils/` with general-purpose utilities extracted from `sharepoint-connector` and `teams-mcp`: `Redacted`, `Smeared`/`smear`, `normalizeError`/`sanitizeError`, timing helpers, and Zod codecs
- Package uses optional peer dependencies for `zod` and `typeid-js` so consumers only install what they need
- Includes migrated tests from source services plus new tests for previously untested utilities (`timing`, `zod`)
- Services are not yet updated to consume the package; adoption will follow in separate PRs
