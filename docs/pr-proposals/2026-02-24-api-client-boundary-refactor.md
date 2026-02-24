# PR Proposal

## Title
refactor(confluence-api): make API client the boundary between Cloud and DataCenter

## Description
- Replace the `ConfluenceApiAdapter` pattern with polymorphic API clients (`CloudConfluenceApiClient`, `DataCenterConfluenceApiClient`) extending an abstract `ConfluenceApiClient` base class
- Move all platform-specific logic (URL construction, response parsing, child fetching, space type filters) into the concrete subclasses
- Delete the adapter interface and both adapter implementations
- Add BDD-style tests for each client and the shared base behavior
