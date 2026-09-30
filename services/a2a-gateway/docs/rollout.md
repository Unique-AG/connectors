# Setup, administration and rollout

## Setup (operator)

1. Create the gateway PostgreSQL database and a secret `a2a-gateway` with `ENCRYPTION_KEY` (`openssl rand -hex 32`). Back the key up with the database.
2. Initialise Absurd once per database: `uvx absurdctl init -d $DATABASE_URL && uvx absurdctl create-queue -d $DATABASE_URL a2a-gateway`.
3. Deploy the chart ([README](../deploy/helm-charts/a2a-gateway/README.md)) with `a2aConfig.publicBaseUrl` (Kong host), `zitadelIssuer`, `corsAllowedOrigins` (admin frontend), the Unique service names and `a2aConfig.egress.allowedHosts` (remote agents and their OAuth token endpoints). Enable `extraRoutes.*` and `networkPolicy`. Migrations run as a hook.
4. Point node-chat at the gateway: `A2A_GATEWAY_URL=http://a2a-gateway.<ns>`. Without it core hides A2A, and native spaces are unaffected.
5. Check: `/health/ready` is 200, the metrics target is up, and a GET on a published card (after step 2 of the next section) returns 200 without a token.

Push notifications stay off unless a client needs them. They require `pushNotifications.allowedHosts`.

## Identity

External clients use the normal Zitadel user login of the tenant (authorization code + PKCE). Kong validates the token; the gateway never does. The protected-resource metadata at `/.well-known/oauth-protected-resource/a2a` tells clients which issuer to use. No machine-to-machine clients are supported, so every call acts as a Unique user with that user's current permissions.

## Administration (Space Admin)

| Task | Where |
| --- | --- |
| Publish a native space over A2A | Space → Advanced settings → A2A publication. The card shows only the name, description and skills you approve. |
| Unpublish | Same switch. Running tasks finish and stay readable; new sends are rejected and the card returns 404. |
| Add an external agent | New Space → A2A External Agent: card URL (host must be approved by the operator), credential, **Test connection**, save. |
| Rotate or revoke a credential | Edit the external space → Rotate credential → Test connection. Revoking disables the connection and keeps its configuration. |
| Use an external agent as sub-agent | Enable Sub-Agent on the external space, then add it to the parent space. |

External agent spaces can never be published, and a published space that is switched to an external agent stops accepting new work.

## Troubleshooting

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Chat: "External agents are currently unavailable" | gateway down or unreachable from node-chat | check the gateway pods, `/health/ready`, NetworkPolicy from node-chat |
| Chat: "rejected this space's connection credentials" | remote credential expired or rotated | rotate the credential in the space |
| Chat: "connection … disabled or not verified" | credential revoked, or a test never passed | edit the space, test the connection |
| Test connection: "remote destination is not approved" | host missing from `EGRESS_ALLOWED_HOSTS`, or not HTTPS | add the exact hostname to `a2aConfig.egress.allowedHosts` |
| Test connection: agent could not be reached | DNS resolves to a private address, TLS, or firewall | the gateway only calls public HTTPS addresses; check the Cilium FQDN rule |
| Client: 401 on `/a2a` | token missing or expired, or the route bypasses Kong | re-login; check the HTTPRoute has `unique-jwt-auth` |
| Client: `TaskNotFound` for an existing task | a different user, or retention expired | tasks are visible only to the user who created them |
| Client: 404 on the card or `publication not found` | unpublished, space deleted, rollout flag off, or the space became an external agent | check the publication and `FEATURE_FLAG_ENABLE_A2A` for the company |
| Client: 429 `too many concurrent streams` | more than 20 open SSE streams for one user on a replica | close unused subscriptions |
| Alert `A2aGatewayStuckRuns` | remote agent hangs or the worker is down | see the alert runbook; runs are recovered or reported as unknown |

Logs carry ids only: search by `executionId`, `taskId` or `connectionId` (`audit: true` records name who did what).

## Staged enablement

Conformance (TCK) and security e2e must pass in CI for the release. Inbound and outbound are released together.

1. Deploy the gateway with no tenant enabled (`FEATURE_FLAG_ENABLE_A2A` off everywhere). Check setup step 5 and that native chat is unchanged.
2. Enable the flag for an internal tenant. Run the journeys:
   - an external client (OAuth) calls a published native space: streaming, reconnect with `SubscribeToTask`, files, cancel
   - direct chat with an external space: multi-turn, files/JSON, approval and refusal, cancel
   - a native parent delegates to an external sub-agent
   - credential rotation
   - a gateway restart during a run
3. Watch for a week: `a2a_gateway_runs_finished_total{state=~"failed|unknown"}`, stuck runs, quota rejections, 5xx on the Kong routes.
4. Enable pilot tenants one at a time, after the operator has approved their remote agent hosts.
5. General availability: enable by default and keep per-tenant opt-out.

## Rollback

| Scope | Action | Effect |
| --- | --- | --- |
| One tenant | turn off `FEATURE_FLAG_ENABLE_A2A` for the company | new publish, configure and invoke rejected; running work finishes; data kept |
| One remote agent | revoke the credential or remove the host from the allowlist | its runs fail on the next call; other agents unaffected |
| Inbound only | disable `extraRoutes.protected`/`public` | external clients get 404; outbound keeps working |
| Everything | unset `A2A_GATEWAY_URL` in node-chat, then scale the gateway to 0 | core hides A2A; native spaces unaffected; the database stays for a later re-enable |

Cancel outbound runs first if remote side effects matter; remote agents are not notified. Rolling back a gateway release is safe because migrations are backward compatible (see [operations.md](./operations.md)).
