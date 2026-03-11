# PR Proposal

## Title
feat(outlook-semantic-mcp): resolve folder display names and report unrecognized folders in email search

## Description
- Validate `directories` condition values against the user's actual folders in the DB before building the search filter
- Fuzzy-match unrecognized folder references against display names (Levenshtein ≥ 80%) and replace with correct provider IDs
- Discard fully unrecognized folder references and surface a markdown summary to the LLM explaining what was excluded
- Update `SearchEmailsQuery.run()` return type to `{ results, searchSummary }` and update the MCP tool caller accordingly
