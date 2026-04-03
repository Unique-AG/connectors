# PR Proposal

## Title
docs(outlook-semantic-mcp): simplify technical docs by removing detailed sync process files

## Description
- Remove `full-sync.md`, `live-catchup.md`, `directory-sync.md`, `subscription-management.md` — internal process detail not needed in operator/architect docs
- Expand `### Sync Pipeline` in `architecture.md` with one concise paragraph per process
- Simplify `flows.md` by removing forward references to deleted files and inlining the subscription status table
- Fix all broken cross-references in `faq.md` and correct two stale answers that describe live catch-up buffering behavior removed in migration `0024_petite_masque.sql`
- Update `technical/README.md` to remove the 4 deleted file entries
