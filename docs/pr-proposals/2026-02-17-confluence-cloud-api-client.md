# PR Proposal

## Ticket
UN-16936

## Title
feat(confluence-connector): implement Confluence API client with Cloud and Data Center adapters

## Description
- Add `ConfluenceApiClient` with Bottleneck rate limiting, undici HTTP, auth header injection, pagination, and 429 retry handling
- Implement `CloudApiAdapter` and `DataCenterApiAdapter` for instance-type-specific URL construction, response parsing, and child page fetching
- Add `ConfluenceApiClientFactory` to create the correct client/adapter combo based on tenant config, registered in `ServiceRegistry`
- Add unit tests for client, both adapters, and factory
