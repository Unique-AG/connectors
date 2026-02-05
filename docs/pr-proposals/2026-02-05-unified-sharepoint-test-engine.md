# PR Proposal

## Title

test(sharepoint-connector): unify e2e mocks with shared stateful test engine

## Description

- Create `SharePointTestEngine` with unified store for all mock clients
- Refactor individual mocks (Graph, REST, HTTP, Ingestion HTTP) into adapters reading from shared store
- Integrate existing `UniqueStatefulMock` (GraphQL) into the unified store
- Update e2e tests to use single engine with one seed call for scenario setup
- Improve test maintainability by having single source of truth for all test state
