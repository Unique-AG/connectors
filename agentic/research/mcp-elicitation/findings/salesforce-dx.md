# Salesforce DX MCP Server (`@salesforce/mcp`)

| Field | Value |
|---|---|
| Vendor | Salesforce (Salesforce CLI team); official |
| Category | dev-platform (enterprise data / CRM) |
| Tier | 2 |
| Source | open (https://github.com/salesforcecli/mcp @ 9bc98ba) |
| Language / SDK | TypeScript monorepo, `@modelcontextprotocol/sdk` ^1.17.3 / ^1.18.0 across packages (yarn.lock resolves 1.18.2); `@salesforce/mcp` 0.30.15 |
| Hosted endpoint | none (stdio via `npx @salesforce/mcp`); Salesforce's separately hosted MCP servers are a different, closed product not reviewed here |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

None. No match for `elicit`, `ElicitRequest`, `elicitInput`, `requestedSchema`, `InputRequired`, `input_requests` or `request_state` in any of the provider packages (dx-core, devops, code-analyzer, mobile-web, metadata-enrichment, scale-products). The resolved SDK, 1.18.2, already supports `elicitInput`; it is simply not used.

## Fallback without client elicitation support

Not applicable. Every place that needs a human decision instead returns or embeds natural-language instructions telling the agent to ask the user and stop (see below).

## Other human-in-the-loop mechanisms

- Prompt-text confirmations, the dominant pattern:
  - `delete_org` description: "ALWAYS confirm with the user before deleting an org", while its `annotations` are `{}` (no `destructiveHint`) ([delete_org.ts#L67](https://github.com/salesforcecli/mcp/blob/9bc98ba22f0efe4a901904db7d0c76ebdf09525d/packages/mcp-provider-dx-core/src/tools/delete_org.ts#L67), [#L75](https://github.com/salesforcecli/mcp/blob/9bc98ba22f0efe4a901904db7d0c76ebdf09525d/packages/mcp-provider-dx-core/src/tools/delete_org.ts#L75)).
  - DevOps `resolve_devops_center_deployment_failure` returns a result telling the agent to present "Do you want me to run full promotion ... Reply **Yes**, **Proceed**, or **Go ahead**" and not call `promote_devops_center_work_item` until the user confirms ([sfDevopsResolveDeploymentFailure.ts#L53-L56](https://github.com/salesforcecli/mcp/blob/9bc98ba22f0efe4a901904db7d0c76ebdf09525d/packages/mcp-provider-devops/src/tools/sfDevopsResolveDeploymentFailure.ts#L53-L56), [#L198-L202](https://github.com/salesforcecli/mcp/blob/9bc98ba22f0efe4a901904db7d0c76ebdf09525d/packages/mcp-provider-devops/src/tools/sfDevopsResolveDeploymentFailure.ts#L198-L202)). A two-step "recommend, then execute" split across tools, with the human gate enforced only by the model.
  - Promote / checkout / resolve-conflict tools: "Never promote without explicit user confirmation", "do not proceed until the user has explicitly chosen a repo path", "NEVER auto-resolve conflicts ... ask the user which side to keep" ([sfDevopsPromoteWorkItem.ts#L63-L65](https://github.com/salesforcecli/mcp/blob/9bc98ba22f0efe4a901904db7d0c76ebdf09525d/packages/mcp-provider-devops/src/tools/sfDevopsPromoteWorkItem.ts#L63-L65), [sfDevopsResolveConflict.ts#L69](https://github.com/salesforcecli/mcp/blob/9bc98ba22f0efe4a901904db7d0c76ebdf09525d/packages/mcp-provider-devops/src/tools/sfDevopsResolveConflict.ts#L69)). These are textbook `disambiguate` / `confirm-destructive` elicitation cases handled by prose.
  - `get_username` returns "no org was inferred. Ask the user to specify one" when it cannot resolve the target org.
- Org allowlist: the required `--orgs` flag (usernames, aliases, `DEFAULT_TARGET_ORG`, `DEFAULT_TARGET_DEV_HUB`, or `ALLOW_ALL_ORGS` with a warning) restricts which authenticated orgs any tool can touch ([index.ts#L55-L82](https://github.com/salesforcecli/mcp/blob/9bc98ba22f0efe4a901904db7d0c76ebdf09525d/packages/mcp/src/index.ts#L55-L82), [auth.ts#L73-L84](https://github.com/salesforcecli/mcp/blob/9bc98ba22f0efe4a901904db7d0c76ebdf09525d/packages/mcp/src/utils/auth.ts#L73-L84)).
- Tool selection: `--toolsets`, `--tools`, `--dynamic-tools`, and `--allow-non-ga-tools` (non-GA tools off by default).
- Annotations: 14 tools carry `readOnlyHint: true` (e.g. `run_soql_query`); only `deploy_metadata` and `retrieve_metadata` carry `destructiveHint: true` ([deploy_metadata.ts#L122-L125](https://github.com/salesforcecli/mcp/blob/9bc98ba22f0efe4a901904db7d0c76ebdf09525d/packages/mcp-provider-dx-core/src/tools/deploy_metadata.ts#L122-L125)).
- Auth is out of band: orgs must already be authorised with the Salesforce CLI (`sf org login`); no in-protocol auth.

## Notes

- Annotation coverage is inconsistent: `retrieve_metadata` (overwrites local files) is marked destructive but `delete_org` and `promote_devops_center_work_item` are not, so a client keying approval on `destructiveHint` would gate the wrong tools.
- The many "ask the user and wait" instructions show clear demand for form elicitation (choose org, choose repo path, choose ours/theirs per file, confirm promotion) that the server meets with prompt engineering only.
