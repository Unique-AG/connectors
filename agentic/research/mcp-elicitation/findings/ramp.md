# Ramp MCP (hosted)

| Field | Value |
|---|---|
| Vendor | Ramp; official |
| Category | banking (corporate cards, spend management) |
| Tier | 2 |
| Source | closed (https://mcp.ramp.com/mcp) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://mcp.ramp.com/mcp (OAuth); demo/sandbox https://demo-mcp.ramp.com/mcp; docs-only server https://mcp.ramp.com/developer/mcp |
| Uses elicitation | unknown (docs don't say) |
| Mechanism | n/a. Confirmation is documented as agent behaviour plus preview/confirm tool calls, not as server questions |
| Evidence type | docs only |

All sources read 2026-11-16. The tools reference page ([agents.ramp.com/docs/reference/agent-tools](https://agents.ramp.com/docs/reference/agent-tools)) renders only a placeholder component, so the tool list, descriptions and annotations could not be read.

## Elicitation usages

The docs don't describe the server asking the user anything during a tool call. They do describe confirmation steps, but each one is the agent asking the user in chat (written into Ramp's published skills) and then calling the tool again with a confirm action or flag.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Connect (OAuth consent) | url (sign-in at connect time) | auth-oauth | On the consent screen "the user chooses **Full access** or **Read-only**." | docs don't say | [agents.ramp.com/docs/guides/identity](https://agents.ramp.com/docs/guides/identity) |
| Travel booking (`SubmitFlightBooking`, `action=preview` then `action=confirm`) | n/a: agent asks in chat | confirm-cost | The user picks the exact option. "Ramp returns a fresh preview with the total, policy result, funding source, required approvals, and fare or cancellation terms." "The agent books only after an explicit confirmation". If anything changes after the preview, "the agent asks for confirmation again." | Confirm takes `expected_total_amount`. This "rejects the booking if the fare moved instead of quietly charging more." | [docs/guides/travel](https://agents.ramp.com/docs/guides/travel), [llms-full.txt (ramp-book-flight skill)](https://agents.ramp.com/llms-full.txt) |
| Travel cancellation | n/a: agent asks in chat | confirm-destructive | "Agents can preview cancellation terms and cancel an entire flight or hotel booking after a separate confirmation" | docs don't say | [docs/guides/travel](https://agents.ramp.com/docs/guides/travel) |
| Purchases (Agent Card checkout, Stripe MPP) | n/a: agent asks in chat | confirm-cost | "Before purchasing, the agent confirms the merchant, total, and funding source." For MPP, "the agent confirms the merchant, all-in amount and currency, purpose, and fund with the user." | docs don't say | [docs/guides/agentic-payments](https://agents.ramp.com/docs/guides/agentic-payments) |
| Physical card activation (`ramp cards activate`) | n/a: tool result tells the agent to ask | other (confirm a physical fact) | "If the result says delivery confirmation is required, ask the user to confirm that the physical card has arrived", then retry with `--confirm_delivery` | Without the flag the activation does not go through (implied by the retry instruction) | [llms-full.txt (card skill)](https://agents.ramp.com/llms-full.txt) |
| Approving travel requests (`TravelRequestAction`) | n/a: agent asks in chat | disambiguate | "If several requests were shown, ask which request they mean." | docs don't say | [llms-full.txt (approval skill)](https://agents.ramp.com/llms-full.txt) |
| Cancelling a flight or hotel by description | n/a: agent asks in chat | disambiguate | "show the likely matches and ask which one; never pick by hotel name, dates, or recency on your own." | docs don't say | [llms-full.txt (book-hotel skill)](https://agents.ramp.com/llms-full.txt) |
| Incorporation (SSN) | n/a: handed off to the Ramp app | secret-input (out of band) | "Never ask the user for their full SSN or SSN last-4 in chat". "SSN entry belongs in the Ramp application form". | n/a | [llms-full.txt (incorporation skill)](https://agents.ramp.com/llms-full.txt) |

## Fallback without client elicitation support

Docs don't say. None of the documented flows depend on a client capability. They rely on the agent following the skill text and on preview/confirm arguments.

## Other human-in-the-loop mechanisms

- Read-only versus full access is chosen per connection at consent. Troubleshooting note: "The connection may be read-only. Reconnect and choose **Full access**". ([connecting](https://agents.ramp.com/docs/guides/connecting))
- Identity: actions run "as the Ramp user who authorized the connection, with that user's permissions", and "Ramp attributes its actions to her." ([identity](https://agents.ramp.com/docs/guides/identity))
- Existing Ramp controls still apply. Purchases follow "each fund's spend limit, merchant rules, approvals". A flight that "needs manager approval stays pending until approval and ticketing finish." x402 purchases are the exception: "card or fund controls do not necessarily apply". ([payments](https://agents.ramp.com/docs/guides/agentic-payments), [travel](https://agents.ramp.com/docs/guides/travel))
- Admin controls: the role permission "Manage connections to Ramp via MCP, CLI and other AI connectors". Removing it from a user stops their connections. Admins can revoke connections in Settings → Developer → Connected AI tools, and connections expire after 30 days. ([support.ramp.com/managing-connected-ai-tools](https://support.ramp.com/managing-connected-ai-tools))
- Money-moving actions the user's role allows: an approver's AI tool can approve or reject items, and "Approving a bill can send it to payment." ([support.ramp.com/ramp-mcp](https://support.ramp.com/ramp-mcp)) A skill notes "No undo for approvals | Confirm with user before executing." ([llms-full.txt](https://agents.ramp.com/llms-full.txt))
- Standalone agents (early access) have their own identity and custom roles. "Adding it to an approval chain doesn't give it authority on its own." ([identity](https://agents.ramp.com/docs/guides/identity))
- Sandbox: a demo server with sample data at `demo-mcp.ramp.com`. ([connecting](https://agents.ramp.com/docs/guides/connecting))

## Notes

- Most of the confirmation and disambiguation text is in Ramp's skills: instructions for the agent, published at agents.ramp.com/skills and in the `ramp-public/skills` repository. Whether the server enforces them is mostly not documented. The exceptions are the `expected_total_amount` check on booking and the `--confirm_delivery` retry on card activation, which the skills say the server checks.
- Several skill examples show CLI commands. The docs say the same Agent Tools are "available through both Ramp MCP and Ramp CLI".
- Tool names in the table (`SubmitFlightBooking`, `TravelRequestAction`) come from skill text, not from the unrendered reference page.
