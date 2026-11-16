# GitHub MCP Server (hosted remote, api.githubcopilot.com/mcp)

| Field | Value |
|---|---|
| Vendor | GitHub; official |
| Category | dev-platform |
| Tier | 1 |
| Source | closed (https://api.githubcopilot.com/mcp/). Shares tool code with the open repo, see `github.md`. The README says the remote server has "additional tools that are not available in the local MCP server" |
| Language / SDK | docs don't say for the hosted deployment |
| Hosted endpoint | https://api.githubcopilot.com/mcp/ |
| Uses elicitation | unknown (the docs don't say whether the hosted server uses it) |
| Mechanism | unknown |
| Evidence type | docs only |

Permalink base for repo docs: `https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/`

## Elicitation usages

`github.md` describes the open-source code, which elicits a typed repository name before `delete_repository` and uses URL elicitation for browser sign-in. This file checks what the docs say about the hosted server.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `delete_repository` | docs don't say | confirm-destructive | The shared README says "Repository deletion still requires its existing confirmation flow before returning a completed result." It doesn't say what the flow asks, or whether the hosted server runs it. The typed-name prompt is documented only in code | docs don't say | [README.md#tools](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/README.md#tools) |
| Sign-in (hosted) | n/a (host-run OAuth, not elicitation) | auth-oauth | "The remote GitHub MCP server uses one-click OAuth authentication by default." In VS Code, "A pop-up will come up allowing you to authenticate with your GitHub account" | docs don't say | [docs.github.com setup](https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp/set-up-the-github-mcp-server) |
| A tool needs a scope the token lacks (hosted, OAuth) | n/a (OAuth scope challenge handled by the client) | auth-oauth (step-up) | The user is asked to grant the missing scope: "the server returns an OAuth scope challenge" and "Your MCP client prompts you to authorize the additional scope". `delete_repository` challenges for `delete_repo`, `repo` | docs don't say | [docs/scope-filtering.md](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/docs/scope-filtering.md), [README.md](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/README.md) |

## Fallback without client elicitation support

Docs don't say for the hosted server.

## Other human-in-the-loop mechanisms

- **Browser sign-in through URL elicitation is local only.** "OAuth login applies to the **stdio** server only. The remote server and the `http` command have their own authentication" ([docs/oauth-login.md](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/docs/oauth-login.md)). The hosted server relies on the host application's OAuth. "Each MCP host application needs to configure a GitHub App or OAuth App to support remote access via OAuth" ([README](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/README.md)). "Dynamic Client Registration is NOT supported by Remote GitHub MCP Server at this time" ([docs/host-integration.md](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/docs/host-integration.md)).
- **Read-only and toolset selection.** The `/readonly` path or the `X-MCP-Readonly` header enables only "read" tools. `/x/{toolset}` or `X-MCP-Toolsets` limit the toolsets ([docs/remote-server.md](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/docs/remote-server.md)).
- **Lockdown.** `X-MCP-Lockdown` hides "public issue details created by users without push access". It is a "best-effort content filter, not a security boundary" ([docs/remote-server.md](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/docs/remote-server.md)).
- **Admin policy.** "the "MCP servers in Copilot" policy must be enabled in order to use MCP with Copilot". Access "may also be limited by admin policies that control which scopes and apps are permitted" ([docs.github.com setup](https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp/set-up-the-github-mcp-server)). Organization OAuth App and GitHub App approval also applies. Admins "must approve OAuth App requests before host apps can access organization data" ([docs/policies-and-governance.md](https://github.com/github/github-mcp-server/blob/0663b830582af923e30fb14cb2e10dd3248baa86/docs/policies-and-governance.md)).
- **Start-up trust prompt in the client.** In VS Code, "When prompted, confirm that you trust the server to start it" ([docs.github.com setup](https://docs.github.com/en/copilot/how-tos/provide-context/use-mcp/set-up-the-github-mcp-server)). The client shows this prompt, not the server.
- **Disambiguation.** Docs don't say.

## Notes

- The [2026-07-23 changelog](https://github.blog/changelog/2026-07-23-github-mcp-server-supports-the-next-mcp-specification/) says: "Our stdio MCP server uses URL elicitation for easy user login." It also says, of remote servers in general: "You'll see more remote servers supporting features like elicitation thanks to multi round-trip requests." Neither sentence says that api.githubcopilot.com uses elicitation.
- Open question: does the hosted `delete_repository` run the same typed-name confirmation as the open code? The README's "existing confirmation flow" sentence covers the shared tool code and doesn't name a deployment. In the open code, the HTTP mode hides the tool unless a shared state key is configured (`github.md`). The docs don't say whether the hosted deployment sets one.
