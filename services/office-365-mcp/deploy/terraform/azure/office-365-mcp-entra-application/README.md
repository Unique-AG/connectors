> [!WARNING]
> This module is **ALPHA**. Unique reserves the right to move, breakingly refactor, or deprecate the module at any stage without notice.

The Entra application registration users sign in to `office-365-mcp` through. It depends on no other
module: the caller supplies Azure ids, names, and a tool selection.

## The tool selection is the permission selection

Set **exactly one** of `tools_preset` or `tools_enabled`. You never write a Graph permission name
anywhere in this interface — the module derives the delegated permissions, and the subset needing
admin consent, from the tools selected. There is deliberately no default: "every tool" is the widest
consent screen a tenant can be asked for, so it has to be chosen (`tools_preset = "teams"`).

## The selection lives in two places and they must agree

The registration is written here. The pod's selection is written by the Argo overlay, as the
`office-365-mcp` chart's `env.TOOLS_PRESET` or `env.TOOLS_ENABLED` in `values.yaml` — exactly one of
the two there as well. Nothing at runtime compares the two.

Do not hand-write the overlay. `terraform output deployment_env` publishes, per `confidential_clients`
key, the resolved values under the chart's own key names; copy them across:

| `deployment_env` key | Overlay value |
| --- | --- |
| `PUBLIC_BASE_URL` | `env.PUBLIC_BASE_URL` |
| `ENTRA_TENANT_ID` | `env.ENTRA_TENANT_ID` |
| `ENTRA_CLIENT_ID` | `env.ENTRA_CLIENT_ID` |
| `TOOLS_ENABLED` | `env.TOOLS_ENABLED` (leave `env.TOOLS_PRESET` unset) |

It carries the resolved tool list and never a preset name on purpose: an overlay pinned to a preset
can widen itself on a chart bump, past a registration nobody re-applied. `ENTRA_CLIENT_SECRET` is
absent because it is a secret — read it from the Key Vault secret named in the `client_secrets`
output. If the pod ends up asking for more than the registration carries, sign-in fails at the
*authorize* hop for every user, with nothing in the pod's logs.

## Apply order

The tenant-wide grant is replaced wholesale on every apply, so the registration must never carry less
than the pod asks for, not even briefly:

| Change | Order |
| --- | --- |
| Widening the surface | `terraform apply` here **first**, then bump the overlay |
| Narrowing the surface | bump the overlay **first**, then `terraform apply` here |

## One registration is one tool surface

An app registration carries one delegated permission grant, so `confidential_clients` means "the
environments that agree on one tool surface". Two surfaces are two module blocks, each with its own
`display_name` and its own `secret_name_prefix`.

`secret_name_prefix` is required, has no default, and must start with `office-365-mcp`: it is what
keeps two registrations from overwriting each other's Key Vault secrets, and the pinned prefix keeps
a typo from overwriting another service's live secret in the shared vault.

## After the first apply

1. In Entra → App registrations, check the permissions show as `Configured permissions` and that they
   are `Granted`. If they are not, grant them (button, or the `admin_consent_url` output) and please
   open an issue — it is not yet fully clear how Azure resolves this.
2. `curl $PUBLIC_BASE_URL/manifest` on the deployed pod and diff its permission line against
   `terraform output tool_surface`. This is the only check that the overlay and the selection here
   were set to the same selection.
3. If the apply fails on the application's `identifierUris`, run it again — the URI is added by a
   second resource, so a second apply completes it.
4. If sign-in shows an unexpected consent prompt for `api://<client_id>/access_as_user`, add one
   `azuread_application_pre_authorized` resource for the app's own client id. It is not shipped
   because Graph plausibly rejects it when client and resource are the same application.
