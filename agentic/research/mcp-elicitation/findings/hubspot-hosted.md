# HubSpot remote MCP server (hosted CRM server)

| Field | Value |
|---|---|
| Vendor | HubSpot; official (hosted CRM/marketing server, distinct from the CLI developer MCP in `hubspot.md`) |
| Category | other (CRM / marketing) |
| Tier | 2 |
| Source | closed (https://mcp.hubspot.com) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://mcp.hubspot.com |
| Uses elicitation | unknown (docs require "user confirmation" for writes but don't say how it is collected) |
| Mechanism | docs don't say |
| Evidence type | docs only |

Sources:
- Developer doc: [Integrate AI tools with the HubSpot MCP server](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/integrate-with-the-remote-hubspot-mcp-server) (cited as "dev doc")
- Overview: [Remote MCP server](https://developers.hubspot.com/docs/build-with-ai/remote-mcp-server)
- Knowledge base: [Set up and use the HubSpot connector for Claude](https://knowledge.hubspot.com/integrations/set-up-and-use-the-hubspot-connector-for-claude) and [Connect your HubSpot account to ChatGPT](https://knowledge.hubspot.com/integrations/connect-your-hubspot-account-to-chatgpt). These describe the Claude and ChatGPT connectors. They refer to "HubSpot's MCP server" in the FAQ and link a resource titled "...HubSpot connector for Claude with Remote MCP", but they never say outright that the connector is this server.

## Elicitation usages

The dev doc names a confirmation step for each write tool. It doesn't say whether the server collects it (form elicitation or otherwise) or whether it relies on the client or the model. The doc never uses the word "elicitation".

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `manage_crm_objects` (create/update records or activities) | docs don't say | other (confirm write) | "The tool presents a proposed-changes summary for user review" and "requires explicit user confirmation before executing any create or update." | docs don't say | dev doc, Available tools |
| `manage_segment` | docs don't say | other (confirm write) | "Requires explicit user confirmation before each write." | docs don't say | dev doc |
| `manage_campaign_objects` | docs don't say | other (confirm write) | "Requires user confirmation before creating or modifying campaigns." | docs don't say | dev doc |
| `manage_landing_page` | docs don't say | other (confirm publish / restore) | "Requires user confirmation before creating a page from a template, publishing, or restoring a revision." | docs don't say | dev doc |
| `manage_website_page` | docs don't say | other (confirm publish / restore / nav change) | "Requires user confirmation before creating a page, publishing, restoring a revision, or modifying navigation (`NAV_*` operations)." | docs don't say | dev doc |
| `manage_blog_post` | docs don't say | other (confirm create / publish) | New posts "are created as drafts; requires user confirmation before creating". Publishing "requires user confirmation before publishing". | docs don't say | dev doc |
| `manage_aeo_recommendations` | docs don't say | other (confirm action) | "Requires user confirmation before executing any action." | docs don't say | dev doc |

Write tools with no confirmation listed in the dev doc: `manage_custom_properties`, `manage_custom_pipelines`, `manage_marketing_email` (draft create/update/clone), `manage_social_posts` ("Create, update, or cancel posts"), `manage_aeo_prompts`.

Destructive operations: the dev doc lists no delete tool. The Claude connector KB article says: "The connector currently supports view, create, and update actions but does not support delete operations." The ChatGPT KB article's permissions tables have a Delete column with nothing in it for any object. The nearest operations to a delete are cancelling social posts and removing records from static segments.

Disambiguation: docs don't say. Account selection happens once, at sign-in ("Select the HubSpot account to connect", dev doc). The KB says "You can only connect one HubSpot account at a time to a single Claude account". To switch, you "disconnect one and connect to the other". Nothing describes the server asking which account, object, or record to use during a tool call.

Cost confirmation, secret entry: docs don't say.

## Fallback without client elicitation support

Docs don't say. The KB articles put write approval in the client. They recommend setting "Write tools" to "Needs Approval" in the Claude or ChatGPT connector settings and warn: "If you set the connector to _Always allow_, edits may occur without asking for approval." The KB also says "Claude may show you what the proposed changes are and ask for your confirmation before making any changes". The word "may" leaves it unclear whether a confirmation is guaranteed.

## Other human-in-the-loop mechanisms

- **Client tool approval.** "Needs Approval" vs "Always allow" for write tools, set in the AI client's connector settings (KB, Claude and ChatGPT).
- **Admin gate.** "For all other users to connect the HubSpot connector for Claude, a Super Admin must approve it and configure its data permissions and install access". Admins also choose "who in the account is allowed to install it" (Claude KB).
- **Permissions.** "All actions respect your existing HubSpot user permissions" (dev doc). Scopes are not chosen per tool: "you don't explicitly define the connector's scopes" (dev doc). New scopes require a re-install.
- **Sensitive Data.** With Sensitive Data on, conversation data is "blocked from access through the MCP server" (dev doc). In the Claude connector, "Claude cannot access any engagement data" (Claude KB).
- **Audit.** "All actions are attributed in your HubSpot account's Audit Log to both the user and the ChatGPT connector" (ChatGPT KB).
- **Sign-in.** OAuth with mandatory PKCE: "PKCE is required for authenticating with HubSpot's MCP server" (dev doc).
- **Annotations** (`readOnlyHint` / `destructiveHint`): docs don't say.

## Notes

- The confirmation wording sits inside the tool descriptions in the dev doc ("The tool presents a proposed-changes summary..."). From docs alone you can't tell whether the server enforces confirmation (an elicitation, or a two-step preview/commit) or whether the description only tells the model to ask. The KB's "may" phrasing and its advice to turn on client-side approval suggest it is not guaranteed. That is a reading of the wording, not a documented fact.
- The open CLI server (`hubspot.md`) confirms production deploys and shows account pickers. The hosted CRM docs describe no in-call picker.
