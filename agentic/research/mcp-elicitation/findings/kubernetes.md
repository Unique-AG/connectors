# Kubernetes MCP Server (containers/kubernetes-mcp-server)

| Field | Value |
|---|---|
| Vendor | containers org (Red Hat maintainers); community |
| Category | infra |
| Tier | 3 |
| Source | open (https://github.com/containers/kubernetes-mcp-server @ be8b260) |
| Language / SDK | Go, `github.com/modelcontextprotocol/go-sdk` v1.8.0 |
| Hosted endpoint | none (self-hosted binary / container, stdio or HTTP) |
| Uses elicitation | yes |
| Mechanism | legacy `elicitation/create` request |
| Evidence type | code |

## Elicitation usages

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Any tool matching a tool-level `confirmation_rules` entry (by tool name, or `destructive = true` matching the tool's `destructiveHint`). Checked before the handler runs. Operator-configured, no rules by default | form | `confirm-destructive` | The rule's `message` (several matching rules merged into one). Empty schema (`{type: object, properties: {}}`), so it is a plain accept/decline dialog | Anything other than `accept` returns a tool error "action requires confirmation"; the handler never runs | [tools_gosdk.go#L89](https://github.com/containers/kubernetes-mcp-server/blob/be8b26028df6af61fb3b7e7c6684f7f8eb1ae852/pkg/mcp/tools_gosdk.go#L89), [confirmation.go#L48](https://github.com/containers/kubernetes-mcp-server/blob/be8b26028df6af61fb3b7e7c6684f7f8eb1ae852/pkg/confirmation/confirmation.go#L48) |
| Any Kubernetes API call (inside any tool) that matches a kube-level rule on verb / kind / group / version / name / namespace. Checked in the HTTP round-tripper, once per API call | form | `confirm-destructive` (also used for sensitive reads, e.g. the documented "get Secret" example) | Rule `message`; same empty schema | Becomes a `PermissionDenied` validation error for that API call | [confirmation_validator.go#L26](https://github.com/containers/kubernetes-mcp-server/blob/be8b26028df6af61fb3b7e7c6684f7f8eb1ae852/pkg/kubernetes/confirmation_validator.go#L26), [accesscontrol_round_tripper.go#L113](https://github.com/containers/kubernetes-mcp-server/blob/be8b26028df6af61fb3b7e7c6684f7f8eb1ae852/pkg/kubernetes/accesscontrol_round_tripper.go#L113) |
| `windows-golden-image` **prompt** (`prompts/get`, kubevirt toolset) | form | `consent-data-sharing` (licence acceptance: Microsoft EULA) | "Microsoft EULA Notice: By proceeding, you agree to the Microsoft Software License Terms... Do you accept the Microsoft End User License Agreement (EULA)?" No schema fields | Prompt returns a "creation cancelled" message instead of the PipelineRun YAML | [windows_golden_image.go#L180](https://github.com/containers/kubernetes-mcp-server/blob/be8b26028df6af61fb3b7e7c6684f7f8eb1ae852/pkg/toolsets/kubevirt/windows_golden_image.go#L180) |
| Any create / update / patch of a Tekton `PipelineRun` that references the `windows-efi-installer` pipeline without `acceptEula=true` (for example through `resources_create_or_update`). Always on, regardless of config | form | `consent-data-sharing` (EULA acceptance, enforced server-side) | Same EULA question, worded for the PipelineRun. No schema | `PermissionDenied`: "Windows EULA was not accepted. The PipelineRun creation has been cancelled." | [windows_eula_validator.go#L68](https://github.com/containers/kubernetes-mcp-server/blob/be8b26028df6af61fb3b7e7c6684f7f8eb1ae852/pkg/kubernetes/windows_eula_validator.go#L68), [accesscontrol_round_tripper.go#L119](https://github.com/containers/kubernetes-mcp-server/blob/be8b26028df6af61fb3b7e7c6684f7f8eb1ae852/pkg/kubernetes/accesscontrol_round_tripper.go#L119) |

## Fallback without client elicitation support

The server does not check capabilities up front. It calls `session.Elicit` and treats the go-sdk's
"client does not support ... elicitation" error (matched by string, because the SDK exports no typed
error) as `ErrElicitationNotSupported`
([elicit.go#L29](https://github.com/containers/kubernetes-mcp-server/blob/be8b26028df6af61fb3b7e7c6684f7f8eb1ae852/pkg/mcp/elicit.go#L29)).
What happens next depends on the usage:

- **Confirmation rules:** set by the global `confirmation_fallback`. The default is `"allow"`, which
  proceeds silently and only logs a warning
  ([confirmation.go#L56](https://github.com/containers/kubernetes-mcp-server/blob/be8b26028df6af61fb3b7e7c6684f7f8eb1ae852/pkg/confirmation/confirmation.go#L56),
  [config.go#L474](https://github.com/containers/kubernetes-mcp-server/blob/be8b26028df6af61fb3b7e7c6684f7f8eb1ae852/pkg/config/config.go#L474)).
  With `"deny"` the action is blocked. The fallback is global only; a rule cannot set its own.
- **EULA prompt:** returns a guide with `acceptEula: "false"` in the YAML and tells the agent it
  "MUST ask the user" before setting it to true. The model is the fallback.
- **EULA validator:** denies the request and tells the agent to set `acceptEula` to `"true"` in the
  PipelineRun. That is a `confirm`-style argument the model can fill in by itself.

## Other human-in-the-loop mechanisms

- `read_only` (keeps only `readOnlyHint=true` tools) and `disable_destructive` (unregisters
  `destructiveHint=true` tools). `enabled_tools`, `disabled_tools`, `toolsets` and `denied_resources`
  restrict further.
- `validation_enabled` sends a `SelfSubjectAccessReview` RBAC pre-check and validates the schema
  before the call.
- The alert-management docs ask for a list, then a preview, then explicit user confirmation before
  writes. This is a prompt-level convention, not enforced.
- The docs call all of these "best-effort guardrails". Cluster RBAC is the real boundary.

## Notes

- This is the most complete design in this batch: elicitation is a generic, operator-configured
  policy engine that works at two layers (tool, and each Kubernetes API call). It is not hard-coded
  per tool.
- A kube-level rule can fire several times inside one tool call, once for each API request that
  matches.
- Elicitation runs during `prompts/get`, not only `tools/call`.
- The abstraction supports URL mode (`api.ElicitParams.URL`, `ElicitationID`), but only tests use it
  ([elicit_test.go#L148](https://github.com/containers/kubernetes-mcp-server/blob/be8b26028df6af61fb3b7e7c6684f7f8eb1ae852/pkg/mcp/elicit_test.go#L148)).
  No production code sends a URL elicitation.
- The default fallback is fail-open (`allow`). A rule an operator sets for safety does nothing in a
  client that cannot elicit unless they also set `deny`.
- There is no 2026-07-28 `InputRequiredResult` support yet. Everything uses the session back-channel.
