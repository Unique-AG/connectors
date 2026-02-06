# PR Proposal

## Ticket
UN-16933

## Title
feat(confluence-connector): implement tenant configuration loading with full auth schema

## Description
- Add tenant-config-loader.ts to read YAML configs and inject secrets from environment variables
- Implement full Confluence auth schema supporting cloud API token, on-prem PAT, and on-prem basic auth
- Create processing.schema.ts with Confluence-specific settings (concurrency, timeouts, scan interval)
- Wire up confluenceConfig, uniqueConfig, processingConfig in AppModule
- Add unit tests for config loading and validation
