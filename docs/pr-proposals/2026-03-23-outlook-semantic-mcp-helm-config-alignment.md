# PR Proposal

## Title
chore(outlook-semantic-mcp): align helm config with src/config

## Description
- Split monolithic `config.yaml` into named template partials (`_config-*.tpl`) per config domain, producing a single ConfigMap as before
- Expose missing env vars in `values.yaml`: `BUFFER_LOGS`, `MICROSOFT_SUBSCRIPTION_EXPIRATION_TIME_HOURS_UTC`, `UNIQUE_STORE_INTERNALLY`
- Set optional fields (those with zod defaults) to `null` so they are only emitted when explicitly set by the operator
- Remove 5 stale entries and add 9 missing entries to `.env.example`
