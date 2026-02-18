# PR Proposal

## Ticket
UN-16935

## Title
feat(confluence-connector): implement page discovery and content fetching sync

## Description
- Add `ConfluencePageScanner` that discovers labeled pages via CQL search and recursively expands children for "ingest all" pages
- Add `ConfluencePageProcessor` that fetches full page content (body, labels, space metadata) for discovered pages
- Wire up `ConfluenceSynchronizationService` to orchestrate scanner then processor with discovery/processing summaries
- Respect `maxPagesToScan` config limit, skip databases, handle individual page errors gracefully
