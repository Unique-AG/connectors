# HubSpot CLI MCP server (`hs mcp`)

| Field | Value |
|---|---|
| Vendor | HubSpot; official (developer-tooling MCP bundled in the HubSpot CLI, distinct from HubSpot's hosted CRM MCP) |
| Category | dev-platform |
| Tier | 2 |
| Source | open (https://github.com/HubSpot/hubspot-cli @ e5740a6) |
| Language / SDK | TypeScript, `@modelcontextprotocol/sdk` 1.32.1 (package.json) |
| Hosted endpoint | none (local stdio via `hs mcp start`) |
| Uses elicitation | yes |
| Mechanism | legacy `elicitation/create` request (`mcpServer.server.elicitInput`, 5-minute timeout) |
| Evidence type | code |

## Elicitation usages

Permalink base: `https://github.com/HubSpot/hubspot-cli/blob/e5740a69086c637295e005c5dd4213ca16d5924f/`

All calls go through `requestElicitation` ([mcp-server/utils/elicitation.ts#L39-L70](https://github.com/HubSpot/hubspot-cli/blob/e5740a69086c637295e005c5dd4213ca16d5924f/mcp-server/utils/elicitation.ts#L39-L70)), which returns `undefined` when the client lacks form elicitation or the request fails, and the picker helper `elicitSelection` ([mcp-server/utils/elicitSelection.ts#L11-L52](https://github.com/HubSpot/hubspot-cli/blob/e5740a69086c637295e005c5dd4213ca16d5924f/mcp-server/utils/elicitSelection.ts#L11-L52)), which skips the prompt when there is exactly one option.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `deploy-project`, `upload-project` when any target account is classified `PRODUCTION_WITH_CARE` | form | confirm-destructive (production target) | "Deploy build #<n> to production account <account>?" / "Upload <project> to production account <account>?"; empty schema (`fields: {}`), so accept/decline only | Non-accept, failure or timeout -> error text "The user did not confirm production account <acct>, so <tool> did not run. Tell the user that the action was canceled. Do not ask the user to confirm again, and do not call <tool> again unless the user asks." | [mcp-server/tools/project/productionConfirmation.ts#L47-L94](https://github.com/HubSpot/hubspot-cli/blob/e5740a69086c637295e005c5dd4213ca16d5924f/mcp-server/tools/project/productionConfirmation.ts#L47-L94); callers [DeployProjectTool.ts#L78](https://github.com/HubSpot/hubspot-cli/blob/e5740a69086c637295e005c5dd4213ca16d5924f/mcp-server/tools/project/DeployProjectTool.ts#L78), [UploadProjectTools.ts#L111](https://github.com/HubSpot/hubspot-cli/blob/e5740a69086c637295e005c5dd4213ca16d5924f/mcp-server/tools/project/UploadProjectTools.ts#L111) |
| `upload-project` with several project profiles and no `profile` arg | form | disambiguate | "Select the profile to use for the upload."; schema `selection` (required string enum of profile names, `enumNames` labels naming target accounts) | Error text "Several profiles are available. Ask the user which to use, then call upload-project again with the profile argument set to one of ...", listing the accounts each targets | [UploadProjectTools.ts#L87-L101](https://github.com/HubSpot/hubspot-cli/blob/e5740a69086c637295e005c5dd4213ca16d5924f/mcp-server/tools/project/UploadProjectTools.ts#L87-L101) |
| Account resolution in `search-docs`, `get-build-logs`, `get-build-status`, `get-api-usage-patterns-by-app-id`, `get-feature-config-schema`, `submit-feedback`, `get-apps-info` when several accounts exist, none recommended, and `account` arg absent or unmatched | form | disambiguate | "Select the HubSpot account to use."; schema `account` (required string enum of account IDs, `enumNames` of account labels) | Text "Several HubSpot accounts are available. Ask the user which to use, then call <tool> again with the account argument set to one of: ..." | [mcp-server/tools/project/resolveAccount.ts#L66-L108](https://github.com/HubSpot/hubspot-cli/blob/e5740a69086c637295e005c5dd4213ca16d5924f/mcp-server/tools/project/resolveAccount.ts#L66-L108) |
| `find-projects` finding several project configs under the directory | form | disambiguate | "Select the HubSpot project to use."; `selection` enum of project dirs | Text "Several projects are available. Ask the user which to use, then call find-projects again with absoluteDirectory narrowed to one of: ..." | [mcp-server/tools/project/FindProjectsTool.ts#L54-L68](https://github.com/HubSpot/hubspot-cli/blob/e5740a69086c637295e005c5dd4213ca16d5924f/mcp-server/tools/project/FindProjectsTool.ts#L54-L68) |
| `get-api-usage-patterns-by-app-id` without `appId` | form | fill-missing-param | "Select the app to inspect usage patterns for."; `selection` enum of "<appName> (<appId>)" | Text "Several apps are available. Ask the user which to use, then call ... with the appId argument ..." | [mcp-server/tools/project/GetApiUsagePatternsByAppIdTool.ts#L98-L112](https://github.com/HubSpot/hubspot-cli/blob/e5740a69086c637295e005c5dd4213ca16d5924f/mcp-server/tools/project/GetApiUsagePatternsByAppIdTool.ts#L98-L112) |
| `get-cms-serverless-function-logs` without `endpoint` | form | fill-missing-param | "Select the CMS serverless function to get logs for."; `selection` enum of routes (deduped), labels "<METHOD> <route>" | Text "Several functions are available. Ask the user which to use, then call ... with the endpoint argument ..." | [mcp-server/tools/cms/HsFunctionLogsTool.ts#L102-L113](https://github.com/HubSpot/hubspot-cli/blob/e5740a69086c637295e005c5dd4213ca16d5924f/mcp-server/tools/cms/HsFunctionLogsTool.ts#L102-L113) |
| `auth-account` when a different default account already exists | form | other (preference: change default account) | "<current> is the default HubSpot account. Set the account you authenticate now as the new default?"; `setAsDefault` (required boolean, default `true`) | Decline/cancel -> keep the old default. No elicitation support -> set the new account as default | [mcp-server/tools/project/AuthAccountTool.ts#L110-L137](https://github.com/HubSpot/hubspot-cli/blob/e5740a69086c637295e005c5dd4213ca16d5924f/mcp-server/tools/project/AuthAccountTool.ts#L110-L137) |

## Fallback without client elicitation support

- Capability check: `canElicit` = `getClientCapabilities()?.elicitation?.form` is truthy ([elicitation.ts#L27-L29](https://github.com/HubSpot/hubspot-cli/blob/e5740a69086c637295e005c5dd4213ca16d5924f/mcp-server/utils/elicitation.ts#L27-L29)). A client that sends a bare `elicitation: {}` only counts if the SDK normalises it to `{form: {}}`. That was not checked here.
- Pickers degrade to "ask in chat, then re-call": the tool returns text listing the choices and naming the argument to set (`account`, `profile`, `appId`, `endpoint`, `absoluteDirectory`). Decline and no-capability produce the same text.
- Production confirmation degrades to a model-set boolean argument: `confirmProductionAccount`, described as "Set to true only after this tool names a production account and the user then explicitly confirms that account in the conversation. NEVER set this on your own. The tool ignores this value when the client can show a confirmation form." ([constants.ts#L18-L22](https://github.com/HubSpot/hubspot-cli/blob/e5740a69086c637295e005c5dd4213ca16d5924f/mcp-server/tools/project/constants.ts#L18-L22)). Without the capability and without the flag, the tool returns an error asking the model to get confirmation and call again with the flag. With the capability, the flag is ignored and a failed or timed-out elicitation counts as a decline, so the model cannot skip the form.
- `auth-account` default-switch silently proceeds with the default answer (`true`).

## Other human-in-the-loop mechanisms

- `confirmProductionAccount` tool argument as a conversational two-step confirmation (above).
- Account classification (`PRODUCTION_WITH_CARE` vs test/sandbox) decides whether to confirm at all. Uploads and deploys to test and sandbox accounts are not prompted.
- `readOnlyHint` / `destructiveHint` annotations on all tools (34 occurrences); `destructiveHint: true` on `deploy-project` and `upload-project`.

## Notes

- This server shows a clear pattern for elicitation with a fallback: every prompt has a fallback in text or an argument, and the fallback messages tell the model what to do next ("Ask the user which to use, then call X again with ...").
- The production confirmation uses an empty-schema form as a plain yes/no dialog.
- The decline message tells the model not to ask again ("Do not ask the user to confirm again, and do not call <tool> again unless the user asks"), so the model does not nag after a decline.
- The argument fallback trusts the model to have asked the user. The tool cannot verify it.
