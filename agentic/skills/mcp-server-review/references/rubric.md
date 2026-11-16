# MCP review rubric

As of 2026-11-13. Latest stable MCP spec: `2026-07-28`. Class: **N** normative,
**P** provider guidance, **S** synthesized. Severity: **P0** security/correctness
blocker, **P1** serious interoperability/reliability defect, **P2** quality.

Report only rules that fail. Quote evidence. `summary.json` field in parentheses.

## Protocol versions

Handshake era: `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`
(`initialize`, `Mcp-Session-Id`). Modern: `2026-07-28` (stateless, `server/discover`,
`resultType`, `Mcp-Method`/`Mcp-Name` headers, list caching `ttlMs`/`cacheScope`,
Tasks as an extension, Roots/Sampling/Logging/HTTP+SSE deprecated). Judge a server
against the revision it targets. Report legacy/deprecated features as status, not defects.

| ID | Cls | Sev | Rule | Check |
|----|-----|-----|------|-------|
| VER-001 | N | P0 | Supported revision(s) determined and consistent | `protocolVersion`, SDK version |
| VER-002 | N | P0 | `2026-07-28` server implements `server/discover` | `initialize --protocol-era modern` (Inspector has no `server/discover` method); else report "not verified" |
| VER-003 | N | P0 | Modern results carry valid `resultType`; mismatched version rejected | wire capture |
| HTTP-001 | N/S | P0 | `Mcp-Method`/`Mcp-Name` match body (modern) | send mismatch, expect rejection |
| HTTP-002 | P/S | P0 | Host/Origin policy and reverse-proxy trust prevent DNS rebinding | transport/proxy config |

## Auth and security

| ID | Cls | Sev | Rule | Check |
|----|-----|-----|------|-------|
| AUTH-001 | N | P0 | Server validates the token was issued for **this** server (audience) | verifier config; token for another resource must fail |
| AUTH-002 | N | P0 | No token passthrough: downstream API gets a separately issued token | downstream HTTP client code |
| AUTH-003 | N | P0 | OAuth: PKCE, issuer validation (RFC 9207), redirect URI validation, no ID tokens as access tokens | AS metadata, callback code |
| AUTH-004 | P/S | P0 | Per-tool and object-level authorization server-side, tenant isolation | user A with user B's id must fail without leakage |
| AUTH-005 | S | P0 | Application state handles bound to principal and tenant | replay another user's handle |
| AUTH-006 | N | P1 | Infra outage on token validation is 5xx, not 401 | simulate JWKS outage |
| SAFE-001 | P/S | P0 | Descriptions, results, external content treated as untrusted (injection) | scan descriptions and `instructions` for imperative text aimed at the model |
| SAFE-002 | P | P0 | High-impact actions need confirmation policy (client-specific) | annotations + host config |
| SAFE-003 | P/S | P1 | Annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`) match behaviour | compare to handler (`missing_annotations`, `no_readOnlyHint_or_destructiveHint`) |
| SUP-001 | P/S | P0/P1 | Provenance, pinned deps/images, update path, schema-drift detection, local-server sandboxing | lockfiles, image refs |
| PRIV-001 | P/S | P1 | Data minimization; retention/residency documented | result fields, policy |
| LOG-001 | N/P/S | P1 | Correlatable logs (trace id via `_meta`), no tokens or auth codes | grep logs |

## Tool design and agent compatibility

| ID | Cls | Sev | Rule | Check |
|----|-----|-----|------|-------|
| TOOL-001 | P/S | P1 | Name = domain + action, unique in the **effective** name the model sees (`github_search_issues`, not `search`) | `duplicate_names`, `generic_names`; consider host prefixing |
| TOOL-002 | S | P1 | Similar tools distinguishable by description (when to use vs neighbour) | read the closest pairs |
| TOOL-003 | P | P1 | Description says when/how to use, constraints, side effects, where ids come from, formats | `missing_description`, `short_description_lt_40` |
| TOOL-004 | P/S | P1 | Granularity follows intent/risk, not backend API shape: split on differing intent, auth, side effects; merge deterministic always-sequential chains | catalog + code |
| TOOL-005 | P/S | P1 | Catalog size measured, not capped: tool count, definition tokens, deferred discovery available | `tool_count`, `tool_definition_tokens_est` |
| SCHEMA-001 | N/P | P1 | Schemas match runtime; `outputSchema` matches `structuredContent`; root shape per revision (object root through `2025-11-25`) | `missing_outputSchema` (P2 alone), `strict_findings` |
| SCHEMA-002 | P/S | P1 | Avoid needless depth and `anyOf`/`oneOf`; broad conditional schemas suggest an over-broad tool | `deep_schemas_gt_4`, `uses_anyOf_oneOf` |
| SCHEMA-003 | P | P1 | Every parameter described | `params_without_description` |
| OUT-001 | P/S | P1 | Results bounded and continuation-complete: paging, filtering, resource links for large data | probe p50/max size |
| OUT-002 | S | P1 | Machine-readable stable ids returned for the next call | sample results |
| ERR-001 | P/S | P1 | Domain failures use `isError: true` with actionable, non-sensitive text, not success prose | probe bad args |
| REL-001 | P/S | P1 | Timeouts, bounded retries, rate limits, overload signals | code/config; 429 behaviour |
| REL-002 | S | P1 | Retried mutating tools do not duplicate effects (idempotency keys) | code review |
| DOC-001 | S | P2 | Server card: supported revisions, tested clients/models, tool count, auth mode, limits, typical latency/size | README |

Thresholds are heuristics, never lint failures: OpenAI suggests < 20 initially loaded
tools; Anthropic suggests tool search at 10+ tools or > 10k definition tokens and sees
selection decay around 30-50 loaded tools. "More than 20 tools is bad" and "128 tools max
in MCP" are both wrong as protocol claims.

## Multi-server interference (recommend, rarely measure)

Interference delta = performance(target + others) - performance(target only), on task
success, first-tool accuracy, cost, latency, unsafe-action rate. Variants: target only,
+ unrelated distractors, + semantically similar tools, + exact name collision, + alternate
interface (browser/CLI), + malicious-metadata server, + high-output server,
+ permission-asymmetric server. Run several samples per task. Reference harnesses:
Microsoft `mcp-interviewer` (research software, not a security audit; LLM judges can be
manipulated by malicious metadata) and `scaleapi/mcp-atlas`.

## Sources (verify before citing N-class findings)

- MCP release `2026-07-28`: https://blog.modelcontextprotocol.io/posts/2026-07-28/
- Changelog: `modelcontextprotocol/modelcontextprotocol` `docs/specification/2026-07-28/changelog.mdx`
- Auth security considerations: same repo, `docs/specification/2026-07-28/basic/authorization/security-considerations.mdx`
- Microsoft tool-space interference (2025-09-11): https://www.microsoft.com/en-us/research/blog/tool-space-interference-in-the-mcp-era-designing-for-agent-compatibility-at-scale/
- Azure MCP security: https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/security
- OpenAI: https://developers.openai.com/api/docs/guides/tools-connectors-mcp and `/guides/function-calling`
- Anthropic: https://www.anthropic.com/research/writing-tools-for-agents ; tool search docs on platform.claude.com
- Google: https://developers.google.com/connected-apps/mcp/server-optimization
- AWS: https://docs.aws.amazon.com/prescriptive-guidance/latest/mcp-strategies/mcp-governance-strategy.html
- OWASP MCP Top 10 (threat taxonomy, not normative): https://owasp.org/projects/mcp-top-10
