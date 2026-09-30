# OAuth onboarding

Use the existing Unique Zitadel authorization-code/PKCE flow and client onboarding. The user signs in; the calling client receives an access token and sends it as `Authorization: Bearer …` for A2A requests. Kong performs the existing token validation; the gateway uses trusted identity headers and checks current space permissions against core. No Zitadel actions, custom principal claims or Lua changes are required. Machine-to-machine onboarding is out of scope, not a separate token-classification policy.

Bootstrap: `GET /.well-known/oauth-protected-resource/a2a`, followed by the issuer's OIDC discovery document. Clients use PKCE S256, fresh `state` and OIDC `nonce`, and exact registered redirect URIs. Keep access tokens in memory and out of URLs, messages and logs. On expiry, use the existing refresh flow or repeat login; reconnect requires valid authentication for the same tenant/user. Running work may finish after token expiry, but every protected resource use still checks current core permissions. JWT revocation follows the existing platform policy; no immediate-revocation guarantee is added.

Public Agent Cards and RPC/streaming handlers remain pending their later epics. Keep catalog/extended cards protected, expose no `/internal` route, and restrict gateway ingress to trusted platform callers.
