# Coinbase Payments MCP and AgentKit MCP extension

| Field | Value |
|---|---|
| Vendor | Coinbase (CDP); official |
| Category | payments (crypto wallet, x402 pay-per-request, onchain transfers and swaps) |
| Tier | 2 |
| Source | Payments MCP: installer open (https://github.com/coinbase/payments-mcp @ dddbf89). The server ships as a minified bundle downloaded from `https://payments-mcp.coinbase.com/install/payments-mcp-v<ver>.zip`; we statically grepped v2.12.2. AgentKit: open (https://github.com/coinbase/agentkit @ f2f3e8c) |
| Language / SDK | Payments MCP: TypeScript/Electron, bundled `@modelcontextprotocol/sdk` (protocol constant `2025-06-18`). AgentKit MCP extension: `@modelcontextprotocol/sdk` ^1.27.0 (pnpm-lock 1.27.1) |
| Hosted endpoint | none (both stdio; the Payments MCP bundle launches an Electron wallet app beside the server) |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code (AgentKit) + static grep of the distributed bundle (Payments MCP) |

## Elicitation usages

None in either project.

- **Payments MCP bundle v2.12.2.** `elicitInput` and the `elicitation/create` schema appear only as the SDK's own definitions. There is no call site (`.elicitInput(` occurs 0 times). The 13 tools are `bazaar_list`, `bazaar_search`, `bazaar_get_resource_details`, `get_wallet_address`, `show_wallet_app`, `get_wallet_balance`, `check_session_status`, `sign_in_with_email`, `verify_email_otp`, `send`, `trade`, `make_http_request_with_x402` and `x402_discover_payment_requirements`. The installer repo has no server code, so there is no line-level permalink.
- **AgentKit.** `getMcpTools` turns every AgentKit action into an MCP `Tool` with only `name`, `description` and `inputSchema`, then calls `action.invoke` directly ([index.ts#L23-L52](https://github.com/coinbase/agentkit/blob/f2f3e8c11a91d56a17979a229a172ba6e61a85c2/typescript/framework-extensions/model-context-protocol/src/index.ts#L23-L52)). The `create-onchain-agent` MCP template declares `capabilities: { tools: {} }` only ([templates/mcp/src/index.ts#L22](https://github.com/coinbase/agentkit/blob/f2f3e8c11a91d56a17979a229a172ba6e61a85c2/typescript/create-onchain-agent/templates/mcp/src/index.ts#L22)).

## Fallback without client elicitation support

Not applicable. Two flows in Payments MCP would suit elicitation, and both are done through the chat instead:

- **Email OTP sign-in** (`secret-input`/`auth` shape). `sign_in_with_email` sends a 6-digit code, and `verify_email_otp` takes "the 6-digit code the user received" as a tool argument. The OTP passes through the model's context.
- **Payment confirmation** (`confirm-cost` shape). `send` and `trade` descriptions say "IMPORTANT: This executes a real financial transaction ... Always confirm the recipient address, asset, and amount with the user before calling." That leaves the confirmation to the model, not the protocol.

## Other human-in-the-loop mechanisms

Payments MCP (bundle):

- **Wallet-app spending limits.** `send` is forwarded to the Electron window (`sendToWindow("send-transaction", …)`). Its description says "Transactions are subject to spending limits set in the wallet app". The limit is configured by the human in a separate UI, out of the model's reach.
- **Per-request cap on x402.** `make_http_request_with_x402` takes an optional `maxAmountPerRequest` (USDC atomic units). The model sets it.
- `revoke-token-approval` is described as "CLI-only (not exposed as an MCP tool)". The server deliberately keeps some wallet operations off the MCP surface.
- No tool annotations were found on the registered tools.

AgentKit MCP:

- **Testnet default.** The template's wallet provider uses `NETWORK_ID || "base-sepolia"` ([getAgentKit.ts#L25](https://github.com/coinbase/agentkit/blob/f2f3e8c11a91d56a17979a229a172ba6e61a85c2/typescript/create-onchain-agent/templates/mcp/src/agentkit/evm/cdp/getAgentKit.ts#L25)). The smart-wallet example warns when it falls back to testnet.
- **Two-step x402 "prepare then pay" by convention.** `make_http_request` returns the 402 payment requirements. `retry_http_request_with_x402` then pays ([x402ActionProvider.ts#L184](https://github.com/coinbase/agentkit/blob/f2f3e8c11a91d56a17979a229a172ba6e61a85c2/typescript/agentkit/src/action-providers/x402/x402ActionProvider.ts#L184), [#L365](https://github.com/coinbase/agentkit/blob/f2f3e8c11a91d56a17979a229a172ba6e61a85c2/typescript/agentkit/src/action-providers/x402/x402ActionProvider.ts#L365)). The one-shot `make_http_request_with_x402` is described as "WARNING: This action automatically handles payments without asking for confirmation! Only use this when explicitly told to skip the confirmation flow." ([#L550-L562](https://github.com/coinbase/agentkit/blob/f2f3e8c11a91d56a17979a229a172ba6e61a85c2/typescript/agentkit/src/action-providers/x402/x402ActionProvider.ts#L550-L562)). Both tools are exposed together, so the model decides whether to skip the confirmation step.
- **Hard limits in code.** `maxPaymentUsdc` defaults to 1.0 USDC (`X402_MAX_PAYMENT_USDC`), and larger payments are rejected with "Payment exceeds limit" ([#L67-L68](https://github.com/coinbase/agentkit/blob/f2f3e8c11a91d56a17979a229a172ba6e61a85c2/typescript/agentkit/src/action-providers/x402/x402ActionProvider.ts#L67-L68), [#L416-L423](https://github.com/coinbase/agentkit/blob/f2f3e8c11a91d56a17979a229a172ba6e61a85c2/typescript/agentkit/src/action-providers/x402/x402ActionProvider.ts#L416-L423)). There is also a service URL allowlist (`registeredServices`), and runtime registration is off by default ([schemas.ts#L13-L22](https://github.com/coinbase/agentkit/blob/f2f3e8c11a91d56a17979a229a172ba6e61a85c2/typescript/agentkit/src/action-providers/x402/schemas.ts#L13-L22)).
- **Action-provider allowlist.** The operator picks which action providers to load in `getAgentKit.ts`, which acts as the tool allowlist.

## Notes

- AgentKit's x402 provider is a clear case of a server *designing* a human confirmation step (prepare, review, pay) without being able to enforce it. Elicitation (`confirm-cost`) or an `InputRequiredResult` round-trip would let the server hold the payment until the user accepts, instead of trusting the model to pause between two tool calls.
- The Payments MCP server code is not in its GitHub repo; the repo only downloads and installs a versioned zip. Findings for it come from grepping that minified artifact and can change with any release.
